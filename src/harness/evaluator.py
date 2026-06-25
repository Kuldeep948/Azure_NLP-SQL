"""Evaluator — automated accuracy measurement against ground-truth datasets.

Provides objective CI/CD gating by comparing generated SQL against expected
SQL using exact-match and execution-accuracy metrics.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Default path for local fallback test cases
_LOCAL_TEST_CASES_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "evaluation" / "test_cases.json"


class TestCase(BaseModel):
    """A single evaluation test case loaded from Blob Storage or local file.

    Attributes:
        nl_query: The natural language query to evaluate.
        expected_sql: Ground-truth SQL that the query should generate.
        tier: Complexity tier (simple, filtered, join, advanced).
        description: Human-readable description of what the test validates.
    """

    nl_query: str
    expected_sql: str
    tier: str = "unknown"
    description: str = ""


class QueryEvalResult(BaseModel):
    """Result of evaluating a single query against its expected output.

    Attributes:
        nl_query: The natural language query that was evaluated.
        expected_sql: The ground-truth SQL.
        generated_sql: The SQL produced by the pipeline.
        exact_match: Whether normalized SQL strings are identical.
        execution_match: Whether executing both queries produces equivalent results.
        latency_ms: Time taken for SQL generation in milliseconds.
        error: Error message if generation or execution failed, None otherwise.
    """

    nl_query: str
    expected_sql: str
    generated_sql: str
    exact_match: bool
    execution_match: bool
    latency_ms: float = 0.0
    error: str | None = None


class EvaluationResult(BaseModel):
    """Aggregate evaluation result across all test cases.

    Attributes:
        exact_match_score: Fraction of test cases with exact SQL match (0.0–1.0).
        execution_accuracy_score: Fraction with equivalent execution results (0.0–1.0).
        per_query_results: Detailed results for each individual test case.
        model_name: Name of the model used for generation.
        timestamp: UTC timestamp when the evaluation was run.
    """

    model_config = {"protected_namespaces": ()}

    exact_match_score: float
    execution_accuracy_score: float
    per_query_results: list[QueryEvalResult]
    model_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Evaluator:
    """Runs automated evaluation of the NLP-to-SQL pipeline.

    Loads test cases from Azure Blob Storage (with local file fallback for dev),
    generates SQL for each, compares against expected results using exact-match
    and execution-accuracy metrics, and reports scores for CI/CD gating.

    Args:
        blob_client: Azure Blob Storage async client for loading test cases.
        sql_client: Client capable of generating SQL and executing queries.
        app_insights_client: Optional ObservabilityLayer for metric reporting.
        threshold: Minimum execution accuracy score to pass (default 0.80).
    """

    def __init__(
        self,
        blob_client: Any,
        sql_client: Any,
        app_insights_client: Any | None = None,
        threshold: float = 0.80,
    ) -> None:
        self._blob_client = blob_client
        self._sql_client = sql_client
        self._app_insights_client = app_insights_client
        self._threshold = threshold

    async def load_test_cases(self) -> list[TestCase]:
        """Load evaluation test cases from Azure Blob Storage.

        Falls back to loading from the local filesystem if Blob Storage
        is unavailable (useful for local development and CI).

        Returns:
            List of TestCase instances for evaluation.

        Raises:
            FileNotFoundError: If neither blob storage nor local file is available.
        """
        # Try loading from Blob Storage first
        try:
            container_client = self._blob_client.get_container_client("evaluation")
            blob_client = container_client.get_blob_client("test_cases.json")
            download = await blob_client.download_blob()
            content = await download.readall()
            data = json.loads(content)

            test_cases = self._parse_test_cases(data)
            logger.info("Loaded %d test cases from Blob Storage", len(test_cases))
            return test_cases

        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to load test cases from Blob Storage: %s. "
                "Falling back to local file.",
                exc,
            )

        # Fallback: load from local file
        return self._load_local_test_cases()

    def _load_local_test_cases(self) -> list[TestCase]:
        """Load test cases from the local filesystem as a development fallback.

        Returns:
            List of TestCase instances.

        Raises:
            FileNotFoundError: If the local test cases file does not exist.
        """
        if not _LOCAL_TEST_CASES_PATH.exists():
            raise FileNotFoundError(
                f"Local test cases file not found at {_LOCAL_TEST_CASES_PATH}. "
                "Ensure data/evaluation/test_cases.json exists or configure Blob Storage."
            )

        data = json.loads(_LOCAL_TEST_CASES_PATH.read_text(encoding="utf-8"))
        test_cases = self._parse_test_cases(data)
        logger.info("Loaded %d test cases from local file: %s", len(test_cases), _LOCAL_TEST_CASES_PATH)
        return test_cases

    @staticmethod
    def _parse_test_cases(data: list[dict[str, Any]]) -> list[TestCase]:
        """Parse raw JSON data into TestCase instances.

        Args:
            data: List of dictionaries from JSON parsing.

        Returns:
            List of validated TestCase instances.
        """
        test_cases: list[TestCase] = []
        for item in data:
            test_cases.append(
                TestCase(
                    nl_query=item["nl_query"],
                    expected_sql=item["expected_sql"],
                    tier=item.get("tier", "unknown"),
                    description=item.get("description", ""),
                )
            )
        return test_cases

    async def run_evaluation(self) -> EvaluationResult:
        """Execute full evaluation against all loaded test cases.

        For each test case:
        1. Generate SQL via the pipeline
        2. Compare normalized SQL for exact match
        3. Execute both expected and generated SQL, compare results

        Returns:
            EvaluationResult with aggregate scores and per-query detail.
        """
        test_cases = await self.load_test_cases()
        per_query_results: list[QueryEvalResult] = []
        exact_matches = 0
        execution_matches = 0

        for test_case in test_cases:
            start_time = time.perf_counter()
            error: str | None = None

            # Generate SQL for the NL query via the SQL client
            try:
                generated_sql = await self._generate_sql(test_case.nl_query)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "SQL generation failed for query '%s': %s",
                    test_case.nl_query,
                    exc,
                )
                generated_sql = ""
                error = str(exc)

            latency_ms = (time.perf_counter() - start_time) * 1000

            # Exact match comparison (normalized)
            exact_match = (
                self.normalize_sql(generated_sql) == self.normalize_sql(test_case.expected_sql)
            )
            if exact_match:
                exact_matches += 1

            # Execution accuracy comparison
            execution_match = False
            if not error:
                try:
                    execution_match = await self._compare_execution(
                        generated_sql, test_case.expected_sql
                    )
                    if execution_match:
                        execution_matches += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Execution comparison failed for query '%s': %s",
                        test_case.nl_query,
                        exc,
                    )
                    if not error:
                        error = f"Execution comparison failed: {exc}"

            per_query_results.append(
                QueryEvalResult(
                    nl_query=test_case.nl_query,
                    expected_sql=test_case.expected_sql,
                    generated_sql=generated_sql,
                    exact_match=exact_match,
                    execution_match=execution_match,
                    latency_ms=latency_ms,
                    error=error,
                )
            )

        total = len(test_cases) if test_cases else 1
        result = EvaluationResult(
            exact_match_score=exact_matches / total,
            execution_accuracy_score=execution_matches / total,
            per_query_results=per_query_results,
            model_name=self._get_model_name(),
            timestamp=datetime.now(timezone.utc),
        )

        # Report to App Insights if available
        if self._app_insights_client:
            try:
                self._app_insights_client.record_metric(
                    "evaluation_exact_match_score",
                    result.exact_match_score,
                    {"model": result.model_name},
                )
                self._app_insights_client.record_metric(
                    "evaluation_execution_accuracy_score",
                    result.execution_accuracy_score,
                    {"model": result.model_name},
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to report metrics to App Insights: %s", exc)

        passed = result.execution_accuracy_score >= self._threshold
        logger.info(
            "Evaluation complete: exact_match=%.2f, execution_accuracy=%.2f, "
            "threshold=%.2f, pass=%s",
            result.exact_match_score,
            result.execution_accuracy_score,
            self._threshold,
            passed,
        )

        return result

    def normalize_sql(self, sql: str) -> str:
        """Normalize SQL for exact-match comparison.

        Strips leading/trailing whitespace, collapses internal whitespace,
        and converts to lower-case. This operation is idempotent.

        Args:
            sql: Raw SQL string to normalize.

        Returns:
            Normalized SQL string (stripped, collapsed, lowered).
        """
        if not sql:
            return ""
        normalized = sql.strip()
        normalized = re.sub(r"\s+", " ", normalized)
        normalized = normalized.lower()
        return normalized

    def compare_execution_results(
        self,
        actual_columns: list[str],
        actual_row_count: int,
        expected_columns: list[str],
        expected_row_count: int,
    ) -> bool:
        """Compare execution results for equivalence.

        Uses case-insensitive, order-independent column name comparison
        and row count equality.

        Args:
            actual_columns: Column names from actual query execution.
            actual_row_count: Number of rows from actual execution.
            expected_columns: Column names from expected query execution.
            expected_row_count: Number of rows from expected execution.

        Returns:
            True if columns match (case-insensitive, order-independent)
            and row counts are equal.
        """
        actual_cols_normalized = sorted(col.lower().strip() for col in actual_columns)
        expected_cols_normalized = sorted(col.lower().strip() for col in expected_columns)

        columns_match = actual_cols_normalized == expected_cols_normalized
        rows_match = actual_row_count == expected_row_count

        return columns_match and rows_match

    async def _generate_sql(self, nl_query: str) -> str:
        """Generate SQL for a given NL query using the configured SQL client.

        Args:
            nl_query: Natural language query to convert.

        Returns:
            Generated SQL string.
        """
        result = await self._sql_client.generate(nl_query)
        if hasattr(result, "sql"):
            return result.sql
        return str(result)

    async def _compare_execution(self, generated_sql: str, expected_sql: str) -> bool:
        """Execute both SQL queries and compare their results.

        Args:
            generated_sql: SQL generated by the pipeline.
            expected_sql: Ground-truth SQL from the test case.

        Returns:
            True if execution results are equivalent, False otherwise.
        """
        if not generated_sql:
            return False

        try:
            # Execute generated SQL
            actual_result = await self._sql_client.execute(generated_sql)
            actual_columns = actual_result.get("columns", [])
            actual_row_count = actual_result.get("row_count", 0)

            # Execute expected SQL
            expected_result = await self._sql_client.execute(expected_sql)
            expected_columns = expected_result.get("columns", [])
            expected_row_count = expected_result.get("row_count", 0)

            return self.compare_execution_results(
                actual_columns,
                actual_row_count,
                expected_columns,
                expected_row_count,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Execution comparison error: %s", exc)
            return False

    def _get_model_name(self) -> str:
        """Get the model name from the SQL client or return default.

        Returns:
            Model name string.
        """
        if hasattr(self._sql_client, "model_name"):
            return self._sql_client.model_name
        return "unknown"
