"""Unit tests for the Guardrail Engine.

Tests cover:
- Row cap injection (TOP for T-SQL, LIMIT for PostgreSQL)
- SQL injection pattern detection
- RBAC table access verification
- PII redaction
"""

import importlib.util
from pathlib import Path

import pytest

# Import guardrails module directly to avoid triggering harness __init__.py
# which imports other modules with heavy external dependencies (langchain, etc.)
import importlib.util

_guardrails_path = Path(__file__).resolve().parents[2] / "src" / "harness" / "guardrails.py"
_spec = importlib.util.spec_from_file_location("src.harness.guardrails", _guardrails_path)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

GuardrailConfig = _module.GuardrailConfig
GuardrailEngine = _module.GuardrailEngine
REDACTED_PLACEHOLDER = _module.REDACTED_PLACEHOLDER


# --- Fixtures ---


@pytest.fixture
def default_config() -> GuardrailConfig:
    """Config with default row_cap=1000 and basic table permissions."""
    return GuardrailConfig(
        row_cap=1000,
        timeout_seconds=30,
        table_permissions={
            "analyst": ["customers", "orders", "products"],
            "admin": ["customers", "orders", "products", "campaigns", "support_tickets"],
            "marketing": ["campaigns", "campaign_conversions"],
        },
    )


@pytest.fixture
def engine(default_config: GuardrailConfig) -> GuardrailEngine:
    return GuardrailEngine(config=default_config)


# --- Row Cap Tests ---


class TestApplyRowCap:
    """Tests for apply_row_cap method."""

    def test_tsql_simple_select(self, engine: GuardrailEngine) -> None:
        """T-SQL: adds TOP to a simple SELECT."""
        sql = "SELECT * FROM customers"
        result = engine.apply_row_cap(sql, dialect="tsql")
        # Should contain TOP 1000
        assert "TOP" in result.upper() or "LIMIT" in result.upper()
        assert "1000" in result

    def test_tsql_select_with_where(self, engine: GuardrailEngine) -> None:
        """T-SQL: adds TOP to SELECT with WHERE clause."""
        sql = "SELECT name, email FROM customers WHERE status = 'active'"
        result = engine.apply_row_cap(sql, dialect="tsql")
        assert "1000" in result

    def test_tsql_preserves_existing_top(self, engine: GuardrailEngine) -> None:
        """T-SQL: does not double-add TOP if already present."""
        sql = "SELECT TOP 50 * FROM customers"
        result = engine.apply_row_cap(sql, dialect="tsql")
        # Should keep original limit, not add another
        assert "50" in result

    def test_postgres_simple_select(self, engine: GuardrailEngine) -> None:
        """PostgreSQL: adds LIMIT to a simple SELECT."""
        sql = "SELECT * FROM customers"
        result = engine.apply_row_cap(sql, dialect="postgres")
        assert "LIMIT" in result.upper()
        assert "1000" in result

    def test_postgres_preserves_existing_limit(self, engine: GuardrailEngine) -> None:
        """PostgreSQL: does not double-add LIMIT if already present."""
        sql = "SELECT * FROM customers LIMIT 50"
        result = engine.apply_row_cap(sql, dialect="postgres")
        assert "50" in result

    def test_custom_row_cap(self) -> None:
        """Uses the configured row_cap value, not hardcoded."""
        config = GuardrailConfig(row_cap=500, table_permissions={})
        eng = GuardrailEngine(config=config)
        sql = "SELECT * FROM orders"
        result = eng.apply_row_cap(sql, dialect="postgres")
        assert "500" in result

    def test_tsql_select_with_join(self, engine: GuardrailEngine) -> None:
        """T-SQL: adds TOP to SELECT with JOIN."""
        sql = "SELECT o.order_id, c.first_name FROM orders o JOIN customers c ON o.customer_id = c.customer_id"
        result = engine.apply_row_cap(sql, dialect="tsql")
        assert "1000" in result


# --- Injection Detection Tests ---


class TestDetectInjectionPatterns:
    """Tests for detect_injection_patterns method."""

    def test_clean_sql_returns_empty(self, engine: GuardrailEngine) -> None:
        """Clean SQL produces no injection findings."""
        sql = "SELECT name FROM customers WHERE customer_id = 42"
        result = engine.detect_injection_patterns(sql)
        assert result == []

    def test_detects_union_injection(self, engine: GuardrailEngine) -> None:
        """Detects UNION SELECT pattern."""
        sql = "SELECT name FROM customers UNION SELECT password FROM users"
        result = engine.detect_injection_patterns(sql)
        assert "UNION-based injection" in result

    def test_detects_union_all_injection(self, engine: GuardrailEngine) -> None:
        """Detects UNION ALL SELECT pattern."""
        sql = "SELECT name FROM customers UNION ALL SELECT secret FROM admins"
        result = engine.detect_injection_patterns(sql)
        assert "UNION-based injection" in result

    def test_detects_single_line_comment(self, engine: GuardrailEngine) -> None:
        """Detects -- comment sequence."""
        sql = "SELECT * FROM customers -- WHERE admin = true"
        result = engine.detect_injection_patterns(sql)
        assert "comment sequence (--)" in result

    def test_detects_multi_line_comment(self, engine: GuardrailEngine) -> None:
        """Detects /* */ comment sequence."""
        sql = "SELECT * FROM customers /* WHERE admin = true */"
        result = engine.detect_injection_patterns(sql)
        assert "comment sequence (/* */)" in result

    def test_detects_stacked_query(self, engine: GuardrailEngine) -> None:
        """Detects semicolon (stacked query)."""
        sql = "SELECT * FROM customers; DROP TABLE users"
        result = engine.detect_injection_patterns(sql)
        assert "stacked query (;)" in result

    def test_detects_tautology_1_equals_1(self, engine: GuardrailEngine) -> None:
        """Detects 1=1 tautological condition."""
        sql = "SELECT * FROM customers WHERE 1=1"
        result = engine.detect_injection_patterns(sql)
        assert "tautological condition" in result

    def test_detects_tautology_or_1_equals_1(self, engine: GuardrailEngine) -> None:
        """Detects OR 1=1 tautological condition."""
        sql = "SELECT * FROM customers WHERE name = 'x' OR 1=1"
        result = engine.detect_injection_patterns(sql)
        assert "tautological condition" in result

    def test_detects_unbalanced_single_quotes(self, engine: GuardrailEngine) -> None:
        """Detects unbalanced single quotes."""
        sql = "SELECT * FROM customers WHERE name = 'unbalanced"
        result = engine.detect_injection_patterns(sql)
        assert "unbalanced quotation marks" in result

    def test_detects_unbalanced_double_quotes(self, engine: GuardrailEngine) -> None:
        """Detects unbalanced double quotes."""
        sql = 'SELECT * FROM customers WHERE name = "unbalanced'
        result = engine.detect_injection_patterns(sql)
        assert "unbalanced quotation marks" in result

    def test_balanced_quotes_not_flagged(self, engine: GuardrailEngine) -> None:
        """Balanced quotes are not flagged."""
        sql = "SELECT * FROM customers WHERE name = 'test' AND city = 'NYC'"
        result = engine.detect_injection_patterns(sql)
        assert "unbalanced quotation marks" not in result

    def test_multiple_patterns_detected(self, engine: GuardrailEngine) -> None:
        """Multiple injection patterns can be reported simultaneously."""
        sql = "SELECT * FROM customers WHERE 1=1 UNION SELECT * FROM secrets -- hack"
        result = engine.detect_injection_patterns(sql)
        assert len(result) >= 3  # tautology + UNION + comment


# --- RBAC Tests ---


class TestCheckRbac:
    """Tests for check_rbac method."""

    def test_all_tables_permitted(self, engine: GuardrailEngine) -> None:
        """Returns empty list when user has access to all tables."""
        tables = ["customers", "orders"]
        roles = ["analyst"]
        result = engine.check_rbac(tables, roles)
        assert result == []

    def test_some_tables_denied(self, engine: GuardrailEngine) -> None:
        """Returns denied tables when user lacks access."""
        tables = ["customers", "campaigns", "support_tickets"]
        roles = ["analyst"]  # analyst can access customers but not campaigns/support_tickets
        result = engine.check_rbac(tables, roles)
        assert "campaigns" in result
        assert "support_tickets" in result
        assert "customers" not in result

    def test_multiple_roles_grant_access(self, engine: GuardrailEngine) -> None:
        """Multiple roles are combined to determine access."""
        tables = ["customers", "campaigns"]
        roles = ["analyst", "marketing"]
        result = engine.check_rbac(tables, roles)
        assert result == []

    def test_no_roles_all_denied(self, engine: GuardrailEngine) -> None:
        """User with no roles is denied all tables."""
        tables = ["customers", "orders"]
        roles = []
        result = engine.check_rbac(tables, roles)
        assert "customers" in result
        assert "orders" in result

    def test_case_insensitive_table_matching(self, engine: GuardrailEngine) -> None:
        """Table matching is case-insensitive."""
        tables = ["CUSTOMERS", "Orders"]
        roles = ["analyst"]
        result = engine.check_rbac(tables, roles)
        assert result == []

    def test_empty_permissions_allows_all(self) -> None:
        """When no permissions are configured, all tables are accessible."""
        config = GuardrailConfig(table_permissions={})
        eng = GuardrailEngine(config=config)
        tables = ["customers", "orders", "secret_table"]
        roles = ["anything"]
        result = eng.check_rbac(tables, roles)
        assert result == []

    def test_unknown_role_denied(self, engine: GuardrailEngine) -> None:
        """Unknown role grants no access."""
        tables = ["customers"]
        roles = ["unknown_role"]
        result = engine.check_rbac(tables, roles)
        assert "customers" in result


# --- PII Redaction Tests ---


class TestRedactPii:
    """Tests for redact_pii method."""

    def test_redacts_email(self, engine: GuardrailEngine) -> None:
        """Email addresses are redacted."""
        results = [{"name": "Alice", "email": "alice@example.com"}]
        redacted = engine.redact_pii(results)
        assert redacted[0]["email"] == REDACTED_PLACEHOLDER
        assert redacted[0]["name"] == "Alice"

    def test_redacts_phone_number(self, engine: GuardrailEngine) -> None:
        """Phone numbers are redacted."""
        results = [{"name": "Bob", "phone": "(555) 123-4567"}]
        redacted = engine.redact_pii(results)
        assert REDACTED_PLACEHOLDER in redacted[0]["phone"]

    def test_redacts_ssn(self, engine: GuardrailEngine) -> None:
        """National ID (SSN format) is redacted."""
        results = [{"name": "Carol", "ssn": "123-45-6789"}]
        redacted = engine.redact_pii(results)
        assert redacted[0]["ssn"] == REDACTED_PLACEHOLDER

    def test_does_not_redact_non_pii(self, engine: GuardrailEngine) -> None:
        """Non-PII string values are preserved."""
        results = [{"product": "Widget Pro", "price": "29.99", "category": "electronics"}]
        redacted = engine.redact_pii(results)
        assert redacted[0] == results[0]

    def test_preserves_non_string_values(self, engine: GuardrailEngine) -> None:
        """Non-string values (int, float, None) are preserved unchanged."""
        results = [{"id": 42, "price": 9.99, "notes": None}]
        redacted = engine.redact_pii(results)
        assert redacted[0]["id"] == 42
        assert redacted[0]["price"] == 9.99
        assert redacted[0]["notes"] is None

    def test_multiple_pii_in_single_value(self, engine: GuardrailEngine) -> None:
        """Multiple PII patterns in one string are all redacted."""
        results = [{"contact": "Email: john@test.com, SSN: 111-22-3333"}]
        redacted = engine.redact_pii(results)
        assert "john@test.com" not in redacted[0]["contact"]
        assert "111-22-3333" not in redacted[0]["contact"]

    def test_empty_results(self, engine: GuardrailEngine) -> None:
        """Empty result set returns empty list."""
        assert engine.redact_pii([]) == []

    def test_does_not_mutate_original(self, engine: GuardrailEngine) -> None:
        """Original results are not mutated."""
        results = [{"email": "test@example.com"}]
        engine.redact_pii(results)
        assert results[0]["email"] == "test@example.com"
