"""Schema Metadata Manager for loading, caching, and polling schema metadata from Blob Storage.

Supports:
- Initial load from Azure Blob Storage using ManagedIdentity (DefaultAzureCredential)
- 60-second polling interval to detect changes via last-modified timestamp
- Startup failure raises SchemaLoadError
- Reload failure keeps stale (previously cached) data and logs the error

Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime

from pydantic import BaseModel

from azure.storage.blob.aio import BlobServiceClient

from src.nlp_to_sql.exceptions import SchemaLoadError

logger = logging.getLogger(__name__)


class ColumnSchema(BaseModel):
    """Represents a single column in a database table."""

    name: str
    data_type: str
    nullable: bool


class ForeignKey(BaseModel):
    """Represents a foreign key relationship."""

    column: str
    references_table: str
    references_column: str


class TableSchema(BaseModel):
    """Represents a database table with its columns, primary keys, and foreign keys."""

    name: str
    columns: list[ColumnSchema]
    primary_keys: list[str]
    foreign_keys: list[ForeignKey]


class SchemaMetadata(BaseModel):
    """Top-level schema metadata containing all table definitions."""

    tables: dict[str, TableSchema]


class SchemaManager:
    """Manages schema metadata lifecycle: loading from Blob Storage, caching, and polling.

    Args:
        blob_client: An async BlobServiceClient authenticated via ManagedIdentity.
        container_name: The Blob Storage container holding the schema metadata file.
        blob_name: The blob name/path for the schema metadata JSON file.
        poll_interval: Seconds between polling checks for metadata changes. Defaults to 60.
        on_schema_change: Optional callback invoked when schema is reloaded after a change.
            Useful for triggering cache invalidation or other side effects.
    """

    def __init__(
        self,
        blob_client: BlobServiceClient,
        container_name: str = "config",
        blob_name: str = "schema_metadata.json",
        poll_interval: int = 60,
        on_schema_change: "Callable[[], None] | None" = None,
    ):
        self._blob_client = blob_client
        self._container_name = container_name
        self._blob_name = blob_name
        self._poll_interval = poll_interval
        self._metadata: SchemaMetadata | None = None
        self._last_modified: datetime | None = None
        self._on_schema_change = on_schema_change

    async def load(self) -> None:
        """Initial load of schema metadata from Blob Storage.

        Raises:
            SchemaLoadError: If the blob is unavailable, unreachable, or unparseable.
                The system cannot start without valid schema metadata.
        """
        try:
            container_client = self._blob_client.get_container_client(self._container_name)
            blob_client = container_client.get_blob_client(self._blob_name)

            # Get blob properties for last-modified tracking
            properties = await blob_client.get_blob_properties()
            last_modified = properties.last_modified

            # Download and parse the schema metadata JSON
            download = await blob_client.download_blob()
            content = await download.readall()
            data = json.loads(content)

            self._metadata = SchemaMetadata.model_validate(data)
            self._last_modified = last_modified

            logger.info(
                "Schema metadata loaded successfully. Tables: %s",
                list(self._metadata.tables.keys()),
            )

        except Exception as exc:
            logger.error("Failed to load schema metadata at startup: %s", exc)
            raise SchemaLoadError(
                f"Schema metadata unavailable at startup: {exc}"
            ) from exc

    async def poll(self) -> None:
        """Check if the schema metadata file has been modified and reload if changed.

        On success: updates the cached metadata and last-modified timestamp.
        On failure: logs the error and continues serving with the previously cached metadata.
        This ensures the system remains available even if Blob Storage is temporarily unreachable.
        """
        try:
            container_client = self._blob_client.get_container_client(self._container_name)
            blob_client = container_client.get_blob_client(self._blob_name)

            # Check last-modified timestamp
            properties = await blob_client.get_blob_properties()
            last_modified = properties.last_modified

            # Only reload if the file has been modified since last check
            if self._last_modified is not None and last_modified <= self._last_modified:
                logger.debug("Schema metadata unchanged, skipping reload.")
                return

            # Download and parse updated schema
            download = await blob_client.download_blob()
            content = await download.readall()
            data = json.loads(content)

            new_metadata = SchemaMetadata.model_validate(data)
            self._metadata = new_metadata
            self._last_modified = last_modified

            logger.info(
                "Schema metadata reloaded. Tables: %s",
                list(self._metadata.tables.keys()),
            )

            # Invoke cache invalidation callback on schema change
            if self._on_schema_change is not None:
                try:
                    self._on_schema_change()
                    logger.info("Schema change callback executed successfully.")
                except Exception as cb_exc:
                    logger.warning("Schema change callback failed: %s", cb_exc)

        except Exception as exc:
            # On reload failure, keep stale data and log the error
            logger.error(
                "Failed to reload schema metadata (keeping stale data): %s", exc
            )

    @property
    def metadata(self) -> SchemaMetadata:
        """Return the current cached schema metadata.

        Raises:
            SchemaLoadError: If metadata has not been loaded yet (load() was never called
                or failed at startup).
        """
        if self._metadata is None:
            raise SchemaLoadError(
                "Schema metadata not available. Ensure load() is called at startup."
            )
        return self._metadata

    @property
    def poll_interval(self) -> int:
        """Return the configured polling interval in seconds."""
        return self._poll_interval

    @property
    def last_modified(self) -> datetime | None:
        """Return the last-modified timestamp of the loaded schema file."""
        return self._last_modified
