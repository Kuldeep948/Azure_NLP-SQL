"""Unit tests for the Schema Metadata Manager.

Tests cover:
- Model validation (SchemaMetadata, TableSchema, ColumnSchema, ForeignKey)
- SchemaManager.load() success and failure behavior
- SchemaManager.poll() reload and stale-data retention
- SchemaManager.metadata property access
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.nlp_to_sql.exceptions import SchemaLoadError
from src.schema.metadata import (
    ColumnSchema,
    ForeignKey,
    SchemaManager,
    SchemaMetadata,
    TableSchema,
)


# --- Fixtures ---


SAMPLE_SCHEMA_DATA = {
    "tables": {
        "customers": {
            "name": "customers",
            "columns": [
                {"name": "customer_id", "data_type": "INT", "nullable": False},
                {"name": "first_name", "data_type": "NVARCHAR(100)", "nullable": False},
                {"name": "email", "data_type": "NVARCHAR(255)", "nullable": False},
            ],
            "primary_keys": ["customer_id"],
            "foreign_keys": [],
        },
        "orders": {
            "name": "orders",
            "columns": [
                {"name": "order_id", "data_type": "INT", "nullable": False},
                {"name": "customer_id", "data_type": "INT", "nullable": False},
                {"name": "status", "data_type": "NVARCHAR(20)", "nullable": True},
            ],
            "primary_keys": ["order_id"],
            "foreign_keys": [
                {
                    "column": "customer_id",
                    "references_table": "customers",
                    "references_column": "customer_id",
                }
            ],
        },
    }
}


def _make_mock_blob_client(
    content: bytes,
    last_modified: datetime,
    download_raises: Exception | None = None,
    properties_raises: Exception | None = None,
) -> MagicMock:
    """Create a mock BlobServiceClient with configured behavior."""
    mock_blob_service = MagicMock()
    mock_container = MagicMock()
    mock_blob = MagicMock()

    mock_blob_service.get_container_client.return_value = mock_container
    mock_container.get_blob_client.return_value = mock_blob

    # Mock get_blob_properties
    if properties_raises:
        mock_blob.get_blob_properties = AsyncMock(side_effect=properties_raises)
    else:
        mock_properties = MagicMock()
        mock_properties.last_modified = last_modified
        mock_blob.get_blob_properties = AsyncMock(return_value=mock_properties)

    # Mock download_blob
    if download_raises:
        mock_blob.download_blob = AsyncMock(side_effect=download_raises)
    else:
        mock_download = MagicMock()
        mock_download.readall = AsyncMock(return_value=content)
        mock_blob.download_blob = AsyncMock(return_value=mock_download)

    return mock_blob_service


# --- Model Tests ---


class TestModels:
    """Tests for Pydantic model validation."""

    def test_column_schema_creation(self):
        col = ColumnSchema(name="id", data_type="INT", nullable=False)
        assert col.name == "id"
        assert col.data_type == "INT"
        assert col.nullable is False

    def test_foreign_key_creation(self):
        fk = ForeignKey(
            column="customer_id",
            references_table="customers",
            references_column="customer_id",
        )
        assert fk.column == "customer_id"
        assert fk.references_table == "customers"
        assert fk.references_column == "customer_id"

    def test_table_schema_creation(self):
        table = TableSchema(
            name="orders",
            columns=[ColumnSchema(name="order_id", data_type="INT", nullable=False)],
            primary_keys=["order_id"],
            foreign_keys=[
                ForeignKey(
                    column="customer_id",
                    references_table="customers",
                    references_column="customer_id",
                )
            ],
        )
        assert table.name == "orders"
        assert len(table.columns) == 1
        assert table.primary_keys == ["order_id"]
        assert len(table.foreign_keys) == 1

    def test_schema_metadata_from_dict(self):
        metadata = SchemaMetadata.model_validate(SAMPLE_SCHEMA_DATA)
        assert "customers" in metadata.tables
        assert "orders" in metadata.tables
        assert metadata.tables["customers"].name == "customers"
        assert len(metadata.tables["orders"].foreign_keys) == 1


# --- SchemaManager Tests ---


class TestSchemaManagerLoad:
    """Tests for SchemaManager.load() method."""

    @pytest.mark.asyncio
    async def test_load_success(self):
        """load() should parse and cache metadata from Blob Storage."""
        last_modified = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        content = json.dumps(SAMPLE_SCHEMA_DATA).encode()
        mock_client = _make_mock_blob_client(content, last_modified)

        manager = SchemaManager(blob_client=mock_client)
        await manager.load()

        assert manager.metadata.tables["customers"].name == "customers"
        assert manager.last_modified == last_modified

    @pytest.mark.asyncio
    async def test_load_failure_raises_schema_load_error(self):
        """load() should raise SchemaLoadError if blob is unavailable."""
        mock_client = _make_mock_blob_client(
            content=b"",
            last_modified=datetime.now(tz=timezone.utc),
            properties_raises=ConnectionError("Blob Storage unreachable"),
        )

        manager = SchemaManager(blob_client=mock_client)
        with pytest.raises(SchemaLoadError, match="unavailable at startup"):
            await manager.load()

    @pytest.mark.asyncio
    async def test_load_failure_invalid_json(self):
        """load() should raise SchemaLoadError if the JSON is unparseable."""
        last_modified = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        mock_client = _make_mock_blob_client(b"not valid json", last_modified)

        manager = SchemaManager(blob_client=mock_client)
        with pytest.raises(SchemaLoadError):
            await manager.load()

    @pytest.mark.asyncio
    async def test_load_failure_invalid_schema(self):
        """load() should raise SchemaLoadError if JSON doesn't match schema model."""
        last_modified = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        invalid_data = json.dumps({"tables": {"bad": {"wrong_field": True}}}).encode()
        mock_client = _make_mock_blob_client(invalid_data, last_modified)

        manager = SchemaManager(blob_client=mock_client)
        with pytest.raises(SchemaLoadError):
            await manager.load()


class TestSchemaManagerPoll:
    """Tests for SchemaManager.poll() method."""

    @pytest.mark.asyncio
    async def test_poll_no_change_skips_reload(self):
        """poll() should skip reload when last-modified hasn't changed."""
        last_modified = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        content = json.dumps(SAMPLE_SCHEMA_DATA).encode()
        mock_client = _make_mock_blob_client(content, last_modified)

        manager = SchemaManager(blob_client=mock_client)
        await manager.load()

        # Poll with same last-modified - should not re-download
        await manager.poll()

        # download_blob called once (initial load), not called again on poll
        container = mock_client.get_container_client.return_value
        blob = container.get_blob_client.return_value
        assert blob.download_blob.call_count == 1

    @pytest.mark.asyncio
    async def test_poll_modified_reloads(self):
        """poll() should reload metadata when the file has been modified."""
        initial_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        content = json.dumps(SAMPLE_SCHEMA_DATA).encode()
        mock_client = _make_mock_blob_client(content, initial_time)

        manager = SchemaManager(blob_client=mock_client)
        await manager.load()

        # Simulate modified file on next poll
        new_time = datetime(2024, 1, 15, 11, 0, 0, tzinfo=timezone.utc)
        container = mock_client.get_container_client.return_value
        blob = container.get_blob_client.return_value

        new_props = MagicMock()
        new_props.last_modified = new_time
        blob.get_blob_properties = AsyncMock(return_value=new_props)

        updated_data = {
            "tables": {
                "products": {
                    "name": "products",
                    "columns": [
                        {"name": "product_id", "data_type": "INT", "nullable": False}
                    ],
                    "primary_keys": ["product_id"],
                    "foreign_keys": [],
                }
            }
        }
        new_download = MagicMock()
        new_download.readall = AsyncMock(return_value=json.dumps(updated_data).encode())
        blob.download_blob = AsyncMock(return_value=new_download)

        await manager.poll()

        assert "products" in manager.metadata.tables
        assert "customers" not in manager.metadata.tables
        assert manager.last_modified == new_time

    @pytest.mark.asyncio
    async def test_poll_failure_keeps_stale_data(self):
        """poll() should keep stale data and log error on reload failure."""
        initial_time = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        content = json.dumps(SAMPLE_SCHEMA_DATA).encode()
        mock_client = _make_mock_blob_client(content, initial_time)

        manager = SchemaManager(blob_client=mock_client)
        await manager.load()

        # Simulate failure on poll
        container = mock_client.get_container_client.return_value
        blob = container.get_blob_client.return_value
        blob.get_blob_properties = AsyncMock(
            side_effect=ConnectionError("Network error")
        )

        await manager.poll()  # Should not raise

        # Stale data still available
        assert "customers" in manager.metadata.tables
        assert manager.last_modified == initial_time


class TestSchemaManagerMetadataProperty:
    """Tests for SchemaManager.metadata property."""

    def test_metadata_before_load_raises(self):
        """Accessing metadata before load() should raise SchemaLoadError."""
        mock_client = MagicMock()
        manager = SchemaManager(blob_client=mock_client)

        with pytest.raises(SchemaLoadError, match="not available"):
            _ = manager.metadata

    @pytest.mark.asyncio
    async def test_metadata_after_load_returns_data(self):
        """Accessing metadata after successful load() returns cached data."""
        last_modified = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        content = json.dumps(SAMPLE_SCHEMA_DATA).encode()
        mock_client = _make_mock_blob_client(content, last_modified)

        manager = SchemaManager(blob_client=mock_client)
        await manager.load()

        metadata = manager.metadata
        assert isinstance(metadata, SchemaMetadata)
        assert len(metadata.tables) == 2


class TestSchemaManagerConfig:
    """Tests for SchemaManager configuration."""

    def test_default_poll_interval(self):
        """Default poll interval should be 60 seconds."""
        mock_client = MagicMock()
        manager = SchemaManager(blob_client=mock_client)
        assert manager.poll_interval == 60

    def test_custom_poll_interval(self):
        """Custom poll interval should be respected."""
        mock_client = MagicMock()
        manager = SchemaManager(blob_client=mock_client, poll_interval=120)
        assert manager.poll_interval == 120

    def test_custom_container_and_blob(self):
        """Custom container and blob names should be stored."""
        mock_client = MagicMock()
        manager = SchemaManager(
            blob_client=mock_client,
            container_name="my-container",
            blob_name="my/schema.json",
        )
        assert manager._container_name == "my-container"
        assert manager._blob_name == "my/schema.json"
