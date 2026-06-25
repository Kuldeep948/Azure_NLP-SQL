"""LLM Orchestrator — SQL generation via Azure OpenAI with retry, fallback, and token budget.

Uses LangChain/LangGraph to build a state machine that:
1. Attempts SQL generation with GPT-4o (primary)
2. Retries with exponential backoff on transient failures (429, 5xx)
3. Falls back to GPT-4 Turbo if primary exhausts retries
4. Manages token budgets by trimming few-shot examples
5. Records telemetry for every invocation (success or failure)

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, TypedDict

from langchain_openai import AzureChatOpenAI
from langgraph.graph import END, StateGraph

from src.nlp_to_sql.exceptions import LLMError, TokenBudgetExceededError
from src.nlp_to_sql.models import GenerationResult, TokenUsage

logger = logging.getLogger(__name__)

# Model context window limits (tokens) — conservative estimates leaving
# room for completion. These are the *prompt* token limits; we reserve
# space for the expected completion.
MODEL_CONTEXT_LIMITS: dict[str, int] = {
    "gpt-4o": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
}

# Cost per 1K tokens (USD) for supported models
COST_PER_1K_TOKENS: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    "gpt-4": {"input": 0.03, "output": 0.06},
}


def estimate_cost(model_name: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate cost in USD for a single LLM invocation.

    Uses per-1K-token pricing for known models. Falls back to gpt-4o pricing
    for unrecognized models.

    Args:
        model_name: The deployment/model name used for generation.
        prompt_tokens: Number of input (prompt) tokens consumed.
        completion_tokens: Number of output (completion) tokens generated.

    Returns:
        Estimated cost in USD (float).
    """
    # Try exact match, then prefix match
    pricing = COST_PER_1K_TOKENS.get(model_name)
    if pricing is None:
        for key, rates in COST_PER_1K_TOKENS.items():
            if key in model_name.lower():
                pricing = rates
                break
    if pricing is None:
        # Default to gpt-4o pricing
        pricing = COST_PER_1K_TOKENS["gpt-4o"]

    input_cost = (prompt_tokens / 1000.0) * pricing["input"]
    output_cost = (completion_tokens / 1000.0) * pricing["output"]
    return round(input_cost + output_cost, 6)

# Default max completion tokens to reserve
DEFAULT_MAX_COMPLETION_TOKENS: int = 4_096

# Approximate characters per token for budget estimation
CHARS_PER_TOKEN_ESTIMATE: float = 4.0


class TelemetryRecord(TypedDict):
    """Telemetry data recorded for each LLM invocation."""

    model_name: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: float
    success: bool
    error: str | None


class OrchestratorState(TypedDict):
    """LangGraph state for the generation pipeline."""

    nl_query: str
    rendered_prompt: str
    generated_sql: str | None
    model_used: str
    attempt_count: int
    token_usage: TokenUsage | None
    error: str | None
    # Internal tracking
    current_model: str  # "primary" or "fallback"
    primary_attempts: int
    fallback_attempts: int
    telemetry: list[TelemetryRecord]
    backoff_seconds: float


class LLMOrchestrator:
    """Orchestrates SQL generation with retry, fallback, and token budget management.

    Uses LangGraph StateGraph to manage the generation flow:
    - Primary model (GPT-4o) with up to max_retries attempts
    - Fallback model (GPT-4 Turbo) with up to max_retries attempts
    - Exponential backoff: min(initial_backoff * 2^(N-1), 16) seconds
    - Token budget enforcement with few-shot example trimming
    - Telemetry recording for every invocation
    """

    def __init__(
        self,
        primary_model: AzureChatOpenAI,
        fallback_model: AzureChatOpenAI,
        max_retries: int = 3,
        initial_backoff: float = 1.0,
        max_backoff: float = 16.0,
        max_completion_tokens: int = DEFAULT_MAX_COMPLETION_TOKENS,
    ) -> None:
        self._primary = primary_model
        self._fallback = fallback_model
        self._max_retries = max_retries
        self._initial_backoff = initial_backoff
        self._max_backoff = max_backoff
        self._max_completion_tokens = max_completion_tokens
        self._telemetry_records: list[TelemetryRecord] = []
        self._graph = self._build_graph()

    @property
    def telemetry_records(self) -> list[TelemetryRecord]:
        """Access recorded telemetry from all invocations."""
        return self._telemetry_records

    def _get_model_name(self, model: AzureChatOpenAI) -> str:
        """Extract the deployment/model name from a LangChain model instance."""
        # AzureChatOpenAI stores the deployment name
        return getattr(model, "deployment_name", None) or getattr(
            model, "azure_deployment", "unknown"
        )

    def _get_context_limit(self, model_name: str) -> int:
        """Get the context window limit for a model, defaulting conservatively."""
        # Check exact match first, then prefix match
        if model_name in MODEL_CONTEXT_LIMITS:
            return MODEL_CONTEXT_LIMITS[model_name]
        for key, limit in MODEL_CONTEXT_LIMITS.items():
            if key in model_name.lower():
                return limit
        # Conservative default
        return 8_192

    def _estimate_token_count(self, text: str) -> int:
        """Estimate token count from text length.

        Uses a conservative 4 characters per token estimate.
        For production, consider using tiktoken for exact counts.
        """
        return max(1, int(len(text) / CHARS_PER_TOKEN_ESTIMATE))

    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff delay for a given attempt number.

        Formula: min(initial_backoff * 2^(attempt-1), max_backoff)
        For attempts 1, 2, 3 with initial=1s: 1s, 2s, 4s (capped at 16s)
        """
        delay = self._initial_backoff * (2 ** (attempt - 1))
        return min(delay, self._max_backoff)

    def _check_token_budget(self, prompt: str, model: str) -> bool:
        """Verify prompt + expected completion fits within model context window.

        Args:
            prompt: The rendered prompt text.
            model: The model deployment name.

        Returns:
            True if within budget, False if exceeds.
        """
        prompt_tokens = self._estimate_token_count(prompt)
        context_limit = self._get_context_limit(model)
        available_for_prompt = context_limit - self._max_completion_tokens
        return prompt_tokens <= available_for_prompt

    def _trim_few_shot_examples(self, prompt: str, model: str) -> str:
        """Remove lowest-ranked few-shot examples until within budget.

        Few-shot examples are expected to be delimited in the prompt between
        markers like:
            <!-- FEW_SHOT_START -->
            Example 1: ...
            Example 2: ...
            <!-- FEW_SHOT_END -->

        Or between common delimiters. This method progressively removes
        examples from the end (lowest similarity rank) until the prompt
        fits within the token budget.

        Args:
            prompt: The rendered prompt text potentially exceeding budget.
            model: The model deployment name.

        Returns:
            The trimmed prompt.

        Raises:
            TokenBudgetExceededError: If prompt still exceeds budget after
                removing all few-shot examples.
        """
        # Try to find few-shot examples section using common patterns
        # Pattern 1: Explicit markers
        marker_pattern = r"(<!-- FEW_SHOT_START -->)(.*?)(<!-- FEW_SHOT_END -->)"
        marker_match = re.search(marker_pattern, prompt, re.DOTALL)

        if marker_match:
            return self._trim_with_markers(prompt, model, marker_match)

        # Pattern 2: Examples section with numbered examples
        # Look for patterns like "Example 1:", "Example 2:", etc.
        example_pattern = r"(Examples?:?\s*\n)((?:(?:Example\s+\d+|Q:|Question:|NL:).*?(?:\n\n|\Z))+)"
        example_match = re.search(example_pattern, prompt, re.DOTALL | re.IGNORECASE)

        if example_match:
            return self._trim_numbered_examples(prompt, model, example_match)

        # Pattern 3: Look for blocks separated by double newlines that look
        # like NL/SQL pairs
        pair_pattern = r"(\n\n(?:(?:NL|Q|Question|Natural Language):.*?\n(?:SQL|A|Answer|Expected SQL):.*?))"
        pairs = list(re.finditer(pair_pattern, prompt, re.DOTALL | re.IGNORECASE))

        if pairs:
            return self._trim_pair_blocks(prompt, model, pairs)

        # No recognizable few-shot examples found — check if prompt fits
        if self._check_token_budget(prompt, model):
            return prompt

        raise TokenBudgetExceededError(
            "Prompt exceeds token budget and no few-shot examples could be identified for trimming.",
            detail=f"Model: {model}, estimated tokens: {self._estimate_token_count(prompt)}, "
            f"limit: {self._get_context_limit(model) - self._max_completion_tokens}",
        )

    def _trim_with_markers(
        self, prompt: str, model: str, match: re.Match[str]
    ) -> str:
        """Trim few-shot examples found between explicit markers."""
        start_marker = match.group(1)
        examples_text = match.group(2)
        end_marker = match.group(3)

        # Split examples (double newline or numbered pattern)
        examples = re.split(r"\n\n+", examples_text.strip())
        examples = [e.strip() for e in examples if e.strip()]

        # Remove from the end (lowest-ranked) progressively
        while examples:
            remaining_text = "\n\n".join(examples)
            new_prompt = prompt[: match.start()] + start_marker + "\n" + remaining_text + "\n" + end_marker + prompt[match.end():]
            if self._check_token_budget(new_prompt, model):
                return new_prompt
            examples.pop()  # Remove last (lowest-ranked)

        # All examples removed — try with empty section
        new_prompt = prompt[: match.start()] + start_marker + "\n" + end_marker + prompt[match.end():]
        if self._check_token_budget(new_prompt, model):
            return new_prompt

        raise TokenBudgetExceededError(
            "Prompt exceeds token budget even after removing all few-shot examples.",
            detail=f"Model: {model}, estimated tokens: {self._estimate_token_count(new_prompt)}, "
            f"limit: {self._get_context_limit(model) - self._max_completion_tokens}",
        )

    def _trim_numbered_examples(
        self, prompt: str, model: str, match: re.Match[str]
    ) -> str:
        """Trim numbered few-shot examples."""
        header = match.group(1)
        examples_text = match.group(2)

        # Split individual examples
        examples = re.split(
            r"(?=(?:Example\s+\d+|Q:|Question:|NL:))",
            examples_text,
            flags=re.IGNORECASE,
        )
        examples = [e.strip() for e in examples if e.strip()]

        while examples:
            remaining = "\n\n".join(examples)
            new_prompt = prompt[: match.start()] + header + remaining + prompt[match.end():]
            if self._check_token_budget(new_prompt, model):
                return new_prompt
            examples.pop()

        # All removed
        new_prompt = prompt[: match.start()] + header + prompt[match.end():]
        if self._check_token_budget(new_prompt, model):
            return new_prompt

        raise TokenBudgetExceededError(
            "Prompt exceeds token budget even after removing all few-shot examples.",
            detail=f"Model: {model}",
        )

    def _trim_pair_blocks(
        self, prompt: str, model: str, pairs: list[re.Match[str]]
    ) -> str:
        """Trim NL/SQL pair blocks from the prompt."""
        # Work backwards (lowest-ranked last)
        remaining_pairs = list(pairs)

        while remaining_pairs:
            # Remove the last pair
            last_pair = remaining_pairs.pop()
            prompt = prompt[: last_pair.start()] + prompt[last_pair.end():]

            if self._check_token_budget(prompt, model):
                return prompt

        # All pairs removed
        if self._check_token_budget(prompt, model):
            return prompt

        raise TokenBudgetExceededError(
            "Prompt exceeds token budget even after removing all few-shot examples.",
            detail=f"Model: {model}",
        )

    def _record_telemetry(
        self,
        model_name: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: float = 0.0,
        success: bool = False,
        error: str | None = None,
    ) -> TelemetryRecord:
        """Record telemetry for an LLM invocation."""
        record: TelemetryRecord = {
            "model_name": model_name,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "latency_ms": latency_ms,
            "success": success,
            "error": error,
        }
        self._telemetry_records.append(record)
        logger.info(
            "LLM telemetry: model=%s, tokens=%d, latency=%.1fms, success=%s",
            model_name,
            record["total_tokens"],
            latency_ms,
            success,
        )
        return record

    async def _invoke_model(
        self, model: AzureChatOpenAI, prompt: str
    ) -> tuple[str, int, int]:
        """Invoke an Azure OpenAI model and return (sql, prompt_tokens, completion_tokens).

        Raises:
            Exception: On any model invocation failure (to be caught by retry logic).
        """
        from langchain_core.messages import HumanMessage

        response = await model.ainvoke([HumanMessage(content=prompt)])

        # Extract token usage from response metadata
        usage_metadata = getattr(response, "usage_metadata", None) or {}
        prompt_tokens = usage_metadata.get("input_tokens", 0) or 0
        completion_tokens = usage_metadata.get("output_tokens", 0) or 0

        # Also check response_metadata for token counts
        response_metadata = getattr(response, "response_metadata", {}) or {}
        token_usage = response_metadata.get("token_usage", {}) or {}
        if not prompt_tokens:
            prompt_tokens = token_usage.get("prompt_tokens", 0)
        if not completion_tokens:
            completion_tokens = token_usage.get("completion_tokens", 0)

        sql = response.content if isinstance(response.content, str) else str(response.content)
        return sql.strip(), prompt_tokens, completion_tokens

    def _build_graph(self) -> StateGraph:
        """Construct LangGraph state machine for generation with retry/fallback.

        The graph flow:
        1. check_budget → (within budget) → attempt_primary
        2. attempt_primary → (success) → done
        3. attempt_primary → (retry needed) → wait_and_retry_primary
        4. wait_and_retry_primary → attempt_primary (loop up to max_retries)
        5. attempt_primary → (all retries exhausted) → attempt_fallback
        6. attempt_fallback → (success) → done
        7. attempt_fallback → (retry needed) → wait_and_retry_fallback
        8. wait_and_retry_fallback → attempt_fallback (loop up to max_retries)
        9. attempt_fallback → (all retries exhausted) → fail
        """
        graph = StateGraph(OrchestratorState)

        # Add nodes
        graph.add_node("check_budget", self._node_check_budget)
        graph.add_node("attempt_primary", self._node_attempt_primary)
        graph.add_node("wait_primary", self._node_wait_primary)
        graph.add_node("attempt_fallback", self._node_attempt_fallback)
        graph.add_node("wait_fallback", self._node_wait_fallback)
        graph.add_node("success", self._node_success)
        graph.add_node("fail", self._node_fail)

        # Set entry point
        graph.set_entry_point("check_budget")

        # Add edges
        graph.add_conditional_edges(
            "check_budget",
            self._route_after_budget_check,
            {"attempt_primary": "attempt_primary", "fail": "fail"},
        )

        graph.add_conditional_edges(
            "attempt_primary",
            self._route_after_primary,
            {
                "success": "success",
                "wait_primary": "wait_primary",
                "attempt_fallback": "attempt_fallback",
            },
        )

        graph.add_edge("wait_primary", "attempt_primary")

        graph.add_conditional_edges(
            "attempt_fallback",
            self._route_after_fallback,
            {
                "success": "success",
                "wait_fallback": "wait_fallback",
                "fail": "fail",
            },
        )

        graph.add_edge("wait_fallback", "attempt_fallback")

        graph.add_edge("success", END)
        graph.add_edge("fail", END)

        return graph.compile()

    # --- Graph Nodes ---

    async def _node_check_budget(self, state: OrchestratorState) -> dict[str, Any]:
        """Check token budget and trim few-shot examples if needed."""
        prompt = state["rendered_prompt"]
        primary_model_name = self._get_model_name(self._primary)

        if not self._check_token_budget(prompt, primary_model_name):
            try:
                prompt = self._trim_few_shot_examples(prompt, primary_model_name)
                return {"rendered_prompt": prompt, "error": None}
            except TokenBudgetExceededError as exc:
                return {"error": str(exc)}

        return {"error": None}

    async def _node_attempt_primary(self, state: OrchestratorState) -> dict[str, Any]:
        """Attempt SQL generation with the primary model."""
        model_name = self._get_model_name(self._primary)
        attempt = state["primary_attempts"] + 1
        start_time = time.perf_counter()

        try:
            sql, prompt_tokens, completion_tokens = await self._invoke_model(
                self._primary, state["rendered_prompt"]
            )
            latency_ms = (time.perf_counter() - start_time) * 1000

            self._record_telemetry(
                model_name=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                success=True,
            )

            return {
                "generated_sql": sql,
                "model_used": model_name,
                "primary_attempts": attempt,
                "attempt_count": state["attempt_count"] + 1,
                "token_usage": TokenUsage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens,
                ),
                "error": None,
            }
        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000
            error_msg = str(exc)

            self._record_telemetry(
                model_name=model_name,
                latency_ms=latency_ms,
                success=False,
                error=error_msg,
            )

            logger.warning(
                "Primary model attempt %d/%d failed: %s",
                attempt,
                self._max_retries,
                error_msg,
            )

            return {
                "primary_attempts": attempt,
                "attempt_count": state["attempt_count"] + 1,
                "error": error_msg,
                "backoff_seconds": self._calculate_backoff(attempt),
            }

    async def _node_wait_primary(self, state: OrchestratorState) -> dict[str, Any]:
        """Wait with exponential backoff before retrying primary model."""
        backoff = state.get("backoff_seconds", self._initial_backoff)
        logger.info("Waiting %.1fs before retrying primary model...", backoff)
        await asyncio.sleep(backoff)
        return {}

    async def _node_attempt_fallback(self, state: OrchestratorState) -> dict[str, Any]:
        """Attempt SQL generation with the fallback model."""
        model_name = self._get_model_name(self._fallback)
        attempt = state["fallback_attempts"] + 1

        # Check token budget for fallback model
        prompt = state["rendered_prompt"]
        if not self._check_token_budget(prompt, model_name):
            try:
                prompt = self._trim_few_shot_examples(prompt, model_name)
            except TokenBudgetExceededError as exc:
                self._record_telemetry(
                    model_name=model_name,
                    success=False,
                    error=str(exc),
                )
                return {
                    "fallback_attempts": attempt,
                    "attempt_count": state["attempt_count"] + 1,
                    "error": str(exc),
                }

        start_time = time.perf_counter()

        try:
            sql, prompt_tokens, completion_tokens = await self._invoke_model(
                self._fallback, prompt
            )
            latency_ms = (time.perf_counter() - start_time) * 1000

            self._record_telemetry(
                model_name=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                success=True,
            )

            return {
                "generated_sql": sql,
                "model_used": model_name,
                "fallback_attempts": attempt,
                "attempt_count": state["attempt_count"] + 1,
                "token_usage": TokenUsage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens,
                ),
                "error": None,
            }
        except Exception as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000
            error_msg = str(exc)

            self._record_telemetry(
                model_name=model_name,
                latency_ms=latency_ms,
                success=False,
                error=error_msg,
            )

            logger.warning(
                "Fallback model attempt %d/%d failed: %s",
                attempt,
                self._max_retries,
                error_msg,
            )

            return {
                "fallback_attempts": attempt,
                "attempt_count": state["attempt_count"] + 1,
                "error": error_msg,
                "backoff_seconds": self._calculate_backoff(attempt),
            }

    async def _node_wait_fallback(self, state: OrchestratorState) -> dict[str, Any]:
        """Wait with exponential backoff before retrying fallback model."""
        backoff = state.get("backoff_seconds", self._initial_backoff)
        logger.info("Waiting %.1fs before retrying fallback model...", backoff)
        await asyncio.sleep(backoff)
        return {}

    async def _node_success(self, state: OrchestratorState) -> dict[str, Any]:
        """Terminal success state — no-op, just marks completion."""
        return {}

    async def _node_fail(self, state: OrchestratorState) -> dict[str, Any]:
        """Terminal failure state — no-op, marks completion with error."""
        return {}

    # --- Routing Functions ---

    def _route_after_budget_check(self, state: OrchestratorState) -> str:
        """Route after budget check: proceed if OK, fail if budget exceeded."""
        if state.get("error"):
            return "fail"
        return "attempt_primary"

    def _route_after_primary(self, state: OrchestratorState) -> str:
        """Route after primary attempt: success, retry, or fallback."""
        if state.get("generated_sql"):
            return "success"
        if state["primary_attempts"] < self._max_retries:
            return "wait_primary"
        # All primary retries exhausted → try fallback
        return "attempt_fallback"

    def _route_after_fallback(self, state: OrchestratorState) -> str:
        """Route after fallback attempt: success, retry, or fail."""
        if state.get("generated_sql"):
            return "success"
        if state["fallback_attempts"] < self._max_retries:
            return "wait_fallback"
        # All fallback retries exhausted → terminal failure
        return "fail"

    # --- Public API ---

    async def generate_sql(self, rendered_prompt: str) -> GenerationResult:
        """Execute the LangGraph and return generated SQL + telemetry.

        Args:
            rendered_prompt: The fully rendered prompt to send to the model.

        Returns:
            GenerationResult with SQL, model name, token counts, latency, and attempts.

        Raises:
            LLMError: If all retry/fallback attempts are exhausted.
            TokenBudgetExceededError: If prompt exceeds budget after trimming.
        """
        start_time = time.perf_counter()

        # Initialize state
        initial_state: OrchestratorState = {
            "nl_query": "",
            "rendered_prompt": rendered_prompt,
            "generated_sql": None,
            "model_used": "",
            "attempt_count": 0,
            "token_usage": None,
            "error": None,
            "current_model": "primary",
            "primary_attempts": 0,
            "fallback_attempts": 0,
            "telemetry": [],
            "backoff_seconds": self._initial_backoff,
        }

        # Execute the graph
        final_state = await self._graph.ainvoke(initial_state)

        total_latency_ms = (time.perf_counter() - start_time) * 1000

        # Check for token budget error specifically
        if final_state.get("error") and not final_state.get("generated_sql"):
            error_msg = final_state["error"]
            if "token budget" in error_msg.lower() or "exceeds" in error_msg.lower():
                raise TokenBudgetExceededError(
                    "The query and schema context is too large to process.",
                    detail=error_msg,
                )
            raise LLMError(
                "SQL generation service is temporarily unavailable.",
                detail=f"All retry attempts exhausted. Last error: {error_msg}",
            )

        if not final_state.get("generated_sql"):
            raise LLMError(
                "SQL generation service is temporarily unavailable.",
                detail="All retry attempts exhausted with no generated SQL.",
            )

        # Build result
        token_usage: TokenUsage | None = final_state.get("token_usage")
        prompt_tokens = token_usage.prompt_tokens if token_usage else 0
        completion_tokens = token_usage.completion_tokens if token_usage else 0

        return GenerationResult(
            sql=final_state["generated_sql"],
            model_name=final_state["model_used"],
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=total_latency_ms,
            attempt_count=final_state["attempt_count"],
        )
