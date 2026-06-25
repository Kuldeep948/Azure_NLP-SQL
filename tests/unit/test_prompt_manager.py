"""Unit tests for the PromptManager class.

Tests cover:
- Template loading from Blob Storage
- Version-specific and latest template retrieval
- Template rendering with placeholder substitution
- Few-shot example retrieval from vector store
- Error handling (unreachable storage, missing templates, missing placeholders)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.harness.prompt_manager import PromptManager
from src.nlp_to_sql.exceptions import ConfigurationError
from src.nlp_to_sql.models import FewShotExample, PromptTemplate
from src.schema.metadata import ColumnSchema, SchemaMetadata, TableSchema


# --- Fixtures ---


@pytest.fixture
def mock_blob_client():
    """Create a mock BlobServiceClient.
    
    Note: get_container_client is synchronous in the Azure SDK async client.
    """
    return MagicMock()


@pytest.fixture
def mock_vector_store():
    """Create a mock SearchClient."""
    return AsyncMock()


@pytest.fixture
def mock_embedding_client():
    """Create a mock embedding client."""
    return AsyncMock()


@pytest.fixture
def prompt_manager(mock_blob_client, mock_vector_store, mock_embedding_client):
    """Create a PromptManager instance with mocked dependencies."""
    return PromptManager(
        blob_client=mock_blob_client,
        vector_store=mock_vector_store,
        embedding_client=mock_embedding_client,
        container_name="prompts",
    )


@pytest.fixture
def sample_metadata_json():
    """Sample metadata.json content for templates."""
    return json.dumps({
        "templates": [
            {
                "version": "v1",
                "blob_name": "system_prompt_v1.txt",
                "is_latest": True,
                "created_at": "2024-01-15T10:00:00Z",
            },
            {
                "version": "v2",
                "blob_name": "system_prompt_v2.txt",
                "is_latest": False,
                "created_at": "2024-02-01T10:00:00Z",
            },
        ]
    }).encode("utf-8")


@pytest.fixture
def sample_template_content():
    """Sample template content with placeholders."""
    return (
        "You are a SQL assistant.\n\n"
        "Schema:\n{{schema}}\n\n"
        "Examples:\n{{few_shot_examples}}\n\n"
        "Question: {{nl_query}}\n"
        "SQL:"
    )


@pytest.fixture
def sample_schema():
    """Create a sample SchemaMetadata for testing."""
    return SchemaMetadata(
        tables={
            "customers": TableSchema(
                name="customers",
                columns=[
                    ColumnSchema(name="customer_id", data_type="INT", nullable=False),
                    ColumnSchema(name="first_name", data_type="NVARCHAR(100)", nullable=False),
                    ColumnSchema(name="email", data_type="NVARCHAR(255)", nullable=False),
                ],
                primary_keys=["customer_id"],
                foreign_keys=[],
            )
        }
    )


def _setup_blob_downloads(mock_blob_client, metadata_content, template_contents):
    """Helper to configure mock blob client for download operations."""
    container_client = MagicMock()
    mock_blob_client.get_container_client.return_value = container_client

    def make_blob_client(blob_name):
        blob_client = MagicMock()
        download_mock = AsyncMock()

        if blob_name == "metadata.json":
            download_mock.readall.return_value = metadata_content
        elif blob_name in template_contents:
            download_mock.readall.return_value = template_contents[blob_name].encode("utf-8")
        else:
            raise Exception(f"Blob not found: {blob_name}")

        blob_client.download_blob = AsyncMock(return_value=download_mock)
        return blob_client

    container_client.get_blob_client.side_effect = make_blob_client


# --- Tests for load_templates ---


async def test_load_templates_success(
    prompt_manager, mock_blob_client, sample_metadata_json, sample_template_content
):
    """Templates are loaded and cached successfully from Blob Storage."""
    _setup_blob_downloads(
        mock_blob_client,
        sample_metadata_json,
        {
            "system_prompt_v1.txt": sample_template_content,
            "system_prompt_v2.txt": "V2 template: {{schema}} {{few_shot_examples}} {{nl_query}}",
        },
    )

    await prompt_manager.load_templates()

    assert len(prompt_manager._templates) == 2
    assert "v1" in prompt_manager._templates
    assert "v2" in prompt_manager._templates
    assert prompt_manager._latest_version == "v1"


async def test_load_templates_blob_unreachable(prompt_manager, mock_blob_client):
    """ConfigurationError is raised when Blob Storage is unreachable."""
    mock_blob_client.get_container_client.side_effect = Exception("Connection refused")

    with pytest.raises(ConfigurationError, match="Blob Storage unreachable"):
        await prompt_manager.load_templates()


async def test_load_templates_no_latest_marked(prompt_manager, mock_blob_client):
    """ConfigurationError raised when no template is marked as latest."""
    metadata = json.dumps({
        "templates": [
            {"version": "v1", "blob_name": "t1.txt", "is_latest": False},
        ]
    }).encode("utf-8")

    _setup_blob_downloads(
        mock_blob_client,
        metadata,
        {"t1.txt": "{{schema}} {{few_shot_examples}} {{nl_query}}"},
    )

    with pytest.raises(ConfigurationError, match="No template is marked as latest"):
        await prompt_manager.load_templates()


async def test_load_templates_empty_list(prompt_manager, mock_blob_client):
    """ConfigurationError raised when templates list is empty."""
    metadata = json.dumps({"templates": []}).encode("utf-8")

    _setup_blob_downloads(mock_blob_client, metadata, {})

    with pytest.raises(ConfigurationError, match="No templates defined"):
        await prompt_manager.load_templates()


# --- Tests for get_template ---


async def test_get_template_specific_version(prompt_manager):
    """Specific version is returned when requested."""
    template = PromptTemplate(
        id="template-v1",
        version="v1",
        content="test content",
        placeholders=["schema", "few_shot_examples", "nl_query"],
        is_latest=True,
        created_at=datetime.now(timezone.utc),
    )
    prompt_manager._templates["v1"] = template
    prompt_manager._latest_version = "v1"

    result = await prompt_manager.get_template(version="v1")
    assert result.version == "v1"


async def test_get_template_latest(prompt_manager):
    """Latest template returned when no version specified."""
    template = PromptTemplate(
        id="template-v2",
        version="v2",
        content="latest content",
        placeholders=["schema", "few_shot_examples", "nl_query"],
        is_latest=True,
        created_at=datetime.now(timezone.utc),
    )
    prompt_manager._templates["v2"] = template
    prompt_manager._latest_version = "v2"

    result = await prompt_manager.get_template()
    assert result.version == "v2"


async def test_get_template_version_not_found(prompt_manager):
    """ConfigurationError raised for non-existent version."""
    prompt_manager._templates = {}

    with pytest.raises(ConfigurationError, match="Template version 'v99' not found"):
        await prompt_manager.get_template(version="v99")


async def test_get_template_no_latest_configured(prompt_manager):
    """ConfigurationError raised when no latest version is set."""
    prompt_manager._latest_version = None

    with pytest.raises(ConfigurationError, match="No latest template is configured"):
        await prompt_manager.get_template()


# --- Tests for render ---


async def test_render_success(prompt_manager, sample_schema):
    """Template renders correctly with all placeholders substituted."""
    template = PromptTemplate(
        id="t1",
        version="v1",
        content="Schema:\n{{schema}}\n\nExamples:\n{{few_shot_examples}}\n\nQ: {{nl_query}}\nSQL:",
        placeholders=["schema", "few_shot_examples", "nl_query"],
        is_latest=True,
        created_at=datetime.now(timezone.utc),
    )

    examples = [
        FewShotExample(
            nl_query="How many customers?",
            sql="SELECT COUNT(*) FROM customers",
            similarity_score=0.95,
        )
    ]

    rendered = await prompt_manager.render(
        template=template,
        schema=sample_schema,
        nl_query="Show all orders",
        few_shot_examples=examples,
    )

    # No unsubstituted placeholders remain
    assert "{{" not in rendered
    assert "}}" not in rendered

    # All values appear
    assert "Show all orders" in rendered
    assert "customers" in rendered
    assert "How many customers?" in rendered


async def test_render_missing_placeholder(prompt_manager, sample_schema):
    """ConfigurationError raised when required placeholder is missing from template."""
    # Template missing the 'schema' placeholder
    template = PromptTemplate(
        id="t1",
        version="v1",
        content="Q: {{nl_query}}\nExamples: {{few_shot_examples}}\nSQL:",
        placeholders=["nl_query", "few_shot_examples"],  # missing 'schema'
        is_latest=True,
        created_at=datetime.now(timezone.utc),
    )

    with pytest.raises(ConfigurationError, match="Required placeholder '{{schema}}'"):
        await prompt_manager.render(
            template=template,
            schema=sample_schema,
            nl_query="test",
            few_shot_examples=[],
        )


async def test_render_no_few_shot_examples(prompt_manager, sample_schema):
    """Template renders correctly with empty few-shot examples list."""
    template = PromptTemplate(
        id="t1",
        version="v1",
        content="{{schema}}\n{{few_shot_examples}}\n{{nl_query}}",
        placeholders=["schema", "few_shot_examples", "nl_query"],
        is_latest=True,
        created_at=datetime.now(timezone.utc),
    )

    rendered = await prompt_manager.render(
        template=template,
        schema=sample_schema,
        nl_query="test query",
        few_shot_examples=[],
    )

    assert "No examples available." in rendered
    assert "test query" in rendered


# --- Tests for retrieve_few_shot_examples ---


async def test_retrieve_few_shot_examples_success(prompt_manager, mock_vector_store):
    """Few-shot examples are retrieved and sorted by similarity."""

    class MockResults:
        def __init__(self, data):
            self._data = data

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._data:
                raise StopAsyncIteration
            return self._data.pop(0)

    results_data = [
        {"nl_query": "q1", "generated_sql": "SELECT 1", "@search.score": 0.95},
        {"nl_query": "q2", "generated_sql": "SELECT 2", "@search.score": 0.90},
        {"nl_query": "q3", "generated_sql": "SELECT 3", "@search.score": 0.85},
    ]
    mock_vector_store.search = AsyncMock(return_value=MockResults(results_data))

    embedding = [0.1] * 1536
    examples = await prompt_manager.retrieve_few_shot_examples(embedding, top_k=5)

    assert len(examples) == 3
    assert examples[0].similarity_score == 0.95
    assert examples[1].similarity_score == 0.90
    assert examples[2].similarity_score == 0.85
    assert examples[0].nl_query == "q1"


async def test_retrieve_few_shot_examples_respects_top_k(
    prompt_manager, mock_vector_store
):
    """At most top_k examples are returned."""

    class MockResults:
        def __init__(self, data):
            self._data = data

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self._data:
                raise StopAsyncIteration
            return self._data.pop(0)

    results_data = [
        {
            "nl_query": f"q{i}",
            "generated_sql": f"SELECT {i}",
            "@search.score": 0.99 - (i * 0.02),
        }
        for i in range(7)
    ]
    mock_vector_store.search = AsyncMock(return_value=MockResults(results_data))

    embedding = [0.1] * 1536
    examples = await prompt_manager.retrieve_few_shot_examples(embedding, top_k=5)

    assert len(examples) <= 5


async def test_retrieve_few_shot_examples_vector_store_unreachable(
    prompt_manager, mock_vector_store
):
    """ConfigurationError raised when vector store is unreachable."""
    mock_vector_store.search.side_effect = Exception("Connection timeout")

    with pytest.raises(ConfigurationError, match="Failed to retrieve few-shot examples"):
        await prompt_manager.retrieve_few_shot_examples([0.1] * 1536)


async def test_retrieve_few_shot_examples_empty_store(
    prompt_manager, mock_vector_store
):
    """Empty list returned when no examples exist in vector store."""

    class MockResults:
        def __aiter__(self):
            return self

        async def __anext__(self):
            raise StopAsyncIteration

    mock_vector_store.search = AsyncMock(return_value=MockResults())

    embedding = [0.1] * 1536
    examples = await prompt_manager.retrieve_few_shot_examples(embedding)

    assert examples == []


# --- Tests for _extract_placeholders ---


def test_extract_placeholders():
    """Placeholders are correctly extracted from template content."""
    content = "Hello {{name}}, your {{item}} is ready. Ref: {{name}}"
    placeholders = PromptManager._extract_placeholders(content)

    assert placeholders == ["name", "item"]  # unique, order preserved


def test_extract_placeholders_none_found():
    """Empty list returned when no placeholders exist."""
    content = "No placeholders here."
    placeholders = PromptManager._extract_placeholders(content)

    assert placeholders == []
