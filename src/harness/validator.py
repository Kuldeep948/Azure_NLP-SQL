"""Output Validator for SQL syntax checking, safety scanning, and schema conformance.

Uses sqlglot for T-SQL/PostgreSQL dialect parsing, AST-based safety checks,
and schema conformance verification against SchemaMetadata.

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 18.1, 18.2, 18.3, 18.4
"""

from __future__ import annotations

import logging
from typing import Any

import sqlglot
from sqlglot import exp
from pydantic import BaseModel, ConfigDict

from src.schema.metadata import SchemaMetadata

logger = logging.getLogger(__name__)

# DDL/DML statement types that are prohibited
_PROHIBITED_STATEMENT_TYPES: dict[type[exp.Expression], str] = {
    exp.Create: "CREATE",
    exp.Alter: "ALTER",
    exp.Drop: "DROP",
    exp.TruncateTable: "TRUNCATE",
    exp.Insert: "INSERT",
    exp.Update: "UPDATE",
    exp.Delete: "DELETE",
    exp.Merge: "MERGE",
}

# Additional keywords to detect via command expressions (fallback)
_PROHIBITED_COMMANDS: set[str] = {"TRUNCATE", "ALTER"}


class ValidationResult(BaseModel):
    """Result of SQL validation containing status, errors, and normalized output."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    is_valid: bool
    errors: list[str]
    normalized_sql: str | None = None
    ast: Any | None = None  # sqlglot.Expression (Any for Pydantic compatibility)


class OutputValidator:
    """Validates Generated SQL for syntax, safety, and schema conformance.

    Uses sqlglot to parse SQL into an AST, then performs:
    1. Syntax validation (parse succeeds)
    2. Safety check (no DDL/DML statements)
    3. Schema conformance (all tables/columns exist in metadata)

    Args:
        schema: The SchemaMetadata containing valid table and column definitions.
        dialect: SQL dialect for parsing. Defaults to "tsql".
    """

    def __init__(self, schema: SchemaMetadata, dialect: str = "tsql") -> None:
        self._schema = schema
        self._dialect = dialect
        # Build lookup sets for schema conformance (case-insensitive)
        self._table_names: set[str] = {
            name.lower() for name in schema.tables.keys()
        }
        self._table_columns: dict[str, set[str]] = {
            table_name.lower(): {col.name.lower() for col in table.columns}
            for table_name, table in schema.tables.items()
        }

    def validate(self, sql: str) -> ValidationResult:
        """Full validation pipeline: syntax → safety → complexity → schema conformance.

        Returns a ValidationResult with is_valid=True only if all checks pass.
        Errors from all failing checks are accumulated in the errors list.

        Args:
            sql: The Generated SQL string to validate.

        Returns:
            ValidationResult with validation status and any errors found.
        """
        errors: list[str] = []

        # Step 1: Syntax validation (parse)
        try:
            ast = self.parse_sql(sql)
        except sqlglot.errors.ParseError as e:
            return ValidationResult(
                is_valid=False,
                errors=[f"Syntax error: {e}"],
                normalized_sql=None,
                ast=None,
            )

        # Step 2: Safety check (DDL/DML detection)
        safety_errors = self.check_safety(ast)
        errors.extend(safety_errors)

        # Step 3: Complexity limits (join count, subquery depth)
        complexity_errors = self.check_complexity(ast)
        errors.extend(complexity_errors)

        # Step 4: Schema conformance
        schema_errors = self.check_schema_conformance(ast)
        errors.extend(schema_errors)

        # Generate normalized SQL if no errors
        normalized_sql = self.pretty_print(ast) if not errors else None

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            normalized_sql=normalized_sql,
            ast=ast,
        )

    def parse_sql(self, sql: str) -> sqlglot.Expression:
        """Parse a SQL string into an AST using the configured dialect.

        Args:
            sql: The SQL string to parse.

        Returns:
            The parsed sqlglot Expression (AST).

        Raises:
            sqlglot.errors.ParseError: If the SQL cannot be parsed.
        """
        expressions = sqlglot.parse(sql, dialect=self._dialect, error_level=sqlglot.ErrorLevel.RAISE)
        if not expressions or expressions[0] is None:
            raise sqlglot.errors.ParseError("Empty or invalid SQL statement")
        return expressions[0]

    def pretty_print(self, ast: sqlglot.Expression) -> str:
        """Format an AST back to a normalized SQL string.

        Produces consistent formatting for storage in the Semantic Cache
        and display in the Frontend.

        Args:
            ast: The sqlglot Expression to format.

        Returns:
            A normalized, pretty-printed SQL string.
        """
        return ast.sql(dialect=self._dialect, pretty=True)

    def check_safety(self, ast: sqlglot.Expression) -> list[str]:
        """Detect prohibited DDL/DML statements in the AST.

        Scans for: CREATE, ALTER, DROP, TRUNCATE, INSERT, UPDATE, DELETE, MERGE.

        Args:
            ast: The parsed sqlglot Expression to check.

        Returns:
            List of error messages for each prohibited statement type detected.
            Empty list means the query is safe.
        """
        errors: list[str] = []
        detected: set[str] = set()

        # Check the top-level expression type
        for stmt_type, stmt_name in _PROHIBITED_STATEMENT_TYPES.items():
            if isinstance(ast, stmt_type):
                detected.add(stmt_name)

        # Also walk the full AST tree for nested/compound statements
        for node in ast.walk():
            for stmt_type, stmt_name in _PROHIBITED_STATEMENT_TYPES.items():
                if isinstance(node, stmt_type):
                    detected.add(stmt_name)

            # Handle TRUNCATE and ALTER which may appear as Command expressions
            if isinstance(node, exp.Command):
                cmd_name = node.this
                if isinstance(cmd_name, str) and cmd_name.upper() in _PROHIBITED_COMMANDS:
                    detected.add(cmd_name.upper())

        for stmt_name in sorted(detected):
            errors.append(
                f"Prohibited statement detected: {stmt_name} statements are not allowed"
            )

        return errors

    def check_complexity(self, ast: sqlglot.Expression) -> list[str]:
        """Check query complexity limits: max JOINs and max subquery depth.

        Rejects queries with:
        - More than 5 JOIN operations
        - Subquery nesting depth greater than 3

        Args:
            ast: The parsed sqlglot Expression to check.

        Returns:
            List of error messages for complexity violations. Empty if within limits.
        """
        errors: list[str] = []

        # Count JOIN nodes
        join_count = len(list(ast.find_all(exp.Join)))
        if join_count > 5:
            errors.append(
                f"Query too complex: {join_count} JOINs detected (maximum allowed: 5)"
            )

        # Count subquery depth (nested SELECT statements)
        max_depth = self._measure_subquery_depth(ast)
        if max_depth > 3:
            errors.append(
                f"Query too complex: subquery nesting depth {max_depth} (maximum allowed: 3)"
            )

        return errors

    def _measure_subquery_depth(self, ast: sqlglot.Expression) -> int:
        """Measure the maximum subquery nesting depth in the AST.

        The top-level SELECT is depth 0. Each nested SELECT (subquery) adds 1.
        """
        max_depth = 0

        def _walk_depth(node: sqlglot.Expression, current_depth: int) -> None:
            nonlocal max_depth
            for child in node.iter_expressions():
                child_depth = current_depth
                if isinstance(child, exp.Select) or isinstance(child, exp.Subquery):
                    # Only count Select nodes that are actual subqueries (not the root)
                    if isinstance(child, exp.Subquery):
                        child_depth = current_depth + 1
                    elif isinstance(child, exp.Select) and current_depth > 0:
                        child_depth = current_depth + 1
                    elif isinstance(child, exp.Select) and child is not ast:
                        child_depth = current_depth + 1
                    max_depth = max(max_depth, child_depth)
                _walk_depth(child, child_depth)

        _walk_depth(ast, 0)
        return max_depth

    def check_schema_conformance(self, ast: sqlglot.Expression) -> list[str]:
        """Verify all table and column references exist in the schema metadata.

        Performs case-insensitive matching against the SchemaMetadata.

        Args:
            ast: The parsed sqlglot Expression to check.

        Returns:
            List of error messages for unrecognized table/column references.
            Empty list means all references are valid.
        """
        errors: list[str] = []
        unrecognized_tables: set[str] = set()
        unrecognized_columns: set[str] = set()

        # Extract table references
        referenced_tables = self._extract_tables(ast)
        # Build a mapping of alias -> real table name for column resolution
        alias_map = self._build_alias_map(ast)

        # Check table references
        for table_name in referenced_tables:
            if table_name.lower() not in self._table_names:
                unrecognized_tables.add(table_name)

        # Extract and check column references
        for column_node in ast.find_all(exp.Column):
            column_name = column_node.name
            table_ref = column_node.table

            if table_ref:
                # Resolve alias to actual table name
                resolved_table = alias_map.get(table_ref.lower(), table_ref.lower())
                if resolved_table in self._table_names:
                    # Check column exists in the specific table
                    valid_columns = self._table_columns.get(resolved_table, set())
                    if column_name.lower() not in valid_columns:
                        unrecognized_columns.add(f"{table_ref}.{column_name}")
                # If table itself is unrecognized, that error is already captured
            else:
                # No table qualifier - check if column exists in any referenced table
                if not self._column_exists_in_any_table(column_name, referenced_tables):
                    unrecognized_columns.add(column_name)

        # Build error messages
        for table in sorted(unrecognized_tables):
            errors.append(f"Unrecognized table: '{table}' not found in schema metadata")

        for column in sorted(unrecognized_columns):
            errors.append(
                f"Unrecognized column: '{column}' not found in schema metadata"
            )

        return errors

    def _extract_tables(self, ast: sqlglot.Expression) -> set[str]:
        """Extract all table names referenced in the AST (excluding aliases)."""
        tables: set[str] = set()
        for table_node in ast.find_all(exp.Table):
            table_name = table_node.name
            if table_name:
                tables.add(table_name)
        return tables

    def _build_alias_map(self, ast: sqlglot.Expression) -> dict[str, str]:
        """Build a mapping of table aliases to actual table names (lowercase)."""
        alias_map: dict[str, str] = {}
        for table_node in ast.find_all(exp.Table):
            table_name = table_node.name
            alias = table_node.alias
            if table_name:
                # Map the table name itself (for unqualified references)
                alias_map[table_name.lower()] = table_name.lower()
                # Map the alias if present
                if alias:
                    alias_map[alias.lower()] = table_name.lower()
        return alias_map

    def _column_exists_in_any_table(
        self, column_name: str, referenced_tables: set[str]
    ) -> bool:
        """Check if a column exists in any of the referenced tables."""
        col_lower = column_name.lower()
        for table_name in referenced_tables:
            table_key = table_name.lower()
            if table_key in self._table_columns:
                if col_lower in self._table_columns[table_key]:
                    return True
        return False
