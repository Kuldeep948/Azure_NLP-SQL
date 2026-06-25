"""Main FastAPI application for the NLP-to-SQL Azure Harness.

Provides the HTTP API layer with endpoints for:
- POST /api/v1/query — Full NL-to-SQL pipeline execution
- POST /api/v1/feedback — User feedback submission
- GET /api/v1/health — Health check

The /query endpoint executes the full pipeline:
1. Validate input
2. Authenticate user
3. Check semantic cache → return early if hit
4. Load and render prompt template (with schema + few-shot examples)
5. Classify intent → return clarification if Ambiguous
6. Generate SQL via LLM Orchestrator
7. Validate SQL (syntax, safety, schema) → retry once on syntax failure
8. Apply guardrails (RBAC check, injection scan, row cap)
9. Execute query
10. Redact PII from results
11. Store in cache
12. Return response
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.api.auth import authenticate
from src.api.dependencies import (
    cleanup,
    get_executor,
    get_guardrail_engine,
    get_input_processor,
    get_observability,
    get_orchestrator,
    get_prompt_manager,
    get_schema_manager,
    get_semantic_cache,
    get_validator,
    get_feedback_manager,
)
from src.api.validation import QueryRequest as _BaseQueryRequest


class QueryRequest(_BaseQueryRequest):
    """Extended query request with session support for multi-turn conversations."""

    session_id: str | None = None  # For multi-turn conversation support (Section 6.5)
from src.harness.input_processor import Tier
from src.nlp_to_sql.exceptions import (
    AuthenticationError,
    AuthorizationError,
    HarnessError,
    InjectionDetectedError,
    LLMError,
    QueryExecutionError,
    TokenBudgetExceededError,
    ValidationError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response Models
# ---------------------------------------------------------------------------


class ColumnInfo(BaseModel):
    """Describes a single column in a query result set."""

    name: str
    data_type: str


class QueryResponse(BaseModel):
    """Successful query response with results."""

    columns: list[ColumnInfo]
    rows: list[dict[str, Any]]
    row_count: int
    sql: str
    tier: str
    cache_hit: bool
    truncated: bool
    trace_id: str
    summary: str | None = None
    visualization_suggestion: dict[str, str] | None = None


class ClarificationResponse(BaseModel):
    """Response when query is ambiguous and needs clarification."""

    clarification_prompt: str
    tier: str
    trace_id: str


class ErrorResponse(BaseModel):
    """Structured error response."""

    error: str
    detail: str | None = None
    trace_id: str | None = None


class FeedbackRequest(BaseModel):
    """User feedback submission."""

    rating: Literal["thumbs_up", "thumbs_down"]
    nl_query: str
    generated_sql: str
    trace_id: str


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str
    timestamp: str


# ---------------------------------------------------------------------------
# Application Lifecycle
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle management."""
    # Startup: load critical resources
    logger.info("Starting NLP-to-SQL Azure Harness API...")

    try:
        # Load schema metadata (required)
        schema_mgr = get_schema_manager()
        await schema_mgr.load()
        logger.info("Schema metadata loaded.")

        # Load prompt templates (required)
        prompt_mgr = get_prompt_manager()
        await prompt_mgr.load_templates()
        logger.info("Prompt templates loaded.")

    except Exception as exc:
        logger.error("Startup failed: %s", exc)
        raise

    logger.info("NLP-to-SQL Azure Harness API started successfully.")
    yield

    # Shutdown: clean up resources
    logger.info("Shutting down NLP-to-SQL Azure Harness API...")
    await cleanup()
    logger.info("Shutdown complete.")


# ---------------------------------------------------------------------------
# FastAPI Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="NLP-to-SQL Azure Harness",
    version="1.0.0",
    description="Converts natural language questions into validated, safe SQL queries executed against Azure SQL Database.",
    lifespan=lifespan,
)

# CORS middleware for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Global Exception Handler
# ---------------------------------------------------------------------------


@app.exception_handler(HarnessError)
async def harness_error_handler(request: Request, exc: HarnessError) -> JSONResponse:
    """Map domain exceptions to appropriate HTTP responses."""
    status_code = _map_exception_to_status(exc)
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(
            error=exc.message or type(exc).__name__,
            detail=exc.detail,
            trace_id=getattr(request.state, "trace_id", None),
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def general_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all handler for unexpected errors."""
    logger.exception("Unhandled exception: %s", exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            error="Internal server error",
            detail="An unexpected error occurred. Please try again later.",
            trace_id=getattr(request.state, "trace_id", None),
        ).model_dump(),
    )


def _map_exception_to_status(exc: HarnessError) -> int:
    """Map a HarnessError subclass to an HTTP status code."""
    if isinstance(exc, AuthenticationError):
        return status.HTTP_401_UNAUTHORIZED
    if isinstance(exc, AuthorizationError):
        return status.HTTP_403_FORBIDDEN
    if isinstance(exc, ValidationError):
        return status.HTTP_400_BAD_REQUEST
    if isinstance(exc, TokenBudgetExceededError):
        return status.HTTP_400_BAD_REQUEST
    if isinstance(exc, InjectionDetectedError):
        return status.HTTP_422_UNPROCESSABLE_ENTITY
    if isinstance(exc, LLMError):
        return status.HTTP_503_SERVICE_UNAVAILABLE
    if isinstance(exc, QueryExecutionError):
        return status.HTTP_500_INTERNAL_SERVER_ERROR
    return status.HTTP_500_INTERNAL_SERVER_ERROR


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/v1/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint for load balancer and monitoring."""
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        timestamp=datetime.utcnow().isoformat() + "Z",
    )


@app.post("/api/v1/feedback", status_code=status.HTTP_202_ACCEPTED)
async def submit_feedback(
    req: FeedbackRequest,
    user: dict = Depends(authenticate),
) -> dict[str, str]:
    """Accept user feedback for a previous query.

    Stores feedback for later review and potential few-shot promotion.
    Returns 202 Accepted immediately.
    """
    trace_id = str(uuid.uuid4())
    obs = get_observability()
    obs.log_event("feedback_received", trace_id, rating=req.rating, user_id=user["user_id"])

    feedback_mgr = get_feedback_manager()
    try:
        await feedback_mgr.store_feedback({
            "rating": req.rating,
            "nl_query": req.nl_query,
            "generated_sql": req.generated_sql,
            "trace_id": req.trace_id,
            "user_id": user["user_id"],
            "submitted_at": datetime.utcnow().isoformat(),
        })
    except Exception as exc:
        logger.warning("Feedback storage failed (non-critical): %s", exc)

    return {"status": "accepted", "trace_id": trace_id}


@app.post(
    "/api/v1/query",
    response_model=QueryResponse | ClarificationResponse,
    responses={
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def submit_query(
    req: QueryRequest,
    user: dict = Depends(authenticate),
) -> QueryResponse | ClarificationResponse:
    """Full NL-to-SQL pipeline execution.

    Pipeline steps:
    1. Validate input (done by Pydantic model)
    2. Authenticate user (done by Depends)
    3. Check semantic cache → return early if hit
    4. Load and render prompt template
    5. Classify intent → return clarification if Ambiguous
    6. Generate SQL via LLM Orchestrator
    7. Validate SQL → retry once on failure
    8. Apply guardrails (RBAC, injection, row cap)
    9. Execute query
    10. Redact PII from results
    11. Store in cache
    12. Return response
    """
    trace_id = str(uuid.uuid4())
    obs = get_observability()
    obs.log_event("query_received", trace_id, user_id=user["user_id"])

    nl_query = req.nl_query

    # --- Step 3: Check semantic cache ---
    cache = get_semantic_cache()
    cache_entry = await cache.lookup(nl_query)

    if cache_entry is not None:
        obs.log_event("cache_hit", trace_id)
        # Return cached result
        return QueryResponse(
            columns=[ColumnInfo(**c) for c in cache_entry.get("columns", [])],
            rows=cache_entry.get("rows", []),
            row_count=cache_entry.get("row_count", 0),
            sql=cache_entry.get("sql", ""),
            tier=cache_entry.get("tier", "cached"),
            cache_hit=True,
            truncated=cache_entry.get("truncated", False),
            trace_id=trace_id,
        )

    # --- Step 4: Load and render prompt template ---
    schema_mgr = get_schema_manager()
    prompt_mgr = get_prompt_manager()

    template = await prompt_mgr.get_template(version=req.prompt_version)

    # --- Step 4b: Load conversation context for multi-turn support (Section 6.5) ---
    conversation_context = ""
    if req.session_id:
        try:
            from src.harness.conversation import ConversationManager
            import redis.asyncio as aioredis
            from src.nlp_to_sql.config import get_config

            config = get_config()
            redis_client = aioredis.from_url(config.redis_connection_string, decode_responses=True)
            conv_mgr = ConversationManager(redis_client=redis_client)
            conversation_context = await conv_mgr.get_context_for_prompt(req.session_id)
        except Exception as exc:
            logger.warning("Conversation context retrieval failed (continuing without): %s", exc)

    # Generate embedding for few-shot retrieval
    few_shot_examples = []
    query_embedding: list[float] = []
    try:
        embedding_client = prompt_mgr._embedding_client
        embedding_response = await embedding_client.embeddings.create(
            input=nl_query,
            model="text-embedding-ada-002",
        )
        query_embedding = embedding_response.data[0].embedding
        few_shot_examples = await prompt_mgr.retrieve_few_shot_examples(
            query_embedding=query_embedding, top_k=5
        )
    except Exception as exc:
        logger.warning("Few-shot retrieval failed (continuing without): %s", exc)

    # --- Step 4c: Filter schema by user roles (Section 6.6) ---
    from src.harness.schema_filter import filter_schema_by_roles

    guardrail = get_guardrail_engine()
    filtered_schema = filter_schema_by_roles(
        schema=schema_mgr.metadata,
        user_roles=user.get("roles", []),
        table_permissions=guardrail.config.table_permissions,
    )

    rendered_prompt = await prompt_mgr.render(
        template=template,
        schema=filtered_schema,
        nl_query=nl_query,
        few_shot_examples=few_shot_examples,
    )

    # Inject conversation context if available (multi-turn support)
    if conversation_context:
        rendered_prompt = f"{rendered_prompt}\n\n{conversation_context}"

    # --- Step 5: Classify intent ---
    input_proc = get_input_processor()
    classification = await input_proc.classify(nl_query)

    if classification.tier == Tier.AMBIGUOUS:
        obs.log_event("ambiguous_query", trace_id, tier=classification.tier.value)
        return ClarificationResponse(
            clarification_prompt=classification.clarification_prompt or "Could you rephrase your question?",
            tier=classification.tier.value,
            trace_id=trace_id,
        )

    # --- Step 6: Generate SQL via LLM Orchestrator ---
    orchestrator = get_orchestrator()
    generation_result = await orchestrator.generate_sql(rendered_prompt)
    generated_sql = generation_result.sql

    # --- Step 6b: Log prompt variant for A/B testing (Section 7.1) ---
    prompt_variant = req.prompt_version or "v1"
    obs.log_event(
        "sql_generated",
        trace_id,
        model=generation_result.model_name,
        attempts=generation_result.attempt_count,
        latency_ms=generation_result.latency_ms,
        prompt_variant=prompt_variant,
    )

    # --- Step 6c: Estimate and log cost per query (Section 7.2) ---
    from src.harness.orchestrator import estimate_cost

    estimated_cost = estimate_cost(
        model_name=generation_result.model_name,
        prompt_tokens=generation_result.prompt_tokens,
        completion_tokens=generation_result.completion_tokens,
    )
    obs.log_event(
        "cost_estimate",
        trace_id,
        model=generation_result.model_name,
        prompt_tokens=generation_result.prompt_tokens,
        completion_tokens=generation_result.completion_tokens,
        cost_usd=estimated_cost,
    )

    # --- Step 7: Validate SQL (retry once on failure) ---
    validator = get_validator()
    validation_result = validator.validate(generated_sql)

    if not validation_result.is_valid:
        # Retry once: re-generate with error feedback
        logger.info(
            "SQL validation failed (attempt 1), retrying. Errors: %s",
            validation_result.errors,
        )
        error_feedback = (
            f"{rendered_prompt}\n\n"
            f"The previous SQL had errors: {'; '.join(validation_result.errors)}. "
            f"Please regenerate a correct query."
        )
        generation_result = await orchestrator.generate_sql(error_feedback)
        generated_sql = generation_result.sql

        validation_result = validator.validate(generated_sql)
        if not validation_result.is_valid:
            raise ValidationError(
                "Generated SQL failed validation after retry",
                detail="; ".join(validation_result.errors),
            )

    # Use normalized SQL if available
    final_sql = validation_result.normalized_sql or generated_sql

    # --- Step 8: Apply guardrails ---
    # guardrail engine already retrieved in Step 4c for schema filtering

    # 8a. RBAC check
    from sqlglot import exp as sqlglot_exp
    referenced_tables: list[str] = []
    if validation_result.ast:
        for table_node in validation_result.ast.find_all(sqlglot_exp.Table):
            if table_node.name:
                referenced_tables.append(table_node.name)

    denied_tables = guardrail.check_rbac(referenced_tables, user.get("roles", []))
    if denied_tables:
        raise AuthorizationError(
            f"Access denied to table(s): {', '.join(denied_tables)}",
            detail="Your role does not have permission to query these tables.",
        )

    # 8b. Injection scan
    injection_patterns = guardrail.detect_injection_patterns(final_sql)
    if injection_patterns:
        raise InjectionDetectedError(
            f"SQL injection patterns detected: {', '.join(injection_patterns)}",
            patterns=injection_patterns,
        )

    # 8c. Apply row cap
    capped_sql = guardrail.apply_row_cap(final_sql, dialect="tsql")

    # --- Step 9: Execute query ---
    executor = get_executor()
    exec_result = await executor.execute(capped_sql)

    obs.log_event(
        "query_executed",
        trace_id,
        row_count=exec_result["row_count"],
        truncated=exec_result["truncated"],
    )

    # --- Step 10: Redact PII from results ---
    redacted_rows = guardrail.redact_pii(exec_result["rows"])

    # --- Step 10b: Generate result summary (Section 6.4) ---
    summary = ""
    visualization = None
    try:
        from src.harness.summarizer import ResultSummarizer, VisualizationSuggester

        summarizer = ResultSummarizer(
            openai_client=prompt_mgr._embedding_client,
            model_deployment="gpt-4o",
        )
        summary = await summarizer.summarize(
            nl_query=nl_query,
            columns=exec_result["columns"],
            rows=redacted_rows,
            row_count=len(redacted_rows),
            truncated=exec_result["truncated"],
        )
        visualization = VisualizationSuggester.suggest(
            columns=exec_result["columns"],
            rows=redacted_rows,
            tier=classification.tier.value,
        )
    except Exception as exc:
        logger.warning("Summarization/visualization failed (non-critical): %s", exc)

    # --- Step 11: Store in cache ---
    try:
        await cache.store(
            nl_query=nl_query,
            embedding=query_embedding,
            sql=final_sql,
            results={
                "columns": exec_result["columns"],
                "rows": redacted_rows,
                "row_count": len(redacted_rows),
                "truncated": exec_result["truncated"],
                "tier": classification.tier.value,
                "sql": final_sql,
            },
        )
    except Exception as exc:
        logger.warning("Cache store failed (non-critical): %s", exc)

    # --- Step 11b: Update conversation session (multi-turn, Section 6.5) ---
    if req.session_id:
        try:
            from src.harness.conversation import ConversationManager
            import redis.asyncio as aioredis
            from src.nlp_to_sql.config import get_config

            config = get_config()
            redis_client = aioredis.from_url(config.redis_connection_string, decode_responses=True)
            conv_mgr = ConversationManager(redis_client=redis_client)
            await conv_mgr.add_turn(
                session_id=req.session_id,
                user_id=user["user_id"],
                nl_query=nl_query,
                generated_sql=final_sql,
                tier=classification.tier.value,
            )
        except Exception as exc:
            logger.warning("Conversation session update failed (non-critical): %s", exc)

    # --- Step 12: Return response ---
    obs.log_event("query_complete", trace_id, tier=classification.tier.value, cache_hit=False)

    return QueryResponse(
        columns=[ColumnInfo(**c) for c in exec_result["columns"]],
        rows=redacted_rows,
        row_count=len(redacted_rows),
        sql=final_sql,
        tier=classification.tier.value,
        cache_hit=False,
        truncated=exec_result["truncated"],
        trace_id=trace_id,
        summary=summary or None,
        visualization_suggestion=visualization,
    )
