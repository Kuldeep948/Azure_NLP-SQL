"""Prompt Manager for loading, caching, versioning, and rendering prompt templates.

Supports:
- Loading templates from Azure Blob Storage at startup with in-memory caching
- Version-based template retrieval (specific version or latest)
- Template rendering with placeholder substitution (Schema_Metadata, Few_Shot_Examples, NL_Query)
- Few-shot example retrieval from Azure AI Search vector store ranked by cosine similarity

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9
"""

from __future__ import annotations

import json
import logging
from typing import Any

from azure.search.documents.aio import SearchClient
from azure.search.documents.models import VectorizedQuery
from azure.storage.blob.aio import BlobServiceClient

from src.nlp_to_sql.exceptions import ConfigurationError
from src.nlp_to_sql.models import FewShotExample, PromptTemplate
from src.schema.metadata import SchemaMetadata

logger = logging.getLogger(__name__)


class PromptManager:
    """Manages prompt templates lifecycle: loading, caching, versioning, and rendering.

    Args:
        blob_client: An async BlobServiceClient for accessing template storage.
        vector_store: An async SearchClient for the few-shot examples index.
        embedding_client: Azure OpenAI embedding client for query embedding generation.
        container_name: Blob container holding prompt templates. Defaults to "prompts".
    """

    def __init__(
        self,
        blob_client: BlobServiceClient,
        vector_store: SearchClient,
        embedding_client: Any,
        container_name: str = "prompts",
    ) -> None:
        self._templates: dict[str, PromptTemplate] = {}
        self._blob_client = blob_client
        self._vector_store = vector_store
        self._embedding_client = embedding_client
        self._container_name = container_name
        self._latest_version: str | None = None

    async def load_templates(self) -> None:
        """Load all templates from Blob Storage at startup and cache in memory.

        Reads a metadata.json file from the configured container to discover
        available template versions. Each template blob is downloaded and parsed
        into a PromptTemplate model.

        Raises:
            ConfigurationError: If Blob Storage is unreachable, metadata.json is
                missing or unparseable, or no template is marked as latest.
        """
        try:
            container_client = self._blob_client.get_container_client(
                self._container_name
            )

            # Load metadata index to discover templates
            metadata_blob = container_client.get_blob_client("metadata.json")
            download = await metadata_blob.download_blob()
            content = await download.readall()
            metadata = json.loads(content)

        except Exception as exc:
            msg = f"Blob Storage unreachable or metadata.json missing: {exc}"
            logger.error(msg)
            raise ConfigurationError(msg) from exc

        templates_list = metadata.get("templates", [])
        if not templates_list:
            msg = "No templates defined in metadata.json"
            logger.error(msg)
            raise ConfigurationError(msg)

        latest_found = False

        for entry in templates_list:
            version = entry.get("version")
            blob_name = entry.get("blob_name")
            is_latest = entry.get("is_latest", False)

            if not version or not blob_name:
                logger.warning(
                    "Skipping malformed template entry: %s", entry
                )
                continue

            try:
                template_blob = container_client.get_blob_client(blob_name)
                download = await template_blob.download_blob()
                template_content = (await download.readall()).decode("utf-8")
            except Exception as exc:
                logger.error(
                    "Failed to load template version '%s' from blob '%s': %s",
                    version,
                    blob_name,
                    exc,
                )
                raise ConfigurationError(
                    f"Failed to load template version '{version}': {exc}"
                ) from exc

            # Extract placeholders from template content (format: {{placeholder_name}})
            placeholders = self._extract_placeholders(template_content)

            template = PromptTemplate(
                id=f"template-{version}",
                version=version,
                content=template_content,
                placeholders=placeholders,
                is_latest=is_latest,
                created_at=entry.get(
                    "created_at", "2024-01-01T00:00:00Z"
                ),
            )

            self._templates[version] = template

            if is_latest:
                self._latest_version = version
                latest_found = True

        if not latest_found:
            msg = "No template is marked as latest in Blob Storage"
            logger.error(msg)
            raise ConfigurationError(msg)

        logger.info(
            "Loaded %d template(s). Latest version: %s",
            len(self._templates),
            self._latest_version,
        )

    async def get_template(self, version: str | None = None) -> PromptTemplate:
        """Return the specified template version, or the latest if not specified.

        Args:
            version: Specific template version to retrieve. If None, returns latest.

        Returns:
            The requested PromptTemplate.

        Raises:
            ConfigurationError: If the requested version does not exist or no
                latest template is configured.
        """
        if version is not None:
            template = self._templates.get(version)
            if template is None:
                raise ConfigurationError(
                    f"Template version '{version}' not found"
                )
            return template

        # Return latest
        if self._latest_version is None:
            raise ConfigurationError(
                "No latest template is configured"
            )

        template = self._templates.get(self._latest_version)
        if template is None:
            raise ConfigurationError(
                "No latest template is configured"
            )
        return template

    async def render(
        self,
        template: PromptTemplate,
        schema: SchemaMetadata,
        nl_query: str,
        few_shot_examples: list[FewShotExample],
    ) -> str:
        """Substitute placeholders in the template with provided values.

        Expected placeholders:
        - {{schema}}: Serialized schema metadata
        - {{few_shot_examples}}: Formatted few-shot examples
        - {{nl_query}}: The user's natural language query

        Args:
            template: The PromptTemplate to render.
            schema: Schema metadata to inject.
            nl_query: The natural language query to inject.
            few_shot_examples: Few-shot examples to inject.

        Returns:
            The fully rendered prompt string with all placeholders substituted.

        Raises:
            ConfigurationError: If a required placeholder is absent from the
                template definition, identifying the missing placeholder.
        """
        # Define required placeholders and their rendered values
        required_placeholders = {
            "schema": self._format_schema(schema),
            "few_shot_examples": self._format_few_shot_examples(few_shot_examples),
            "nl_query": nl_query,
        }

        # Verify all required placeholders exist in the template
        for placeholder in required_placeholders:
            if placeholder not in template.placeholders:
                raise ConfigurationError(
                    f"Required placeholder '{{{{{placeholder}}}}}' is absent "
                    f"from template '{template.version}'"
                )

        # Perform substitution
        rendered = template.content
        for placeholder, value in required_placeholders.items():
            rendered = rendered.replace(f"{{{{{placeholder}}}}}", value)

        return rendered

    async def retrieve_few_shot_examples(
        self, query_embedding: list[float], top_k: int = 5
    ) -> list[FewShotExample]:
        """Retrieve up to top_k few-shot examples ranked by cosine similarity.

        Uses Azure AI Search vector search to find the most similar examples
        to the given query embedding.

        Args:
            query_embedding: The embedding vector of the user's NL query.
            top_k: Maximum number of examples to retrieve. Defaults to 5.

        Returns:
            A list of FewShotExample instances ordered by descending cosine
            similarity, containing at most top_k items.

        Raises:
            ConfigurationError: If the vector store is unreachable.
        """
        try:
            vector_query = VectorizedQuery(
                vector=query_embedding,
                k_nearest_neighbors=top_k,
                fields="embedding",
            )

            results = await self._vector_store.search(
                search_text=None,
                vector_queries=[vector_query],
                top=top_k,
            )

            examples: list[FewShotExample] = []
            async for result in results:
                example = FewShotExample(
                    nl_query=result["nl_query"],
                    sql=result["generated_sql"],
                    similarity_score=result["@search.score"],
                )
                examples.append(example)

            # Sort by descending similarity (should already be sorted by search)
            examples.sort(key=lambda e: e.similarity_score, reverse=True)

            return examples[:top_k]

        except Exception as exc:
            msg = f"Failed to retrieve few-shot examples from vector store: {exc}"
            logger.error(msg)
            raise ConfigurationError(msg) from exc

    @staticmethod
    def _extract_placeholders(content: str) -> list[str]:
        """Extract placeholder names from template content.

        Placeholders are in the format {{placeholder_name}}.

        Args:
            content: The raw template string.

        Returns:
            A list of unique placeholder names found in the template.
        """
        import re

        pattern = r"\{\{(\w+)\}\}"
        matches = re.findall(pattern, content)
        # Return unique placeholders preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for match in matches:
            if match not in seen:
                seen.add(match)
                unique.append(match)
        return unique

    @staticmethod
    def _format_schema(schema: SchemaMetadata) -> str:
        """Format schema metadata into a readable string for prompt injection.

        Args:
            schema: The SchemaMetadata to format.

        Returns:
            A formatted string representation of the schema.
        """
        lines: list[str] = []
        for table_name, table in schema.tables.items():
            columns_str = ", ".join(
                f"{col.name} ({col.data_type}{'?' if col.nullable else ''})"
                for col in table.columns
            )
            lines.append(f"Table: {table_name} — Columns: [{columns_str}]")

            if table.primary_keys:
                lines.append(f"  Primary Keys: {', '.join(table.primary_keys)}")

            if table.foreign_keys:
                fk_strs = [
                    f"{fk.column} -> {fk.references_table}.{fk.references_column}"
                    for fk in table.foreign_keys
                ]
                lines.append(f"  Foreign Keys: {', '.join(fk_strs)}")

        return "\n".join(lines)

    @staticmethod
    def _format_few_shot_examples(examples: list[FewShotExample]) -> str:
        """Format few-shot examples into a readable string for prompt injection.

        Args:
            examples: The list of FewShotExample instances.

        Returns:
            A formatted string with numbered NL→SQL pairs.
        """
        if not examples:
            return "No examples available."

        lines: list[str] = []
        for i, ex in enumerate(examples, 1):
            lines.append(f"Example {i}:")
            lines.append(f"  Question: {ex.nl_query}")
            lines.append(f"  SQL: {ex.sql}")
            lines.append("")

        return "\n".join(lines).rstrip()
