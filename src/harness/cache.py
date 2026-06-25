"""Semantic Cache — embedding-based query matching with Azure AI Search + Redis.

Short-circuits the NLP-to-SQL pipeline when a semantically equivalent query
has been previously answered, returning cached SQL and results.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class CacheEntry(BaseModel):
    """Represents a cached query result stored in Vector Store + Redis.

    Attributes:
        nl_query: The original natural language query.
        embedding: Vector embedding of the NL query.
        generated_sql: SQL generated for this query.
        results: Query execution results as a dictionary.
        created_at: UTC timestamp when the entry was created.
        ttl_seconds: Time-to-live in seconds (default 1 hour).
    """

    nl_query: str
    embedding: list[float]
    generated_sql: str
    results: dict[str, Any]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ttl_seconds: int = 3600


class SemanticCache:
    """Embedding-based semantic cache backed by Azure AI Search and Redis.

    Lookup embeds the incoming NL query, performs a vector search in Azure AI Search,
    and returns a cached result if cosine similarity meets the threshold. Redis stores
    the full result payload for low-latency retrieval.

    Graceful degradation: if Vector Store or embedding service is unreachable,
    the cache treats the situation as a cache miss (no error to caller).

    Args:
        embedding_client: Azure OpenAI client for generating embeddings.
        search_client: Azure AI Search client for vector similarity search.
        redis_client: Redis async client for result payload storage.
        similarity_threshold: Minimum cosine similarity for a cache hit (default 0.92).
        lookup_timeout_ms: Maximum time in milliseconds for a lookup operation (default 300).
    """

    def __init__(
        self,
        embedding_client: Any,
        search_client: Any,
        redis_client: Any,
        similarity_threshold: float = 0.92,
        lookup_timeout_ms: int = 300,
    ) -> None:
        self._embedding_client = embedding_client
        self._search_client = search_client
        self._redis_client = redis_client
        self._similarity_threshold = similarity_threshold
        self._lookup_timeout_ms = lookup_timeout_ms

    async def lookup(self, nl_query: str) -> CacheEntry | None:
        """Embed query, search vector store for similarity >= threshold within timeout.

        Args:
            nl_query: The natural language query to look up.

        Returns:
            CacheEntry if a semantically similar cached result is found, None otherwise.

        Notes:
            - Returns None on timeout (exceeds lookup_timeout_ms).
            - Returns None on any service error (graceful degradation).
        """
        try:
            result = await asyncio.wait_for(
                self._do_lookup(nl_query),
                timeout=self._lookup_timeout_ms / 1000.0,
            )
            return result
        except asyncio.TimeoutError:
            logger.warning("Cache lookup timed out after %dms", self._lookup_timeout_ms)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cache lookup error (treating as miss): %s", exc)
            return None

    async def _do_lookup(self, nl_query: str) -> CacheEntry | None:
        """Internal lookup: embed query, vector search, check threshold, retrieve from Redis.

        Args:
            nl_query: The natural language query to search for.

        Returns:
            CacheEntry if found and similarity meets threshold, None otherwise.
        """
        # Generate embedding for the incoming query
        embedding = await self._get_embedding(nl_query)

        # Search Azure AI Search for similar embeddings
        from azure.search.documents.models import VectorizedQuery

        vector_query = VectorizedQuery(
            vector=embedding,
            k_nearest_neighbors=1,
            fields="embedding",
        )

        results = self._search_client.search(
            search_text=None,
            vector_queries=[vector_query],
            top=1,
        )

        for result in results:
            score = result.get("@search.score", 0.0)
            if score >= self._similarity_threshold:
                # Retrieve full result from Redis for low-latency access
                cache_key = self._make_redis_key(result["id"])
                cached_data = await self._redis_client.get(cache_key)
                if cached_data:
                    data = json.loads(cached_data)
                    return CacheEntry(**data)

                # Fallback: reconstruct from search result if Redis miss
                return CacheEntry(
                    nl_query=result.get("nl_query", nl_query),
                    embedding=embedding,
                    generated_sql=result.get("generated_sql", ""),
                    results=json.loads(result.get("results", "{}")),
                    created_at=result.get("created_at", datetime.now(timezone.utc)),
                    ttl_seconds=result.get("ttl_seconds", 3600),
                )

        return None

    async def store(
        self,
        nl_query: str,
        embedding: list[float],
        sql: str,
        results: dict[str, Any],
        ttl: int = 3600,
    ) -> None:
        """Store entry in both Azure AI Search (Vector Store) and Redis.

        Args:
            nl_query: The natural language query.
            embedding: Pre-computed embedding vector.
            sql: Generated SQL for this query.
            results: Execution results to cache.
            ttl: Time-to-live in seconds (default 3600).

        Notes:
            Failures in either storage backend are logged but do not raise,
            maintaining graceful degradation.
        """
        entry = CacheEntry(
            nl_query=nl_query,
            embedding=embedding,
            generated_sql=sql,
            results=results,
            created_at=datetime.now(timezone.utc),
            ttl_seconds=ttl,
        )

        doc_id = self._generate_id(nl_query)

        # Store in Azure AI Search (Vector Store)
        document = {
            "id": doc_id,
            "nl_query": entry.nl_query,
            "embedding": entry.embedding,
            "generated_sql": entry.generated_sql,
            "results": json.dumps(entry.results),
            "created_at": entry.created_at.isoformat(),
            "ttl_seconds": entry.ttl_seconds,
        }

        try:
            self._search_client.upload_documents(documents=[document])
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to store cache entry in Vector Store: %s", exc)

        # Store in Redis with TTL for automatic expiration
        cache_key = self._make_redis_key(doc_id)
        try:
            await self._redis_client.set(
                cache_key,
                entry.model_dump_json(),
                ex=ttl,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to store cache entry in Redis: %s", exc)

    async def evict_expired(self) -> None:
        """Remove expired entries from Vector Store when Redis TTL fires.

        Queries Azure AI Search for all entries and removes those whose
        created_at + ttl_seconds is in the past. This acts as a cleanup
        mechanism for the Vector Store when Redis has already evicted
        the corresponding keys.
        """
        now = datetime.now(timezone.utc)

        try:
            # Search for all entries and check expiration
            results = self._search_client.search(
                search_text="*",
                select=["id", "created_at", "ttl_seconds"],
                top=1000,
            )

            expired_ids: list[str] = []
            for result in results:
                created_at_str = result.get("created_at")
                ttl = result.get("ttl_seconds", 3600)

                if created_at_str:
                    if isinstance(created_at_str, str):
                        created_at = datetime.fromisoformat(created_at_str)
                    else:
                        created_at = created_at_str

                    if created_at.tzinfo is None:
                        created_at = created_at.replace(tzinfo=timezone.utc)

                    expiry = created_at.timestamp() + ttl
                    if now.timestamp() > expiry:
                        expired_ids.append(result["id"])

            # Delete expired entries from Vector Store
            if expired_ids:
                documents_to_delete = [{"id": doc_id} for doc_id in expired_ids]
                self._search_client.delete_documents(documents=documents_to_delete)
                logger.info("Evicted %d expired cache entries", len(expired_ids))
            else:
                logger.debug("No expired cache entries to evict")

        except Exception as exc:  # noqa: BLE001
            logger.error("Error during cache eviction: %s", exc)

    async def _get_embedding(self, text: str) -> list[float]:
        """Generate embedding using the configured embedding client.

        Args:
            text: Text to embed.

        Returns:
            Embedding vector as a list of floats.
        """
        response = await self._embedding_client.embeddings.create(
            input=[text],
            model="text-embedding-ada-002",
        )
        return response.data[0].embedding

    @staticmethod
    def _generate_id(nl_query: str) -> str:
        """Generate a deterministic document ID from the query text.

        Args:
            nl_query: Query to hash.

        Returns:
            32-character hex string derived from SHA-256.
        """
        return hashlib.sha256(nl_query.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _make_redis_key(doc_id: str) -> str:
        """Create a namespaced Redis key.

        Args:
            doc_id: Document identifier.

        Returns:
            Redis key string in the format 'semantic_cache:<doc_id>'.
        """
        return f"semantic_cache:{doc_id}"
