"""Unit tests for the LLM Orchestrator.

Tests cover:
- Exponential backoff calculation
- Token budget checking
- Few-shot example trimming
- Successful generation with primary model
- Fallback to secondary model
- Failure after all retries exhausted
- Telemetry recording
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.harness.orchestrator import (
    DEFAULT_MAX_COMPLETION_TOKENS,
    LLMOrchestrator,
    OrchestratorState,
    TelemetryRecord,
)
from src.nlp_to_sql.exceptions import LLMError, TokenBudgetExceededError
from src.nlp_to_sql.models import GenerationResult


def _make_mock_model(deployment_name: str = "gpt-4o") -> MagicMock:
    """Create a mock AzureChatOpenAI model."""
    model = MagicMock()
    model.deployment_name = deployment_name
    model.azure_deployment = deployment_name
    return model


def _make_orchestrator(
    primary_name: str = "gpt-4o",
    fallback_name: str = "gpt-4-turbo",
    max_retries: int = 3,
    initial_backoff: float = 0.01,  # Use tiny backoff for tests
) -> LLMOrchestrator:
    """Create an LLMOrchestrator with mock models."""
    primary = _make_mock_model(primary_name)
    fallback = _make_mock_model(fallback_name)
    return LLMOrchestrator(
        primary_model=primary,
        fallback_model=fallback,
        max_retries=max_retries,
        initial_backoff=initial_backoff,
    )


class TestBackoffCalculation:
    """Tests for exponential backoff timing."""

    def test_backoff_attempt_1(self) -> None:
        orch = _make_orchestrator(initial_backoff=1.0)
        assert orch._calculate_backoff(1) == 1.0

    def test_backoff_attempt_2(self) -> None:
        orch = _make_orchestrator(initial_backoff=1.0)
        assert orch._calculate_backoff(2) == 2.0

    def test_backoff_attempt_3(self) -> None:
        orch = _make_orchestrator(initial_backoff=1.0)
        assert orch._calculate_backoff(3) == 4.0

    def test_backoff_capped_at_max(self) -> None:
        orch = _make_orchestrator(initial_backoff=1.0)
        # Attempt 5 would be 16s which equals max
        assert orch._calculate_backoff(5) == 16.0
        # Attempt 6 would be 32s but capped at 16s
        assert orch._calculate_backoff(6) == 16.0

    def test_backoff_with_custom_initial(self) -> None:
        orch = LLMOrchestrator(
            primary_model=_make_mock_model(),
            fallback_model=_make_mock_model("gpt-4-turbo"),
            initial_backoff=2.0,
        )
        assert orch._calculate_backoff(1) == 2.0
        assert orch._calculate_backoff(2) == 4.0
        assert orch._calculate_backoff(3) == 8.0


class TestTokenBudget:
    """Tests for token budget checking."""

    def test_short_prompt_within_budget(self) -> None:
        orch = _make_orchestrator()
        # Short prompt should be well within GPT-4o's 128k limit
        assert orch._check_token_budget("SELECT * FROM users", "gpt-4o") is True

    def test_long_prompt_exceeds_budget(self) -> None:
        orch = _make_orchestrator()
        # Create a prompt that definitely exceeds budget for gpt-4 (8192 tokens)
        huge_prompt = "x" * (8192 * 5)  # ~8192 tokens at 4 chars/token, way over gpt-4 limit
        assert orch._check_token_budget(huge_prompt, "gpt-4") is False

    def test_prompt_at_context_limit(self) -> None:
        orch = _make_orchestrator()
        # GPT-4 context is 8192 tokens, minus 4096 for completion = 4096 for prompt
        # At 4 chars/token, that's ~16384 characters
        prompt_at_limit = "x" * 16384
        assert orch._check_token_budget(prompt_at_limit, "gpt-4") is True

    def test_prompt_just_over_limit(self) -> None:
        orch = _make_orchestrator()
        # Just over the limit
        prompt_over = "x" * (16384 + 100)
        assert orch._check_token_budget(prompt_over, "gpt-4") is False


class TestTrimFewShotExamples:
    """Tests for few-shot example trimming."""

    def test_trim_with_explicit_markers(self) -> None:
        orch = _make_orchestrator()
        prompt = (
            "System prompt here.\n"
            "<!-- FEW_SHOT_START -->\n"
            "Example 1: Q: How many users?\nA: SELECT COUNT(*) FROM users\n\n"
            "Example 2: Q: List products\nA: SELECT * FROM products\n\n"
            "Example 3: Q: Total revenue\nA: SELECT SUM(amount) FROM orders\n"
            "<!-- FEW_SHOT_END -->\n"
            "Now generate SQL for: {query}"
        )
        # This should fit within budget for gpt-4o (128k context)
        result = orch._trim_few_shot_examples(prompt, "gpt-4o")
        assert "System prompt here" in result

    def test_trim_raises_when_still_exceeds(self) -> None:
        orch = LLMOrchestrator(
            primary_model=_make_mock_model(),
            fallback_model=_make_mock_model("gpt-4-turbo"),
            max_completion_tokens=4096,
        )
        # Create prompt that exceeds even GPT-4 limit without any examples
        huge_base = "x" * 50000  # Way more than 4096 tokens for gpt-4
        prompt = (
            huge_base
            + "\n<!-- FEW_SHOT_START -->\nExample 1\n<!-- FEW_SHOT_END -->\n"
        )
        with pytest.raises(TokenBudgetExceededError):
            orch._trim_few_shot_examples(prompt, "gpt-4")

    def test_trim_no_examples_within_budget(self) -> None:
        orch = _make_orchestrator()
        prompt = "Short prompt without examples"
        result = orch._trim_few_shot_examples(prompt, "gpt-4o")
        assert result == prompt

    def test_trim_no_examples_exceeds_budget(self) -> None:
        orch = _make_orchestrator()
        huge_prompt = "x" * 50000
        with pytest.raises(TokenBudgetExceededError):
            orch._trim_few_shot_examples(huge_prompt, "gpt-4")


class TestGenerateSQL:
    """Tests for the generate_sql method."""

    @pytest.mark.asyncio
    async def test_successful_primary_generation(self) -> None:
        orch = _make_orchestrator()

        # Mock successful model invocation
        mock_response = MagicMock()
        mock_response.content = "SELECT COUNT(*) FROM customers"
        mock_response.usage_metadata = {"input_tokens": 100, "output_tokens": 20}
        mock_response.response_metadata = {}
        orch._primary.ainvoke = AsyncMock(return_value=mock_response)

        result = await orch.generate_sql("Generate SQL for: How many customers?")

        assert isinstance(result, GenerationResult)
        assert result.sql == "SELECT COUNT(*) FROM customers"
        assert result.model_name == "gpt-4o"
        assert result.prompt_tokens == 100
        assert result.completion_tokens == 20
        assert result.attempt_count == 1
        assert result.latency_ms > 0

    @pytest.mark.asyncio
    async def test_fallback_after_primary_fails(self) -> None:
        orch = _make_orchestrator(initial_backoff=0.001)

        # Primary always fails
        orch._primary.ainvoke = AsyncMock(
            side_effect=Exception("Service unavailable")
        )

        # Fallback succeeds
        mock_response = MagicMock()
        mock_response.content = "SELECT * FROM orders"
        mock_response.usage_metadata = {"input_tokens": 80, "output_tokens": 15}
        mock_response.response_metadata = {}
        orch._fallback.ainvoke = AsyncMock(return_value=mock_response)

        result = await orch.generate_sql("Show all orders")

        assert result.sql == "SELECT * FROM orders"
        assert result.model_name == "gpt-4-turbo"
        # 3 primary attempts + 1 fallback attempt
        assert result.attempt_count == 4

    @pytest.mark.asyncio
    async def test_all_retries_exhausted_raises_llm_error(self) -> None:
        orch = _make_orchestrator(initial_backoff=0.001)

        # Both models always fail
        orch._primary.ainvoke = AsyncMock(
            side_effect=Exception("Rate limited")
        )
        orch._fallback.ainvoke = AsyncMock(
            side_effect=Exception("Service error")
        )

        with pytest.raises(LLMError) as exc_info:
            await orch.generate_sql("Generate SQL")

        assert "temporarily unavailable" in str(exc_info.value.message)

    @pytest.mark.asyncio
    async def test_telemetry_recorded_for_all_attempts(self) -> None:
        orch = _make_orchestrator(initial_backoff=0.001)

        # Primary fails twice, then succeeds
        call_count = 0

        async def primary_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception(f"Fail attempt {call_count}")
            mock_resp = MagicMock()
            mock_resp.content = "SELECT 1"
            mock_resp.usage_metadata = {"input_tokens": 50, "output_tokens": 5}
            mock_resp.response_metadata = {}
            return mock_resp

        orch._primary.ainvoke = AsyncMock(side_effect=primary_side_effect)

        result = await orch.generate_sql("test prompt")

        # Should have 3 telemetry records (2 failures + 1 success)
        assert len(orch.telemetry_records) == 3
        assert orch.telemetry_records[0]["success"] is False
        assert orch.telemetry_records[1]["success"] is False
        assert orch.telemetry_records[2]["success"] is True

    @pytest.mark.asyncio
    async def test_token_budget_exceeded_raises_specific_error(self) -> None:
        orch = LLMOrchestrator(
            primary_model=_make_mock_model(),
            fallback_model=_make_mock_model("gpt-4-turbo"),
            max_completion_tokens=4096,
            initial_backoff=0.001,
        )

        # Create a prompt that exceeds gpt-4 budget
        huge_prompt = "x" * 50000

        with pytest.raises((TokenBudgetExceededError, LLMError)):
            await orch.generate_sql(huge_prompt)

    @pytest.mark.asyncio
    async def test_telemetry_recorded_on_failure(self) -> None:
        orch = _make_orchestrator(initial_backoff=0.001, max_retries=1)

        orch._primary.ainvoke = AsyncMock(side_effect=Exception("error"))
        orch._fallback.ainvoke = AsyncMock(side_effect=Exception("error"))

        with pytest.raises(LLMError):
            await orch.generate_sql("test")

        # Should have telemetry for each attempt (1 primary + 1 fallback)
        assert len(orch.telemetry_records) == 2
        assert all(r["success"] is False for r in orch.telemetry_records)
        assert all(r["error"] is not None for r in orch.telemetry_records)


class TestEstimateTokenCount:
    """Tests for token count estimation."""

    def test_empty_string(self) -> None:
        orch = _make_orchestrator()
        assert orch._estimate_token_count("") == 1  # minimum of 1

    def test_known_length(self) -> None:
        orch = _make_orchestrator()
        # 100 chars / 4 chars per token = 25 tokens
        assert orch._estimate_token_count("x" * 100) == 25

    def test_short_text(self) -> None:
        orch = _make_orchestrator()
        assert orch._estimate_token_count("hi") == 1
