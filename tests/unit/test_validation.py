"""Unit tests for API input validation.

Tests cover Requirements 1.1, 1.2, 1.3, 1.4:
- Valid queries accepted (1–2000 chars, non-blank, valid UTF-8)
- Queries exceeding 2000 chars rejected with descriptive message
- Empty/whitespace-only queries rejected with descriptive message
- Invalid UTF-8 sequences rejected with descriptive message
"""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from src.api.validation import QueryRequest, validate_query_request


# --- Requirement 1.1: Valid queries accepted ---


class TestValidQueries:
    """Queries that meet all constraints should be accepted."""

    def test_simple_query(self):
        req = QueryRequest(nl_query="Show me all customers")
        assert req.nl_query == "Show me all customers"

    def test_min_length_query(self):
        req = QueryRequest(nl_query="x")
        assert req.nl_query == "x"

    def test_max_length_query(self):
        query = "a" * 2000
        req = QueryRequest(nl_query=query)
        assert len(req.nl_query) == 2000

    def test_unicode_characters(self):
        req = QueryRequest(nl_query="Показать всех клиентов")
        assert req.nl_query == "Показать всех клиентов"

    def test_emoji_characters(self):
        req = QueryRequest(nl_query="Find orders 📦 from last week")
        assert req.nl_query == "Find orders 📦 from last week"

    def test_with_prompt_version(self):
        req = QueryRequest(nl_query="Show revenue", prompt_version="v2")
        assert req.prompt_version == "v2"

    def test_prompt_version_defaults_none(self):
        req = QueryRequest(nl_query="Show revenue")
        assert req.prompt_version is None


# --- Requirement 1.2: Exceeds 2000 characters ---


class TestMaxLengthRejection:
    """Queries exceeding 2000 characters should be rejected."""

    def test_exceeds_max_length(self):
        query = "a" * 2001
        with pytest.raises(ValidationError) as exc_info:
            QueryRequest(nl_query=query)
        assert "2000" in str(exc_info.value)

    def test_validate_function_exceeds_max_length(self):
        query = "a" * 2001
        with pytest.raises(HTTPException) as exc_info:
            validate_query_request(query)
        assert exc_info.value.status_code == 400
        assert "2000" in exc_info.value.detail


# --- Requirement 1.3: Empty or whitespace-only ---


class TestWhitespaceRejection:
    """Empty or whitespace-only queries should be rejected."""

    def test_empty_string_rejected(self):
        with pytest.raises(ValidationError):
            QueryRequest(nl_query="")

    def test_single_space_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            QueryRequest(nl_query=" ")
        assert "blank" in str(exc_info.value).lower()

    def test_multiple_spaces_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            QueryRequest(nl_query="     ")
        assert "blank" in str(exc_info.value).lower()

    def test_tabs_only_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            QueryRequest(nl_query="\t\t\t")
        assert "blank" in str(exc_info.value).lower()

    def test_newlines_only_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            QueryRequest(nl_query="\n\n\n")
        assert "blank" in str(exc_info.value).lower()

    def test_mixed_whitespace_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            QueryRequest(nl_query=" \t\n\r ")
        assert "blank" in str(exc_info.value).lower()

    def test_validate_function_empty_rejected(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_query_request("")
        assert exc_info.value.status_code == 400
        assert "blank" in exc_info.value.detail.lower()

    def test_validate_function_whitespace_rejected(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_query_request("   ")
        assert exc_info.value.status_code == 400
        assert "blank" in exc_info.value.detail.lower()


# --- Requirement 1.4: Invalid UTF-8 ---


class TestUtf8Validation:
    """Invalid UTF-8 byte sequences should be rejected."""

    def test_bytes_valid_utf8_accepted(self):
        req = QueryRequest(nl_query=b"Hello world".decode("utf-8"))
        assert req.nl_query == "Hello world"

    def test_surrogate_in_string(self):
        """Strings with lone surrogates cannot round-trip through UTF-8."""
        # Lone surrogates are not valid UTF-8
        with pytest.raises(ValidationError) as exc_info:
            QueryRequest(nl_query="\ud800")
        assert "utf-8" in str(exc_info.value).lower()

    def test_validate_function_valid_utf8(self):
        result = validate_query_request("Valid query 你好")
        assert result.nl_query == "Valid query 你好"


# --- Edge cases ---


class TestEdgeCases:
    """Edge cases that combine multiple constraints."""

    def test_query_with_leading_trailing_whitespace_accepted(self):
        """Queries with content surrounded by whitespace are valid."""
        req = QueryRequest(nl_query="  hello  ")
        assert req.nl_query == "  hello  "

    def test_exactly_2000_chars_accepted(self):
        query = "x" * 2000
        req = QueryRequest(nl_query=query)
        assert len(req.nl_query) == 2000

    def test_exactly_2001_chars_rejected(self):
        query = "x" * 2001
        with pytest.raises(ValidationError):
            QueryRequest(nl_query=query)
