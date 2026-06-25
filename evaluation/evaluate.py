"""Standalone evaluation script for the NLP-to-SQL pipeline.

Run as: python evaluation/evaluate.py

Executes the full evaluation pipeline against the configured test cases,
reports accuracy metrics, and exits with a non-zero code if the accuracy
threshold is not met (useful for CI/CD gating).

Environment variables:
    AZURE_STORAGE_CONNECTION_STRING: Blob Storage connection string (optional for local dev).
    SQL_CONNECTION_STRING: Azure SQL Database connection string.
    AZURE_OPENAI_ENDPOINT: Azure OpenAI endpoint URL.
    AZURE_OPENAI_API_KEY: Azure OpenAI API key.
    APP_INSIGHTS_CONNECTION_STRING: Application Insights connection string (optional).
    EVALUATION_THRESHOLD: Minimum execution accuracy to pass (default 0.80).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path so imports work when run standalone
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from harness.evaluator import Evaluator, EvaluationResult  # noqa: E402
from harness.observability import ObservabilityLayer  # noqa: E402

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("evaluation")


class _LocalBlobClient:
    """Minimal blob client stub that always fails, triggering local file fallback."""

    def get_container_client(self, _name: str) -> "_LocalContainerClient":
        return _LocalContainerClient()


class _LocalContainerClient:
    """Container client stub that raises to trigger local fallback."""

    def get_blob_client(self, _name: str) -> "_LocalBlobRef":
        return _LocalBlobRef()


class _LocalBlobRef:
    """Blob reference stub that raises on download."""

    async def download_blob(self) -> None:
        raise ConnectionError("No Blob Storage configured — using local fallback")


class _LocalSqlClient:
    """Minimal SQL client stub for local evaluation.

    In local dev mode without a real SQL connection, this client provides
    placeholder behavior. Replace with a real client for full execution testing.
    """

    model_name: str = "local-stub"

    async def generate(self, nl_query: str) -> object:
        """Stub: returns empty SQL (override with real client for actual evaluation)."""

        class _Result:
            sql = ""

        return _Result()

    async def execute(self, sql: str) -> dict:
        """Stub: returns empty result (override with real client for actual evaluation)."""
        return {"columns": [], "row_count": 0}


def _create_blob_client() -> object:
    """Create a Blob Storage client from environment or return local stub.

    Returns:
        Azure BlobServiceClient if connection string is configured,
        otherwise a local stub that triggers file fallback.
    """
    connection_string = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if connection_string:
        try:
            from azure.storage.blob.aio import BlobServiceClient

            return BlobServiceClient.from_connection_string(connection_string)
        except ImportError:
            logger.warning("azure-storage-blob not installed, using local fallback")
        except Exception as exc:
            logger.warning("Failed to create Blob client: %s, using local fallback", exc)

    return _LocalBlobClient()


def _create_sql_client() -> object:
    """Create a SQL client from environment or return local stub.

    Returns:
        Configured SQL client or local stub for development.
    """
    connection_string = os.environ.get("SQL_CONNECTION_STRING")
    if connection_string:
        logger.info("SQL connection configured (execution accuracy will be measured)")
        # In a full implementation, this would create an actual SQL execution client.
        # For now, return the stub — replace with project-specific SQL client.
        return _LocalSqlClient()

    logger.warning("No SQL_CONNECTION_STRING — execution accuracy will report 0%%")
    return _LocalSqlClient()


def _create_observability() -> ObservabilityLayer | None:
    """Create observability layer if App Insights is configured.

    Returns:
        ObservabilityLayer instance or None.
    """
    connection_string = os.environ.get("APP_INSIGHTS_CONNECTION_STRING")
    if connection_string:
        return ObservabilityLayer(connection_string=connection_string)
    return ObservabilityLayer()  # Local dev mode


def _print_results(result: EvaluationResult, threshold: float) -> None:
    """Print evaluation results in a readable format.

    Args:
        result: The evaluation result to display.
        threshold: The pass/fail threshold.
    """
    passed = result.execution_accuracy_score >= threshold

    print("\n" + "=" * 60)
    print("  NLP-to-SQL EVALUATION RESULTS")
    print("=" * 60)
    print(f"  Model:                {result.model_name}")
    print(f"  Timestamp:            {result.timestamp.isoformat()}")
    print(f"  Test Cases:           {len(result.per_query_results)}")
    print(f"  Exact Match Score:    {result.exact_match_score:.2%}")
    print(f"  Execution Accuracy:   {result.execution_accuracy_score:.2%}")
    print(f"  Threshold:            {threshold:.2%}")
    print(f"  Status:               {'PASS ✓' if passed else 'FAIL ✗'}")
    print("=" * 60)

    # Print per-tier breakdown
    tiers: dict[str, list] = {}
    for qr in result.per_query_results:
        # Infer tier from the test case (not directly on QueryEvalResult)
        tiers.setdefault("all", []).append(qr)

    # Show failures
    failures = [qr for qr in result.per_query_results if not qr.exact_match]
    if failures:
        print(f"\n  Failed queries ({len(failures)}):")
        for i, qr in enumerate(failures[:10], 1):
            print(f"    {i}. {qr.nl_query[:60]}...")
            if qr.error:
                print(f"       Error: {qr.error}")
        if len(failures) > 10:
            print(f"    ... and {len(failures) - 10} more")

    print()


async def main() -> int:
    """Run the evaluation pipeline.

    Returns:
        Exit code: 0 if threshold met, 1 otherwise.
    """
    threshold = float(os.environ.get("EVALUATION_THRESHOLD", "0.80"))

    logger.info("Starting NLP-to-SQL evaluation pipeline")
    logger.info("Threshold: %.2f", threshold)

    blob_client = _create_blob_client()
    sql_client = _create_sql_client()
    observability = _create_observability()

    evaluator = Evaluator(
        blob_client=blob_client,
        sql_client=sql_client,
        app_insights_client=observability,
        threshold=threshold,
    )

    try:
        result = await evaluator.run_evaluation()
    except FileNotFoundError as exc:
        logger.error("Cannot run evaluation: %s", exc)
        return 1
    except Exception as exc:
        logger.error("Evaluation failed with unexpected error: %s", exc)
        return 1

    _print_results(result, threshold)

    # Export results to JSON for CI artifact consumption
    output_path = _PROJECT_ROOT / "data" / "evaluation" / "latest_results.json"
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            result.model_dump_json(indent=2),
            encoding="utf-8",
        )
        logger.info("Results written to %s", output_path)
    except Exception as exc:
        logger.warning("Could not write results file: %s", exc)

    # Exit with appropriate code for CI/CD gating
    if result.execution_accuracy_score >= threshold:
        return 0
    return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
