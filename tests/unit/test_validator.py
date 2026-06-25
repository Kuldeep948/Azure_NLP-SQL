"""Unit tests for the Output Validator.

Tests cover:
- SQL parsing with T-SQL dialect
- Pretty-printing / normalization
- Safety checks (DDL/DML detection)
- Schema conformance checks
- Full validation pipeline orchestration
"""

import pytest
import sqlglot

from src.harness.validator import OutputValidator, ValidationResult
from src.schema.metadata import (
    ColumnSchema,
    ForeignKey,
    SchemaMetadata,
    TableSchema,
)


@pytest.fixture
def sample_schema() -> SchemaMetadata:
    """Provide a minimal schema for testing."""
    return SchemaMetadata(
        tables={
            "customers": TableSchema(
                name="customers",
                columns=[
                    ColumnSchema(name="customer_id", data_type="INT", nullable=False),
                    ColumnSchema(name="first_name", data_type="NVARCHAR(100)", nullable=False),
                    ColumnSchema(name="last_name", data_type="NVARCHAR(100)", nullable=False),
                    ColumnSchema(name="email", data_type="NVARCHAR(255)", nullable=False),
                    ColumnSchema(name="phone", data_type="NVARCHAR(20)", nullable=True),
                ],
                primary_keys=["customer_id"],
                foreign_keys=[],
            ),
            "orders": TableSchema(
                name="orders",
                columns=[
                    ColumnSchema(name="order_id", data_type="INT", nullable=False),
                    ColumnSchema(name="customer_id", data_type="INT", nullable=False),
                    ColumnSchema(name="order_date", data_type="DATETIME2", nullable=True),
                    ColumnSchema(name="status", data_type="NVARCHAR(20)", nullable=True),
                    ColumnSchema(name="total_amount", data_type="DECIMAL(12,2)", nullable=True),
                ],
                primary_keys=["order_id"],
                foreign_keys=[
                    ForeignKey(
                        column="customer_id",
                        references_table="customers",
                        references_column="customer_id",
                    )
                ],
            ),
            "products": TableSchema(
                name="products",
                columns=[
                    ColumnSchema(name="product_id", data_type="INT", nullable=False),
                    ColumnSchema(name="name", data_type="NVARCHAR(200)", nullable=False),
                    ColumnSchema(name="category", data_type="NVARCHAR(100)", nullable=True),
                    ColumnSchema(name="price", data_type="DECIMAL(10,2)", nullable=False),
                ],
                primary_keys=["product_id"],
                foreign_keys=[],
            ),
        }
    )


@pytest.fixture
def validator(sample_schema: SchemaMetadata) -> OutputValidator:
    """Create an OutputValidator with the sample schema."""
    return OutputValidator(schema=sample_schema, dialect="tsql")


class TestParseSql:
    """Tests for the parse_sql method."""

    def test_parse_simple_select(self, validator: OutputValidator):
        """Parse a basic SELECT statement."""
        ast = validator.parse_sql("SELECT customer_id, first_name FROM customers")
        assert ast is not None
        assert isinstance(ast, sqlglot.exp.Expression)

    def test_parse_select_with_where(self, validator: OutputValidator):
        """Parse SELECT with WHERE clause."""
        sql = "SELECT * FROM orders WHERE status = 'completed'"
        ast = validator.parse_sql(sql)
        assert ast is not None

    def test_parse_join_query(self, validator: OutputValidator):
        """Parse a JOIN query."""
        sql = """
        SELECT c.first_name, o.total_amount
        FROM customers c
        JOIN orders o ON c.customer_id = o.customer_id
        """
        ast = validator.parse_sql(sql)
        assert ast is not None

    def test_parse_aggregate_query(self, validator: OutputValidator):
        """Parse an aggregate query with GROUP BY."""
        sql = "SELECT status, COUNT(*) as cnt FROM orders GROUP BY status"
        ast = validator.parse_sql(sql)
        assert ast is not None

    def test_parse_invalid_sql_raises_error(self, validator: OutputValidator):
        """Invalid SQL raises ParseError."""
        with pytest.raises(sqlglot.errors.ParseError):
            validator.parse_sql("SELECT FROM WHERE")

    def test_parse_empty_string_raises_error(self, validator: OutputValidator):
        """Empty string raises ParseError."""
        with pytest.raises(sqlglot.errors.ParseError):
            validator.parse_sql("")


class TestPrettyPrint:
    """Tests for the pretty_print method."""

    def test_pretty_print_normalizes_formatting(self, validator: OutputValidator):
        """Pretty print produces consistent formatting."""
        ast = validator.parse_sql("select customer_id,first_name from customers where customer_id=1")
        result = validator.pretty_print(ast)
        # Should be a non-empty string
        assert isinstance(result, str)
        assert len(result) > 0
        # Should contain SELECT and FROM keywords
        assert "SELECT" in result.upper()
        assert "FROM" in result.upper()

    def test_round_trip_produces_equivalent_ast(self, validator: OutputValidator):
        """parse → pretty_print → parse produces equivalent AST."""
        original_sql = "SELECT customer_id, first_name FROM customers WHERE customer_id > 10"
        ast1 = validator.parse_sql(original_sql)
        pretty = validator.pretty_print(ast1)
        ast2 = validator.parse_sql(pretty)
        # Both ASTs should produce the same normalized SQL
        assert ast1.sql(dialect="tsql") == ast2.sql(dialect="tsql")

    def test_round_trip_with_join(self, validator: OutputValidator):
        """Round-trip works for JOIN queries."""
        sql = "SELECT c.first_name, o.total_amount FROM customers c JOIN orders o ON c.customer_id = o.customer_id"
        ast1 = validator.parse_sql(sql)
        pretty = validator.pretty_print(ast1)
        ast2 = validator.parse_sql(pretty)
        assert ast1.sql(dialect="tsql") == ast2.sql(dialect="tsql")


class TestCheckSafety:
    """Tests for the check_safety method."""

    def test_safe_select_query(self, validator: OutputValidator):
        """SELECT queries produce no safety errors."""
        ast = validator.parse_sql("SELECT * FROM customers")
        errors = validator.check_safety(ast)
        assert errors == []

    def test_detect_create_table(self, validator: OutputValidator):
        """CREATE TABLE is detected as prohibited."""
        ast = validator.parse_sql("CREATE TABLE test (id INT)")
        errors = validator.check_safety(ast)
        assert len(errors) >= 1
        assert any("CREATE" in e for e in errors)

    def test_detect_drop_table(self, validator: OutputValidator):
        """DROP TABLE is detected as prohibited."""
        ast = validator.parse_sql("DROP TABLE customers")
        errors = validator.check_safety(ast)
        assert len(errors) >= 1
        assert any("DROP" in e for e in errors)

    def test_detect_insert(self, validator: OutputValidator):
        """INSERT is detected as prohibited."""
        ast = validator.parse_sql("INSERT INTO customers (first_name) VALUES ('Test')")
        errors = validator.check_safety(ast)
        assert len(errors) >= 1
        assert any("INSERT" in e for e in errors)

    def test_detect_update(self, validator: OutputValidator):
        """UPDATE is detected as prohibited."""
        ast = validator.parse_sql("UPDATE customers SET first_name = 'X' WHERE customer_id = 1")
        errors = validator.check_safety(ast)
        assert len(errors) >= 1
        assert any("UPDATE" in e for e in errors)

    def test_detect_delete(self, validator: OutputValidator):
        """DELETE is detected as prohibited."""
        ast = validator.parse_sql("DELETE FROM customers WHERE customer_id = 1")
        errors = validator.check_safety(ast)
        assert len(errors) >= 1
        assert any("DELETE" in e for e in errors)

    def test_detect_merge(self, validator: OutputValidator):
        """MERGE is detected as prohibited."""
        sql = """
        MERGE INTO customers AS target
        USING (SELECT 1 AS customer_id, 'Test' AS first_name) AS source
        ON target.customer_id = source.customer_id
        WHEN MATCHED THEN UPDATE SET first_name = source.first_name
        """
        ast = validator.parse_sql(sql)
        errors = validator.check_safety(ast)
        assert len(errors) >= 1
        assert any("MERGE" in e for e in errors)

    def test_select_with_subquery_is_safe(self, validator: OutputValidator):
        """SELECT with subquery is safe."""
        sql = "SELECT * FROM customers WHERE customer_id IN (SELECT customer_id FROM orders)"
        ast = validator.parse_sql(sql)
        errors = validator.check_safety(ast)
        assert errors == []


class TestCheckSchemaConformance:
    """Tests for the check_schema_conformance method."""

    def test_valid_table_and_columns(self, validator: OutputValidator):
        """Query with valid table and column references passes."""
        ast = validator.parse_sql("SELECT customer_id, first_name FROM customers")
        errors = validator.check_schema_conformance(ast)
        assert errors == []

    def test_valid_join_references(self, validator: OutputValidator):
        """Query with valid JOIN references passes."""
        sql = """
        SELECT c.first_name, o.total_amount
        FROM customers c
        JOIN orders o ON c.customer_id = o.customer_id
        """
        ast = validator.parse_sql(sql)
        errors = validator.check_schema_conformance(ast)
        assert errors == []

    def test_unrecognized_table(self, validator: OutputValidator):
        """Query referencing a non-existent table fails."""
        ast = validator.parse_sql("SELECT * FROM nonexistent_table")
        errors = validator.check_schema_conformance(ast)
        assert len(errors) >= 1
        assert any("nonexistent_table" in e for e in errors)

    def test_unrecognized_column_with_table_qualifier(self, validator: OutputValidator):
        """Query referencing a non-existent column on a valid table fails."""
        ast = validator.parse_sql("SELECT customers.nonexistent_col FROM customers")
        errors = validator.check_schema_conformance(ast)
        assert len(errors) >= 1
        assert any("nonexistent_col" in e for e in errors)

    def test_unrecognized_column_without_qualifier(self, validator: OutputValidator):
        """Query referencing a non-existent column without qualifier fails."""
        ast = validator.parse_sql("SELECT nonexistent_col FROM customers")
        errors = validator.check_schema_conformance(ast)
        assert len(errors) >= 1
        assert any("nonexistent_col" in e for e in errors)

    def test_case_insensitive_matching(self, validator: OutputValidator):
        """Schema matching is case-insensitive."""
        ast = validator.parse_sql("SELECT CUSTOMER_ID, FIRST_NAME FROM CUSTOMERS")
        errors = validator.check_schema_conformance(ast)
        assert errors == []

    def test_multiple_unrecognized_identifiers(self, validator: OutputValidator):
        """Multiple unrecognized references are all reported."""
        ast = validator.parse_sql("SELECT bad_col FROM fake_table")
        errors = validator.check_schema_conformance(ast)
        # Should report both the bad table and the bad column
        assert any("fake_table" in e for e in errors)

    def test_star_select_passes(self, validator: OutputValidator):
        """SELECT * from a valid table passes."""
        ast = validator.parse_sql("SELECT * FROM customers")
        errors = validator.check_schema_conformance(ast)
        assert errors == []

    def test_alias_resolved_correctly(self, validator: OutputValidator):
        """Aliases are resolved to actual table names for column checks."""
        sql = "SELECT c.customer_id, c.first_name FROM customers c"
        ast = validator.parse_sql(sql)
        errors = validator.check_schema_conformance(ast)
        assert errors == []


class TestValidate:
    """Tests for the full validate() pipeline."""

    def test_valid_query_returns_is_valid_true(self, validator: OutputValidator):
        """A valid SELECT query passes all checks."""
        result = validator.validate("SELECT customer_id, first_name FROM customers")
        assert result.is_valid is True
        assert result.errors == []
        assert result.normalized_sql is not None
        assert result.ast is not None

    def test_syntax_error_returns_is_valid_false(self, validator: OutputValidator):
        """An invalid SQL string fails at syntax check."""
        result = validator.validate("SELCT FROM WHERE")
        assert result.is_valid is False
        assert len(result.errors) >= 1
        assert any("Syntax error" in e or "yntax" in e.lower() for e in result.errors)
        assert result.normalized_sql is None

    def test_unsafe_query_returns_is_valid_false(self, validator: OutputValidator):
        """DDL/DML queries fail safety check."""
        result = validator.validate("DROP TABLE customers")
        assert result.is_valid is False
        assert any("DROP" in e for e in result.errors)

    def test_schema_violation_returns_is_valid_false(self, validator: OutputValidator):
        """Query referencing non-existent table fails schema check."""
        result = validator.validate("SELECT * FROM nonexistent_table")
        assert result.is_valid is False
        assert any("nonexistent_table" in e for e in result.errors)

    def test_multiple_errors_accumulated(self, validator: OutputValidator):
        """Safety and schema errors from the same query are both reported."""
        # INSERT into a non-existent table triggers both safety and schema errors
        result = validator.validate("INSERT INTO fake_table (col) VALUES (1)")
        assert result.is_valid is False
        assert any("INSERT" in e for e in result.errors)
        assert any("fake_table" in e for e in result.errors)

    def test_valid_join_query(self, validator: OutputValidator):
        """A valid JOIN query passes all checks."""
        sql = """
        SELECT c.first_name, c.last_name, o.total_amount
        FROM customers c
        JOIN orders o ON c.customer_id = o.customer_id
        WHERE o.status = 'completed'
        """
        result = validator.validate(sql)
        assert result.is_valid is True
        assert result.errors == []
        assert result.normalized_sql is not None

    def test_valid_aggregate_query(self, validator: OutputValidator):
        """A valid aggregate query passes all checks."""
        sql = "SELECT status, COUNT(*) AS cnt FROM orders GROUP BY status"
        result = validator.validate(sql)
        assert result.is_valid is True
        assert result.errors == []
