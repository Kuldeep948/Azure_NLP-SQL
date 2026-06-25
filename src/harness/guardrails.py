"""Guardrail Engine for enforcing row caps, injection detection, RBAC, and PII redaction.

Provides safety enforcement on Generated SQL before execution and on result sets
before returning to callers.

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 6.10
"""

from __future__ import annotations

import re

import sqlglot
from pydantic import BaseModel, Field


class GuardrailConfig(BaseModel):
    """Configuration for the Guardrail Engine.

    Attributes:
        row_cap: Maximum rows returned per query (1-10000, default 1000).
        timeout_seconds: Query execution timeout in seconds (1-300, default 30).
        table_permissions: Mapping of role name to list of permitted table names.
    """

    row_cap: int = Field(default=1000, ge=1, le=10000)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    table_permissions: dict[str, list[str]] = Field(default_factory=dict)


# PII detection patterns
_EMAIL_PATTERN = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.IGNORECASE
)
_PHONE_PATTERN = re.compile(
    r"(?<!\d)"  # no digit before
    r"(?:\+?\d{1,3}[\s\-.]?)?"  # optional country code
    r"(?:\(?\d{2,4}\)?[\s\-.]?)"  # area code
    r"\d{3,4}[\s\-.]?"  # first group
    r"\d{3,4}"  # second group
    r"(?!\d)",  # no digit after
)
_NATIONAL_ID_PATTERN = re.compile(
    r"\b\d{3}[\-\s]?\d{2}[\-\s]?\d{4}\b"  # US SSN pattern (XXX-XX-XXXX)
)

# SQL injection detection patterns
_UNION_PATTERN = re.compile(r"\bUNION\b\s+(ALL\s+)?SELECT\b", re.IGNORECASE)
_SINGLE_LINE_COMMENT = re.compile(r"--")
_MULTI_LINE_COMMENT = re.compile(r"/\*")
_STACKED_QUERY_PATTERN = re.compile(r";")
_TAUTOLOGY_PATTERN = re.compile(
    r"\b(\d+)\s*=\s*\1\b"  # numeric tautology like 1=1
    r"|"
    r"'([^']+)'\s*=\s*'\2'"  # string tautology like 'a'='a'
    r"|"
    r"\bOR\s+1\s*=\s*1\b",  # OR 1=1
    re.IGNORECASE,
)

REDACTED_PLACEHOLDER = "[REDACTED]"


class GuardrailEngine:
    """Enforces safety guardrails on SQL queries and result sets.

    Provides:
    - Row cap injection (TOP/LIMIT) via sqlglot AST transformation
    - SQL injection pattern detection
    - RBAC table-level access verification
    - PII redaction on query results
    """

    def __init__(self, config: GuardrailConfig) -> None:
        self._config = config

    @property
    def config(self) -> GuardrailConfig:
        """Return the current guardrail configuration."""
        return self._config

    def apply_row_cap(self, sql: str, dialect: str = "tsql") -> str:
        """Inject TOP (T-SQL) or LIMIT (PostgreSQL) clause into the SQL query.

        Uses sqlglot AST transformation to safely inject the row cap without
        breaking query semantics.

        Args:
            sql: The SQL query string to modify.
            dialect: SQL dialect - "tsql" for T-SQL or "postgres" for PostgreSQL.

        Returns:
            Modified SQL string with row cap applied.
        """
        row_cap = self._config.row_cap

        # Map dialect names to sqlglot dialect identifiers
        dialect_map = {
            "tsql": "tsql",
            "postgres": "postgres",
            "postgresql": "postgres",
        }
        sqlglot_dialect = dialect_map.get(dialect.lower(), "tsql")

        try:
            parsed = sqlglot.parse(sql, dialect=sqlglot_dialect)
        except sqlglot.errors.ParseError:
            # If parsing fails, fall back to string-based injection
            return self._fallback_row_cap(sql, row_cap, sqlglot_dialect)

        if not parsed:
            return sql

        # Transform the first statement (the main SELECT)
        statement = parsed[0]

        if statement is None:
            return sql

        # Only apply row cap to SELECT statements
        if not isinstance(statement, sqlglot.exp.Select):
            return sql

        if sqlglot_dialect == "tsql":
            # For T-SQL, inject TOP clause
            # Check if TOP already exists
            existing_limit = statement.args.get("limit")
            if existing_limit is not None:
                return sql
            # Use sqlglot's limit method which handles TOP for tsql dialect
            statement = statement.limit(row_cap, dialect=sqlglot_dialect)
        else:
            # For PostgreSQL, inject LIMIT clause
            existing_limit = statement.args.get("limit")
            if existing_limit is not None:
                return sql
            statement = statement.limit(row_cap, dialect=sqlglot_dialect)

        return statement.sql(dialect=sqlglot_dialect)

    def _fallback_row_cap(self, sql: str, row_cap: int, dialect: str) -> str:
        """Fallback string-based row cap injection when AST parsing fails."""
        sql_stripped = sql.strip().rstrip(";")
        if dialect == "tsql":
            # Inject TOP after SELECT keyword
            select_match = re.match(r"(SELECT\s+)(DISTINCT\s+)?", sql_stripped, re.IGNORECASE)
            if select_match:
                prefix = select_match.group(0)
                # Check if TOP already present
                after_select = sql_stripped[select_match.end():]
                if re.match(r"TOP\s+", after_select, re.IGNORECASE):
                    return sql
                return f"{prefix}TOP {row_cap} {after_select}"
        else:
            # Append LIMIT for PostgreSQL
            if re.search(r"\bLIMIT\b", sql_stripped, re.IGNORECASE):
                return sql
            return f"{sql_stripped} LIMIT {row_cap}"
        return sql

    def detect_injection_patterns(self, sql: str) -> list[str]:
        """Scan SQL for injection pattern categories.

        Checks for:
        - UNION-based injection
        - Comment sequences (-- and /* */)
        - Stacked queries (;)
        - Tautological conditions (e.g., 1=1)
        - Unbalanced quotation marks

        Args:
            sql: The SQL query string to scan.

        Returns:
            List of detected injection pattern category names. Empty if clean.
        """
        detected: list[str] = []

        if _UNION_PATTERN.search(sql):
            detected.append("UNION-based injection")

        if _SINGLE_LINE_COMMENT.search(sql):
            detected.append("comment sequence (--)")

        if _MULTI_LINE_COMMENT.search(sql):
            detected.append("comment sequence (/* */)")

        if _STACKED_QUERY_PATTERN.search(sql):
            detected.append("stacked query (;)")

        if _TAUTOLOGY_PATTERN.search(sql):
            detected.append("tautological condition")

        # Check for unbalanced quotation marks
        if self._has_unbalanced_quotes(sql):
            detected.append("unbalanced quotation marks")

        return detected

    def _has_unbalanced_quotes(self, sql: str) -> bool:
        """Check if single or double quotes are unbalanced in the SQL string."""
        single_count = 0
        double_count = 0
        i = 0
        while i < len(sql):
            char = sql[i]
            if char == "'" :
                # Check for escaped quote ('')
                if i + 1 < len(sql) and sql[i + 1] == "'":
                    i += 2  # Skip escaped quote
                    continue
                single_count += 1
            elif char == '"':
                # Check for escaped double quote ("")
                if i + 1 < len(sql) and sql[i + 1] == '"':
                    i += 2
                    continue
                double_count += 1
            i += 1
        return (single_count % 2 != 0) or (double_count % 2 != 0)

    def check_rbac(self, tables: list[str], user_roles: list[str]) -> list[str]:
        """Verify that the user's roles grant access to all referenced tables.

        Args:
            tables: List of table names referenced in the query.
            user_roles: List of role names assigned to the authenticated user.

        Returns:
            List of table names the user CANNOT access.
            Empty list means all tables are permitted.
        """
        if not self._config.table_permissions:
            # No permissions configured means all tables are accessible
            return []

        # Collect all tables the user can access based on their roles
        permitted_tables: set[str] = set()
        for role in user_roles:
            role_tables = self._config.table_permissions.get(role, [])
            permitted_tables.update(t.lower() for t in role_tables)

        # Find tables the user cannot access
        denied_tables: list[str] = []
        for table in tables:
            if table.lower() not in permitted_tables:
                denied_tables.append(table)

        return denied_tables

    def redact_pii(self, results: list[dict]) -> list[dict]:
        """Scan result set values for PII patterns and replace with redaction placeholder.

        Detects:
        - Email addresses
        - Phone numbers
        - National identification numbers (e.g., US SSN)

        Args:
            results: List of row dictionaries from query execution.

        Returns:
            New list of row dictionaries with PII values replaced by "[REDACTED]".
        """
        redacted_results: list[dict] = []
        for row in results:
            redacted_row: dict = {}
            for key, value in row.items():
                if isinstance(value, str):
                    redacted_row[key] = self._redact_string(value)
                else:
                    redacted_row[key] = value
            redacted_results.append(redacted_row)
        return redacted_results

    def _redact_string(self, value: str) -> str:
        """Apply PII redaction patterns to a single string value."""
        result = _EMAIL_PATTERN.sub(REDACTED_PLACEHOLDER, value)
        result = _NATIONAL_ID_PATTERN.sub(REDACTED_PLACEHOLDER, result)
        result = _PHONE_PATTERN.sub(REDACTED_PLACEHOLDER, result)
        return result
