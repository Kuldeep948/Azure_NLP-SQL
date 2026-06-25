"""Unit tests for the InputProcessor class.

Tests keyword heuristic classification, entity resolution,
CLU fallback behavior, and ambiguity detection.
"""

import pytest

from src.harness.input_processor import (
    ClassificationResult,
    InputProcessor,
    Tier,
    _ENTITY_MATCH_THRESHOLD,
)
from src.schema.metadata import ColumnSchema, SchemaMetadata, TableSchema


@pytest.fixture
def sample_schema() -> SchemaMetadata:
    """Create a minimal schema for testing."""
    return SchemaMetadata(
        tables={
            "customers": TableSchema(
                name="customers",
                columns=[
                    ColumnSchema(name="id", data_type="INT", nullable=False),
                    ColumnSchema(name="name", data_type="NVARCHAR(200)", nullable=False),
                    ColumnSchema(name="email", data_type="NVARCHAR(255)", nullable=False),
                    ColumnSchema(name="segment", data_type="NVARCHAR(50)", nullable=True),
                    ColumnSchema(name="region", data_type="NVARCHAR(100)", nullable=True),
                ],
                primary_keys=["id"],
                foreign_keys=[],
            ),
            "orders": TableSchema(
                name="orders",
                columns=[
                    ColumnSchema(name="id", data_type="INT", nullable=False),
                    ColumnSchema(name="customer_id", data_type="INT", nullable=False),
                    ColumnSchema(name="order_date", data_type="DATETIME2", nullable=True),
                    ColumnSchema(name="status", data_type="NVARCHAR(20)", nullable=True),
                    ColumnSchema(name="total_amount", data_type="DECIMAL(12,2)", nullable=True),
                ],
                primary_keys=["id"],
                foreign_keys=[],
            ),
            "products": TableSchema(
                name="products",
                columns=[
                    ColumnSchema(name="id", data_type="INT", nullable=False),
                    ColumnSchema(name="name", data_type="NVARCHAR(200)", nullable=False),
                    ColumnSchema(name="category", data_type="NVARCHAR(100)", nullable=True),
                    ColumnSchema(name="list_price", data_type="DECIMAL(10,2)", nullable=False),
                ],
                primary_keys=["id"],
                foreign_keys=[],
            ),
            "order_items": TableSchema(
                name="order_items",
                columns=[
                    ColumnSchema(name="id", data_type="INT", nullable=False),
                    ColumnSchema(name="order_id", data_type="INT", nullable=False),
                    ColumnSchema(name="product_id", data_type="INT", nullable=False),
                    ColumnSchema(name="quantity", data_type="INT", nullable=False),
                ],
                primary_keys=["id"],
                foreign_keys=[],
            ),
        }
    )


@pytest.fixture
def processor(sample_schema: SchemaMetadata) -> InputProcessor:
    """Create an InputProcessor with no CLU client (heuristic-only)."""
    return InputProcessor(clu_client=None, schema=sample_schema)


class TestKeywordHeuristics:
    """Tests for the _keyword_heuristics method."""

    def test_simple_query(self, processor: InputProcessor) -> None:
        tier, confidence = processor._keyword_heuristics("Show all customers")
        assert tier == Tier.SIMPLE
        assert confidence >= 0.6

    def test_filtered_query_with_count(self, processor: InputProcessor) -> None:
        tier, confidence = processor._keyword_heuristics(
            "How many orders were placed last month?"
        )
        assert tier == Tier.FILTERED
        assert confidence >= 0.6

    def test_filtered_query_with_aggregation(self, processor: InputProcessor) -> None:
        tier, confidence = processor._keyword_heuristics(
            "What is the total amount of orders with status pending?"
        )
        assert tier == Tier.FILTERED
        assert confidence >= 0.5

    def test_join_query(self, processor: InputProcessor) -> None:
        tier, confidence = processor._keyword_heuristics(
            "Show customers along with their orders"
        )
        assert tier == Tier.JOIN
        assert confidence >= 0.55

    def test_advanced_query_with_window_function(
        self, processor: InputProcessor
    ) -> None:
        tier, confidence = processor._keyword_heuristics(
            "Rank customers by total spending using row_number"
        )
        assert tier == Tier.ADVANCED
        assert confidence >= 0.6

    def test_advanced_query_with_cte(self, processor: InputProcessor) -> None:
        tier, confidence = processor._keyword_heuristics(
            "With top_buyers as (select customer_id from orders)"
        )
        assert tier == Tier.ADVANCED
        assert confidence >= 0.6

    def test_ambiguous_query_low_confidence(self, processor: InputProcessor) -> None:
        tier, confidence = processor._keyword_heuristics("xyz abc def")
        assert tier == Tier.AMBIGUOUS
        assert confidence < 0.6

    def test_empty_query(self, processor: InputProcessor) -> None:
        tier, confidence = processor._keyword_heuristics("")
        assert tier == Tier.AMBIGUOUS
        assert confidence < 0.6


class TestResolveEntities:
    """Tests for the _resolve_entities method."""

    def test_exact_match_not_included(self, processor: InputProcessor) -> None:
        """Exact schema matches should not appear in resolved_entities."""
        result = processor._resolve_entities("Show all customers")
        assert "customers" not in result

    def test_fuzzy_match_above_threshold(self, processor: InputProcessor) -> None:
        """Close misspellings should resolve to schema terms."""
        result = processor._resolve_entities("Show all custmers")
        assert "custmers" in result
        assert result["custmers"] == "customers"

    def test_fuzzy_match_below_threshold(self, processor: InputProcessor) -> None:
        """Completely unrelated terms should not resolve."""
        result = processor._resolve_entities("Show all xyzfoobar")
        assert "xyzfoobar" not in result

    def test_column_name_resolution(self, processor: InputProcessor) -> None:
        """Misspelled column names should resolve."""
        result = processor._resolve_entities("Get the categry of products")
        assert "categry" in result
        assert result["categry"] == "category"

    def test_stop_words_skipped(self, processor: InputProcessor) -> None:
        """Common stop words should not be resolved."""
        result = processor._resolve_entities("show the from all")
        assert len(result) == 0

    def test_short_tokens_skipped(self, processor: InputProcessor) -> None:
        """Tokens shorter than 3 characters should be skipped."""
        result = processor._resolve_entities("id is ab")
        assert "id" not in result
        assert "is" not in result
        assert "ab" not in result


class TestClassify:
    """Tests for the full classify() method."""

    @pytest.mark.asyncio
    async def test_simple_classification(self, processor: InputProcessor) -> None:
        result = await processor.classify("Show all customers")
        assert isinstance(result, ClassificationResult)
        assert result.tier == Tier.SIMPLE
        assert result.confidence >= 0.6
        assert result.clarification_prompt is None

    @pytest.mark.asyncio
    async def test_ambiguous_classification_returns_clarification(
        self, processor: InputProcessor
    ) -> None:
        result = await processor.classify("xyz abc def")
        assert result.tier == Tier.AMBIGUOUS
        assert result.clarification_prompt is not None
        assert len(result.clarification_prompt) > 0

    @pytest.mark.asyncio
    async def test_filtered_classification(self, processor: InputProcessor) -> None:
        result = await processor.classify("How many orders were placed last month?")
        assert result.tier == Tier.FILTERED
        assert result.confidence >= 0.6

    @pytest.mark.asyncio
    async def test_join_classification(self, processor: InputProcessor) -> None:
        result = await processor.classify(
            "Show customers along with their orders"
        )
        assert result.tier == Tier.JOIN

    @pytest.mark.asyncio
    async def test_advanced_classification(self, processor: InputProcessor) -> None:
        result = await processor.classify(
            "Use row_number to rank products by list_price"
        )
        assert result.tier == Tier.ADVANCED

    @pytest.mark.asyncio
    async def test_clu_fallback_when_none(self, processor: InputProcessor) -> None:
        """When CLU client is None, heuristics are used directly."""
        result = await processor.classify("List all products")
        assert result.tier in list(Tier)

    @pytest.mark.asyncio
    async def test_resolved_entities_in_result(
        self, processor: InputProcessor
    ) -> None:
        """Resolved entities should appear in the classification result."""
        result = await processor.classify("Show custmers with high spending")
        assert "custmers" in result.resolved_entities

    @pytest.mark.asyncio
    async def test_classification_result_always_valid_tier(
        self, processor: InputProcessor
    ) -> None:
        """Classification should always return a valid Tier enum value."""
        queries = [
            "Show all customers",
            "",
            "xyzabc",
            "How many orders with total greater than 100",
            "Join customers and orders on customer_id",
            "Use rank() over partition by category",
        ]
        for query in queries:
            result = await processor.classify(query)
            assert result.tier in list(Tier)
            assert 0.0 <= result.confidence <= 1.0


class TestCLUFallback:
    """Tests for CLU error fallback behavior."""

    @pytest.mark.asyncio
    async def test_clu_error_falls_back_to_heuristics(
        self, sample_schema: SchemaMetadata
    ) -> None:
        """When CLU client raises an exception, heuristics should be used."""

        class FaultyClient:
            def analyze_conversation(self, **kwargs):
                raise ConnectionError("CLU unreachable")

        processor = InputProcessor(
            clu_client=FaultyClient(),  # type: ignore[arg-type]
            schema=sample_schema,
        )
        result = await processor.classify("Show all customers")
        # Should succeed via heuristics, not raise
        assert result.tier in list(Tier)
