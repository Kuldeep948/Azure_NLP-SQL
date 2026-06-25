"""Core domain models for the NLP-to-SQL Azure Harness.

These Pydantic models define the data structures used throughout the
pipeline — from query ingestion through SQL generation and result delivery.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class NLQuery(BaseModel):
    """Validated natural language query input."""

    text: str = Field(..., min_length=1, max_length=2000)
    user_id: str
    session_id: str | None = None
    prompt_version: str | None = None


class TokenUsage(BaseModel):
    """Token consumption metrics for a single LLM invocation."""

    prompt_tokens: int = Field(..., ge=0)
    completion_tokens: int = Field(..., ge=0)
    total_tokens: int = Field(..., ge=0)


class GenerationResult(BaseModel):
    """Output from the LLM Orchestrator after SQL generation."""

    sql: str
    model_name: str
    prompt_tokens: int = Field(..., ge=0)
    completion_tokens: int = Field(..., ge=0)
    latency_ms: float = Field(..., ge=0)
    attempt_count: int = Field(..., ge=1)


class FewShotExample(BaseModel):
    """A retrieval-augmented few-shot example (NL query → SQL pair)."""

    nl_query: str
    sql: str
    similarity_score: float = Field(..., ge=0.0, le=1.0)


class PromptTemplate(BaseModel):
    """A versioned prompt template loaded from Blob Storage."""

    id: str
    version: str
    content: str
    placeholders: list[str]
    is_latest: bool = False
    created_at: datetime


class ColumnInfo(BaseModel):
    """Describes a single column in a query result set."""

    name: str
    data_type: str
