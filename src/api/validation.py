"""API input validation for the NLP-to-SQL Azure Harness.

Provides Pydantic-based request models with custom validators that enforce:
- 1–2000 character length (Requirement 1.1, 1.2)
- Non-whitespace-only content (Requirement 1.3)
- Valid UTF-8 encoding (Requirement 1.4)

Returns HTTP 400 with descriptive error messages for invalid inputs.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, field_validator


class QueryRequest(BaseModel):
    """Validated request body for the /query endpoint.

    Attributes:
        nl_query: The natural language query string. Must be 1–2000 characters,
                  not whitespace-only, and valid UTF-8.
        prompt_version: Optional prompt template version to use. If omitted,
                        the latest template is used.
    """

    nl_query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Natural language query (1–2000 characters, non-blank, valid UTF-8)",
    )
    prompt_version: str | None = None

    @field_validator("nl_query")
    @classmethod
    def reject_whitespace_only(cls, value: str) -> str:
        """Reject queries that contain only whitespace characters.

        Requirement 1.3: empty or whitespace-only queries return HTTP 400.
        """
        if not value.strip():
            raise ValueError("Query cannot be blank")
        return value

    @field_validator("nl_query", mode="before")
    @classmethod
    def validate_utf8(cls, value: object) -> str:
        """Validate that the input is a proper UTF-8 string.

        Requirement 1.4: byte sequences that are not valid UTF-8 return HTTP 400.
        If the value arrives as bytes, attempt UTF-8 decoding. If it arrives as
        a string, verify it can round-trip through UTF-8 encoding without loss.
        """
        if isinstance(value, bytes):
            try:
                return value.decode("utf-8")
            except (UnicodeDecodeError, ValueError) as exc:
                raise ValueError(
                    "Query must be valid UTF-8 text"
                ) from exc

        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except (UnicodeEncodeError, ValueError) as exc:
                raise ValueError(
                    "Query must be valid UTF-8 text"
                ) from exc
            return value

        raise ValueError("Query must be a string")


def validate_query_request(nl_query: str) -> QueryRequest:
    """Standalone validation function usable as a FastAPI dependency or directly.

    Args:
        nl_query: The raw query string to validate.

    Returns:
        A validated QueryRequest instance.

    Raises:
        HTTPException: 400 status with a descriptive error message if validation fails.
    """
    # Check length before Pydantic to give a specific max-length message
    if len(nl_query) > 2000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum allowed length is 2000 characters",
        )

    if not nl_query:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query cannot be blank",
        )

    try:
        return QueryRequest(nl_query=nl_query)
    except Exception as exc:
        # Extract user-facing message from Pydantic ValidationError
        detail = _extract_validation_message(exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
        ) from exc


def _extract_validation_message(exc: Exception) -> str:
    """Extract a user-friendly message from a Pydantic validation error."""
    from pydantic import ValidationError as PydanticValidationError

    if isinstance(exc, PydanticValidationError):
        errors = exc.errors()
        if errors:
            # Use the message from the first error
            msg = errors[0].get("msg", "")
            # Pydantic prefixes with "Value error, " for field_validator raises
            if msg.startswith("Value error, "):
                return msg[len("Value error, "):]
            return msg

    return str(exc)
