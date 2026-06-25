"""Feedback Manager — stores user feedback and promotes examples to few-shot index.

Handles the feedback loop where thumbs-up responses can be promoted to the
few-shot example Vector Store for improved future query generation.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class FeedbackEntry(BaseModel):
    """Represents a single piece of user feedback on a generated SQL query.

    Attributes:
        rating: User's rating — either thumbs_up or thumbs_down.
        nl_query: The natural language query that was evaluated.
        generated_sql: The SQL that was generated for the query.
        trace_id: Distributed trace ID linking this feedback to the original request.
        status: Processing status (pending | promoted | review_pending).
        created_at: UTC timestamp when the feedback was submitted.
    """

    rating: Literal["thumbs_up", "thumbs_down"]
    nl_query: str
    generated_sql: str
    trace_id: str
    status: str = "pending"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FeedbackManager:
    """Manages user feedback storage and few-shot promotion workflow.

    Persists all feedback to Azure Blob Storage and promotes thumbs-up
    entries to the Azure AI Search few-shot index for retrieval-augmented
    prompt construction.

    Args:
        blob_client: Azure Blob Storage async client for persisting feedback.
        search_client: Azure AI Search client for the few-shot index.
        embedding_client: Azure OpenAI client for generating embeddings.
        dedup_threshold: Cosine similarity threshold for deduplication (default 0.98).
    """

    def __init__(
        self,
        blob_client: Any,
        search_client: Any,
        embedding_client: Any,
        dedup_threshold: float = 0.98,
    ) -> None:
        self._blob_client = blob_client
        self._search_client = search_client
        self._embedding_client = embedding_client
        self._dedup_threshold = dedup_threshold

    async def store_feedback(self, entry: FeedbackEntry) -> None:
        """Persist feedback entry to Azure Blob Storage.

        Stores as a JSON blob under the feedback/ container path, keyed by
        trace_id and timestamp for uniqueness.

        Args:
            entry: Validated FeedbackEntry to store.

        Raises:
            Exception: If blob storage write fails.
        """
        blob_name = (
            f"feedback/{entry.trace_id}/"
            f"{entry.created_at.strftime('%Y%m%d_%H%M%S')}_{entry.rating}.json"
        )

        try:
            container_client = self._blob_client.get_container_client("feedback")

            # Ensure container exists
            try:
                await container_client.create_container()
            except Exception:  # noqa: BLE001
                pass  # Container already exists

            blob_client = container_client.get_blob_client(blob_name)
            await blob_client.upload_blob(
                entry.model_dump_json(),
                overwrite=True,
                content_settings={"content_type": "application/json"},
            )
            logger.info(
                "Stored feedback for trace_id=%s, rating=%s",
                entry.trace_id,
                entry.rating,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to store feedback: %s", exc)
            raise

    async def promote_to_few_shot(self, entry: FeedbackEntry) -> None:
        """Add a thumbs-up entry to the Vector Store few-shot index.

        If a semantically similar example already exists (similarity >= dedup_threshold),
        the existing entry is updated with the new SQL and trace ID instead of
        inserting a duplicate.

        Args:
            entry: FeedbackEntry with rating='thumbs_up' to promote.

        Raises:
            Exception: If vector store write fails.

        Notes:
            Only thumbs-up entries can be promoted. Non-thumbs-up entries
            are ignored with a warning log.
        """
        if entry.rating != "thumbs_up":
            logger.warning("Cannot promote non-thumbs-up entry (rating=%s)", entry.rating)
            return

        # Generate embedding for the NL query
        embedding = await self._get_embedding(entry.nl_query)

        # Check for existing near-duplicate
        existing_id = await self._find_duplicate(embedding)

        doc_id = existing_id or self._generate_id(entry.nl_query, entry.trace_id)
        document = {
            "id": doc_id,
            "nl_query": entry.nl_query,
            "embedding": embedding,
            "generated_sql": entry.generated_sql,
            "feedback_trace_id": entry.trace_id,
            "promoted_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            if existing_id:
                # Update existing entry (merge)
                self._search_client.merge_or_upload_documents(documents=[document])
                logger.info(
                    "Updated existing few-shot entry (dedup hit, threshold=%.2f) "
                    "doc_id=%s for trace_id=%s",
                    self._dedup_threshold,
                    existing_id,
                    entry.trace_id,
                )
            else:
                # Insert new entry
                self._search_client.upload_documents(documents=[document])
                logger.info(
                    "Promoted feedback to few-shot index: trace_id=%s, doc_id=%s",
                    entry.trace_id,
                    doc_id,
                )
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to promote to few-shot index: %s", exc)
            raise

    async def validate_payload(self, data: dict[str, Any]) -> FeedbackEntry:
        """Validate a raw feedback payload and return a FeedbackEntry.

        Checks that all required fields are present and have valid values.

        Args:
            data: Raw dictionary payload from the API request.

        Returns:
            Validated FeedbackEntry instance.

        Raises:
            ValueError: If required fields are missing or have invalid values.
        """
        required_fields = ["rating", "nl_query", "generated_sql", "trace_id"]
        missing = [f for f in required_fields if f not in data or not data[f]]

        if missing:
            raise ValueError(
                f"Missing or empty required fields: {', '.join(missing)}"
            )

        rating = data["rating"]
        if rating not in ("thumbs_up", "thumbs_down"):
            raise ValueError(
                f"Invalid rating '{rating}'. Must be 'thumbs_up' or 'thumbs_down'."
            )

        nl_query = data["nl_query"]
        if not isinstance(nl_query, str) or not nl_query.strip():
            raise ValueError("nl_query must be a non-empty string.")

        generated_sql = data["generated_sql"]
        if not isinstance(generated_sql, str) or not generated_sql.strip():
            raise ValueError("generated_sql must be a non-empty string.")

        trace_id = data["trace_id"]
        if not isinstance(trace_id, str) or not trace_id.strip():
            raise ValueError("trace_id must be a non-empty string.")

        return FeedbackEntry(
            rating=rating,
            nl_query=nl_query.strip(),
            generated_sql=generated_sql.strip(),
            trace_id=trace_id.strip(),
            status=data.get("status", "pending"),
            created_at=data.get("created_at", datetime.now(timezone.utc)),
        )

    async def _find_duplicate(self, embedding: list[float]) -> str | None:
        """Check if a semantically similar example exists in the few-shot index.

        Args:
            embedding: The embedding vector to compare against.

        Returns:
            Document ID of the existing entry if similarity >= threshold, None otherwise.
        """
        try:
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
                if score >= self._dedup_threshold:
                    return result["id"]

        except Exception as exc:  # noqa: BLE001
            logger.warning("Dedup check failed, proceeding with new insert: %s", exc)

        return None

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
    def _generate_id(nl_query: str, trace_id: str) -> str:
        """Generate a deterministic document ID from query + trace_id.

        Args:
            nl_query: The natural language query.
            trace_id: The request trace identifier.

        Returns:
            32-character hex string derived from SHA-256.
        """
        content = f"{nl_query}:{trace_id}"
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:32]
