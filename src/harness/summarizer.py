"""Result Summarizer — generates natural language summaries of SQL query results.

Uses Azure OpenAI to produce concise, business-friendly summaries of tabular
query results (e.g., "Total revenue last quarter was $2.4M, with the West
region contributing 38%.").

Assignment Reference: Section 6.4 — Query Execution & Result Presentation
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Maximum rows to include in the summarization prompt (to manage token usage)
_MAX_ROWS_FOR_SUMMARY = 50


class ResultSummarizer:
    """Generates natural language summaries of query results using Azure OpenAI.

    Args:
        openai_client: Azure OpenAI async client for chat completions.
        model_deployment: Deployment name to use for summarization (default: gpt-4o).
    """

    def __init__(
        self,
        openai_client: Any,
        model_deployment: str = "gpt-4o",
    ) -> None:
        self._client = openai_client
        self._model = model_deployment

    async def summarize(
        self,
        nl_query: str,
        columns: list[dict[str, str]],
        rows: list[dict[str, Any]],
        row_count: int,
        truncated: bool = False,
    ) -> str:
        """Generate a natural language summary of the query results.

        Args:
            nl_query: The original user question.
            columns: Column metadata (name + data_type).
            rows: Result rows (limited to first _MAX_ROWS_FOR_SUMMARY).
            row_count: Total number of rows returned.
            truncated: Whether the result set was truncated.

        Returns:
            A concise natural language summary of the results.
            Returns empty string if summarization fails (non-blocking).
        """
        try:
            # Limit rows sent to the LLM to manage token budget
            display_rows = rows[:_MAX_ROWS_FOR_SUMMARY]

            prompt = self._build_summary_prompt(
                nl_query=nl_query,
                columns=columns,
                rows=display_rows,
                row_count=row_count,
                truncated=truncated,
            )

            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a data analyst assistant. Summarize the SQL query "
                            "results in 1-3 sentences using plain business language. "
                            "Highlight key metrics, trends, or notable values. "
                            "Use appropriate formatting for numbers (currency, percentages). "
                            "Do not mention SQL or technical database concepts."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=200,
            )

            summary = response.choices[0].message.content.strip()
            logger.debug("Generated summary for query: %s", nl_query[:50])
            return summary

        except Exception as exc:
            logger.warning("Result summarization failed (non-critical): %s", exc)
            return ""

    def _build_summary_prompt(
        self,
        nl_query: str,
        columns: list[dict[str, str]],
        rows: list[dict[str, Any]],
        row_count: int,
        truncated: bool,
    ) -> str:
        """Build the summarization prompt from query and results.

        Args:
            nl_query: User's original question.
            columns: Column definitions.
            rows: Result rows to summarize.
            row_count: Total result count.
            truncated: Whether results were truncated.

        Returns:
            Formatted prompt string for the LLM.
        """
        col_names = [c["name"] for c in columns]
        header = " | ".join(col_names)

        # Format rows as a simple table
        table_lines = [header, "-" * len(header)]
        for row in rows[:20]:  # Show at most 20 rows in prompt
            values = [str(row.get(c, "")) for c in col_names]
            table_lines.append(" | ".join(values))

        if len(rows) > 20:
            table_lines.append(f"... ({row_count - 20} more rows)")

        table_str = "\n".join(table_lines)

        parts = [
            f"User's question: \"{nl_query}\"",
            f"\nQuery returned {row_count} row(s).",
        ]

        if truncated:
            parts.append("(Results were truncated due to size limits.)")

        parts.append(f"\nResults:\n{table_str}")
        parts.append("\nProvide a brief, insightful summary of these results.")

        return "\n".join(parts)


class VisualizationSuggester:
    """Suggests appropriate chart types for query results.

    Based on column types and data patterns, recommends:
    - Bar chart for comparisons
    - Line chart for trends
    - Pie chart for composition
    - Table for detailed data

    Assignment Reference: Section 6.4 — "Optionally suggest appropriate visualisations"
    """

    @staticmethod
    def suggest(
        columns: list[dict[str, str]],
        rows: list[dict[str, Any]],
        tier: str,
    ) -> dict[str, str]:
        """Suggest a visualization type based on result structure.

        Args:
            columns: Column metadata.
            rows: Result rows.
            tier: Query complexity tier.

        Returns:
            Dict with 'type' (bar|line|pie|table) and 'reason' explanation.
        """
        if not rows or not columns:
            return {"type": "table", "reason": "No data to visualize"}

        col_count = len(columns)
        row_count = len(rows)

        # Detect time-series data (line chart)
        time_cols = [
            c for c in columns
            if any(t in c["name"].lower() for t in ["date", "month", "year", "quarter", "week", "time"])
        ]
        numeric_cols = [
            c for c in columns
            if any(t in c.get("data_type", "").lower() for t in ["int", "float", "decimal", "numeric"])
        ]

        if time_cols and numeric_cols:
            return {
                "type": "line",
                "reason": "Time-based data detected — line chart shows trends over time",
            }

        # Detect composition (pie chart) — single numeric + single category, few rows
        category_cols = [c for c in columns if c not in numeric_cols and c not in time_cols]
        if len(category_cols) == 1 and len(numeric_cols) == 1 and row_count <= 10:
            return {
                "type": "pie",
                "reason": "Category with single metric — pie chart shows composition",
            }

        # Detect comparison (bar chart) — category + numeric
        if category_cols and numeric_cols and row_count <= 30:
            return {
                "type": "bar",
                "reason": "Categories with metrics — bar chart enables comparison",
            }

        # Default: table
        return {"type": "table", "reason": "Complex or large dataset — table view recommended"}
