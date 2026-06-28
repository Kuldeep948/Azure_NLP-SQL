"""API dependency injection for the NLP-to-SQL Azure Harness.

Provides lazy singleton instances of all harness components, initialized
from environment variables and DefaultAzureCredential. Each getter returns
the same instance on subsequent calls (module-level caching).

Components are created on first access to avoid startup cost for unused
dependencies in testing or partial deployments.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from dotenv import load_dotenv

# Ensure .env is loaded before any config access
load_dotenv()

from src.nlp_to_sql.config import get_config

logger = logging.getLogger(__name__)

# Module-level singletons (lazy initialization)
_schema_manager: Any = None
_prompt_manager: Any = None
_input_processor: Any = None
_orchestrator: Any = None
_validator: Any = None
_guardrail_engine: Any = None
_semantic_cache: Any = None
_executor: Any = None
_feedback_manager: Any = None
_observability: Any = None

# Shared Azure clients (lazy)
_blob_client: Any = None
_credential: Any = None


def _get_credential() -> Any:
    """Get or create the shared credential for Azure services.
    
    For local development without Azure CLI, falls back to API key auth.
    In production with Managed Identity, uses DefaultAzureCredential.
    """
    global _credential
    if _credential is None:
        import os
        # Check if we're in local dev (no Managed Identity endpoint)
        if os.environ.get("IDENTITY_ENDPOINT") is None:
            # Local dev: return None, individual clients will use API keys
            _credential = None
        else:
            from azure.identity.aio import DefaultAzureCredential
            _credential = DefaultAzureCredential()
    return _credential


def _get_blob_client() -> Any:
    """Get or create the shared async BlobServiceClient.
    
    Uses connection string for local dev, or Managed Identity in production.
    """
    global _blob_client
    if _blob_client is None:
        import os
        config = get_config()
        
        # Try connection string first (local dev)
        conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        if conn_str:
            try:
                from azure.storage.blob.aio import BlobServiceClient
                _blob_client = BlobServiceClient.from_connection_string(conn_str)
                return _blob_client
            except Exception as exc:
                logger.warning("Blob client from connection string failed: %s", exc)
        
        blob_url = config.azure_blob_storage_url
        
        # Skip blob client if URL is a placeholder
        if 'localhost' in blob_url or not blob_url.startswith('https://'):
            _blob_client = _LocalBlobStub()
            return _blob_client
            
        try:
            from azure.storage.blob.aio import BlobServiceClient
            credential = _get_credential()
            if credential is not None:
                _blob_client = BlobServiceClient(
                    account_url=blob_url,
                    credential=credential,
                )
            else:
                _blob_client = _LocalBlobStub()
        except Exception as exc:
            logger.warning("Blob client creation failed, using local stub: %s", exc)
            _blob_client = _LocalBlobStub()
    return _blob_client


class _LocalBlobStub:
    """Stub blob client that triggers local file fallback in SchemaManager and PromptManager."""
    def get_container_client(self, name: str):
        raise ConnectionError(f"No Blob Storage configured — using local file fallback for '{name}'")


def get_schema_manager() -> Any:
    """Get or create the SchemaManager singleton.

    Uses Azure Blob Storage to load and poll schema metadata.
    Wires a cache invalidation callback that evicts expired semantic cache
    entries when the schema changes.
    """
    global _schema_manager
    if _schema_manager is None:
        from src.schema.metadata import SchemaManager
        config = get_config()

        def _on_schema_change() -> None:
            """Invalidate semantic cache when schema metadata changes."""
            cache = get_semantic_cache()
            if hasattr(cache, "evict_expired"):
                try:
                    import asyncio
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(cache.evict_expired())
                    else:
                        loop.run_until_complete(cache.evict_expired())
                except Exception as exc:
                    logger.warning("Cache invalidation on schema change failed: %s", exc)
            elif hasattr(cache, "invalidate_all"):
                try:
                    import asyncio
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(cache.invalidate_all())
                    else:
                        loop.run_until_complete(cache.invalidate_all())
                except Exception as exc:
                    logger.warning("Cache invalidation on schema change failed: %s", exc)
            else:
                logger.info("Schema changed but cache does not support invalidation.")

        _schema_manager = SchemaManager(
            blob_client=_get_blob_client(),
            container_name=config.azure_blob_schema_container,
            blob_name="schema_metadata.json",
            poll_interval=60,
            on_schema_change=_on_schema_change,
        )
    return _schema_manager


def get_prompt_manager() -> Any:
    """Get or create the PromptManager singleton.

    Uses Azure Blob Storage for templates and Azure AI Search for few-shot retrieval.
    """
    global _prompt_manager
    if _prompt_manager is None:
        from src.harness.prompt_manager import PromptManager

        config = get_config()

        # Create the vector store client for few-shot index
        vector_store = None
        try:
            from azure.search.documents.aio import SearchClient
            from azure.core.credentials import AzureKeyCredential

            credential = _get_credential()
            if credential is None and config.azure_search_api_key:
                # Local dev: use API key
                credential = AzureKeyCredential(config.azure_search_api_key)
            
            if credential is not None:
                vector_store = SearchClient(
                    endpoint=config.azure_search_endpoint,
                    index_name=config.azure_search_fewshot_index,
                    credential=credential,
                )
        except Exception as exc:
            logger.warning("Vector store client creation failed: %s", exc)

        # Create the embedding client
        embedding_client = _create_embedding_client(config)

        _prompt_manager = PromptManager(
            blob_client=_get_blob_client(),
            vector_store=vector_store,
            embedding_client=embedding_client,
            container_name=config.azure_blob_prompts_container,
        )
    return _prompt_manager


def get_input_processor() -> Any:
    """Get or create the InputProcessor singleton.

    Uses Azure CLU for intent classification (if configured) with schema metadata.
    """
    global _input_processor
    if _input_processor is None:
        from src.harness.input_processor import InputProcessor

        config = get_config()
        schema_mgr = get_schema_manager()

        # Create CLU client if configured
        clu_client = None
        if config.azure_clu_endpoint and config.azure_clu_api_key:
            try:
                from azure.ai.language.conversations import ConversationAnalysisClient
                from azure.core.credentials import AzureKeyCredential

                clu_client = ConversationAnalysisClient(
                    endpoint=config.azure_clu_endpoint,
                    credential=AzureKeyCredential(config.azure_clu_api_key),
                )
            except Exception as exc:
                logger.warning("CLU client creation failed, using heuristics: %s", exc)

        _input_processor = InputProcessor(
            clu_client=clu_client,
            schema=schema_mgr.metadata,
            clu_project_name=config.azure_clu_project_name or "nlp-to-sql-intents",
            clu_deployment_name=config.azure_clu_deployment_name or "production",
        )
    return _input_processor


def get_orchestrator() -> Any:
    """Get or create the LLMOrchestrator singleton.

    Configures primary (GPT-4o) and fallback (GPT-4 Turbo) Azure OpenAI models.
    """
    global _orchestrator
    if _orchestrator is None:
        from langchain_openai import AzureChatOpenAI
        from src.harness.orchestrator import LLMOrchestrator

        config = get_config()

        primary_model = AzureChatOpenAI(
            azure_endpoint=config.azure_openai_endpoint,
            azure_deployment=config.azure_openai_primary_deployment,
            api_version=config.azure_openai_api_version,
            api_key=config.azure_openai_api_key or "",
            temperature=0,
        )

        fallback_model = AzureChatOpenAI(
            azure_endpoint=config.azure_openai_endpoint,
            azure_deployment=config.azure_openai_fallback_deployment,
            api_version=config.azure_openai_api_version,
            api_key=config.azure_openai_api_key or "",
            temperature=0,
        )

        _orchestrator = LLMOrchestrator(
            primary_model=primary_model,
            fallback_model=fallback_model,
            max_retries=config.max_retries,
            initial_backoff=config.initial_backoff_seconds,
        )
    return _orchestrator


def get_validator() -> Any:
    """Get or create the OutputValidator singleton.

    Uses the current schema metadata for conformance checks.
    """
    global _validator
    if _validator is None:
        from src.harness.validator import OutputValidator

        schema_mgr = get_schema_manager()
        _validator = OutputValidator(
            schema=schema_mgr.metadata,
            dialect="tsql",
        )
    return _validator


def get_guardrail_engine() -> Any:
    """Get or create the GuardrailEngine singleton.

    Configured with row cap, timeout, and table permissions from app config.
    """
    global _guardrail_engine
    if _guardrail_engine is None:
        from src.harness.guardrails import GuardrailConfig, GuardrailEngine

        config = get_config()

        guardrail_config = GuardrailConfig(
            row_cap=config.row_cap,
            timeout_seconds=config.query_timeout_seconds,
            # Table permissions could be loaded from Key Vault or config
            # For now, empty means all tables accessible
            table_permissions={},
        )
        _guardrail_engine = GuardrailEngine(config=guardrail_config)
    return _guardrail_engine


def get_semantic_cache() -> Any:
    """Get or create the SemanticCache singleton.

    Uses Azure AI Search for vector lookup and Redis for result caching.
    Falls back to stub if cache dependencies are not fully configured.
    """
    global _semantic_cache
    if _semantic_cache is None:
        try:
            from azure.search.documents import SearchClient as SyncSearchClient
            from src.harness.cache import SemanticCache
            import redis.asyncio as aioredis

            config = get_config()
            credential = _get_credential()

            # Create search client for semantic cache index
            search_client = SyncSearchClient(
                endpoint=config.azure_search_endpoint,
                index_name=config.azure_search_cache_index,
                credential=credential,
            )

            # Create Redis client
            redis_client = aioredis.from_url(
                config.redis_connection_string,
                decode_responses=True,
            )

            # Create embedding client
            embedding_client = _create_embedding_client(config)

            _semantic_cache = SemanticCache(
                embedding_client=embedding_client,
                search_client=search_client,
                redis_client=redis_client,
                similarity_threshold=config.cache_similarity_threshold,
                lookup_timeout_ms=300,
            )
            logger.info("Semantic cache initialized (full mode).")
        except Exception as exc:
            logger.warning("Semantic cache initialization failed, using stub: %s", exc)
            _semantic_cache = _StubSemanticCache()
    return _semantic_cache


def get_executor() -> Any:
    """Get or create the QueryExecutor singleton.

    Connects to Azure SQL Database using the configured connection string.
    """
    global _executor
    if _executor is None:
        from src.harness.executor import QueryExecutor

        config = get_config()
        _executor = QueryExecutor(
            connection_string=config.sql_connection_string,
            timeout_seconds=config.query_timeout_seconds,
        )
    return _executor


def get_feedback_manager() -> Any:
    """Get or create the FeedbackManager singleton.

    Uses Azure Blob Storage for feedback persistence and Azure AI Search
    for few-shot promotion.
    """
    global _feedback_manager
    if _feedback_manager is None:
        try:
            from azure.search.documents import SearchClient as SyncSearchClient
            from src.harness.feedback import FeedbackManager

            config = get_config()
            credential = _get_credential()

            # Few-shot index client for promotion
            search_client = SyncSearchClient(
                endpoint=config.azure_search_endpoint,
                index_name=config.azure_search_fewshot_index,
                credential=credential,
            )

            embedding_client = _create_embedding_client(config)

            _feedback_manager = FeedbackManager(
                blob_client=_get_blob_client(),
                search_client=search_client,
                embedding_client=embedding_client,
                dedup_threshold=0.98,
            )
            logger.info("Feedback manager initialized (full mode).")
        except Exception as exc:
            logger.warning("Feedback manager initialization failed, using stub: %s", exc)
            _feedback_manager = _StubFeedbackManager()
    return _feedback_manager


def get_observability() -> Any:
    """Get or create the ObservabilityLayer singleton.

    Connects to Azure Application Insights for telemetry.
    Falls back to console logging if App Insights is not configured.
    """
    global _observability
    if _observability is None:
        try:
            from src.harness.observability import ObservabilityLayer

            config = get_config()
            connection_string = getattr(config, "app_insights_connection_string", None)
            _observability = ObservabilityLayer(connection_string=connection_string)
            logger.info("Observability layer initialized.")
        except Exception as exc:
            logger.warning("Observability initialization failed, using stub: %s", exc)
            _observability = _StubObservability()
    return _observability


def _create_embedding_client(config: Any) -> Any:
    """Create an Azure OpenAI embedding client for vector operations."""
    from openai import AsyncAzureOpenAI

    return AsyncAzureOpenAI(
        azure_endpoint=config.azure_openai_endpoint,
        api_key=config.azure_openai_api_key or "",
        api_version=config.azure_openai_api_version,
    )


# ---------------------------------------------------------------------------
# Stub implementations for components not yet fully implemented
# ---------------------------------------------------------------------------


class _StubSemanticCache:
    """Stub semantic cache that always returns a cache miss."""

    async def lookup(self, nl_query: str) -> None:
        return None

    async def store(
        self, nl_query: str, embedding: list[float], sql: str, results: dict, ttl: int = 3600
    ) -> None:
        pass


class _StubFeedbackManager:
    """Stub feedback manager that accepts and discards feedback."""

    async def store_feedback(self, entry: Any) -> None:
        logger.debug("Feedback stored (stub): %s", entry)


class _StubObservability:
    """Stub observability layer that logs to standard logger."""

    def log_event(self, event_type: str, trace_id: str, **kwargs: Any) -> None:
        logger.info("Event [%s] trace=%s %s", event_type, trace_id, kwargs)

    def record_metric(self, metric_name: str, value: float, dimensions: dict | None = None) -> None:
        logger.debug("Metric %s=%f %s", metric_name, value, dimensions)

    def start_span(self, operation_name: str, trace_id: str) -> None:
        logger.debug("Span start: %s trace=%s", operation_name, trace_id)


async def cleanup() -> None:
    """Cleanup all singleton resources on application shutdown."""
    global _blob_client, _credential, _executor

    if _executor is not None:
        await _executor.close()

    if _blob_client is not None:
        await _blob_client.close()

    if _credential is not None:
        await _credential.close()

    logger.info("All dependency resources cleaned up.")
