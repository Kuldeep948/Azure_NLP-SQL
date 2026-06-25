"""Custom exception hierarchy for the NLP-to-SQL Azure Harness.

Each exception maps to a specific failure domain within the pipeline,
enabling targeted error handling and consistent HTTP response codes.
"""


class HarnessError(Exception):
    """Base exception for all NLP-to-SQL Harness errors."""

    def __init__(self, message: str = "", *, detail: str | None = None) -> None:
        self.message = message
        self.detail = detail
        super().__init__(message)


class ConfigurationError(HarnessError):
    """Raised when system configuration is invalid or unavailable.

    Examples: Key Vault unreachable, missing required secrets, invalid
    prompt template, missing environment variables.
    Maps to HTTP 500 or prevents startup.
    """


class ValidationError(HarnessError):
    """Raised when input or output validation fails.

    Examples: NL query too long, blank query, Generated SQL fails syntax
    check, schema conformance failure.
    Maps to HTTP 400 (input) or HTTP 422 (output).
    """


class AuthenticationError(HarnessError):
    """Raised when authentication fails.

    Examples: Missing bearer token, expired token, invalid token signature,
    Managed Identity credential failure.
    Maps to HTTP 401.
    """


class AuthorizationError(HarnessError):
    """Raised when RBAC denies access.

    Examples: User role does not have access to referenced table(s).
    Maps to HTTP 403.
    """


class LLMError(HarnessError):
    """Raised when the LLM Orchestrator cannot generate SQL.

    Examples: All retry/fallback attempts exhausted, token budget exceeded.
    Maps to HTTP 503.
    """


class QueryExecutionError(HarnessError):
    """Raised when SQL execution against the database fails.

    Examples: Database connection error, query timeout, runtime SQL error.
    Maps to HTTP 500 or HTTP 504 (timeout).
    """


class CacheError(HarnessError):
    """Raised when the semantic cache encounters a non-recoverable error.

    Note: Transient cache failures should be treated as cache misses and
    not propagated. This exception is for configuration or persistent issues.
    """


class InjectionDetectedError(HarnessError):
    """Raised when SQL injection patterns are detected in Generated SQL.

    Maps to HTTP 422.
    """

    def __init__(self, message: str = "", *, patterns: list[str] | None = None) -> None:
        super().__init__(message)
        self.patterns = patterns or []


class SchemaError(HarnessError):
    """Raised when schema metadata is unavailable or invalid.

    Examples: Blob Storage unreachable, unparseable schema JSON,
    referenced table/column not found in metadata.
    Maps to HTTP 503 (unavailable) or HTTP 422 (invalid references).
    """


class SchemaLoadError(SchemaError):
    """Raised when schema metadata cannot be loaded at startup.

    Examples: Blob Storage unreachable during initial load, unparseable JSON.
    Maps to HTTP 503 or prevents startup.
    """


class SchemaLoadError(SchemaError):
    """Raised when schema metadata cannot be loaded at startup.

    Examples: Blob Storage unreachable, unparseable schema JSON file.
    Prevents the system from starting.
    """


class TemplateRenderError(ConfigurationError):
    """Raised when prompt template rendering fails.

    Examples: Missing placeholder in template, substitution error.
    Maps to HTTP 500.
    """


class TokenBudgetExceededError(LLMError):
    """Raised when the prompt exceeds the model's context window.

    The trimming algorithm has removed all few-shot examples and the
    prompt still exceeds the token budget.
    Maps to HTTP 400.
    """
