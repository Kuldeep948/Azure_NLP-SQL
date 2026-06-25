"""Application configuration for the NLP-to-SQL Azure Harness.

Uses pydantic-settings to load configuration from environment variables
for local development and supports Azure Key Vault for production secrets
via DefaultAzureCredential.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class AppConfig(BaseSettings):
    """Application configuration loaded from environment variables / Key Vault.

    In local development, values are read from a .env file at the project root.
    In production, secrets are retrieved from Azure Key Vault using
    DefaultAzureCredential (Managed Identity).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Azure OpenAI ---
    azure_openai_endpoint: str
    azure_openai_api_key: str | None = None
    azure_openai_primary_deployment: str = "gpt-4o"
    azure_openai_fallback_deployment: str = "gpt-4-turbo"
    azure_openai_embedding_deployment: str = "text-embedding-ada-002"
    azure_openai_api_version: str = "2024-02-01"

    # --- Azure AI Search ---
    azure_search_endpoint: str
    azure_search_api_key: str | None = None
    azure_search_cache_index: str = "semantic-cache-index"
    azure_search_fewshot_index: str = "few-shot-index"

    # --- Azure SQL Database ---
    sql_connection_string: str

    # --- Azure Blob Storage ---
    azure_blob_storage_url: str
    azure_blob_prompts_container: str = "prompts"
    azure_blob_schema_container: str = "schema"
    azure_blob_evaluation_container: str = "evaluation"
    azure_blob_feedback_container: str = "feedback"

    # --- Azure Cache for Redis ---
    redis_connection_string: str

    # --- Azure Key Vault ---
    azure_key_vault_url: str

    # --- Azure AI Language (CLU) ---
    azure_clu_endpoint: str | None = None
    azure_clu_api_key: str | None = None
    azure_clu_project_name: str | None = None
    azure_clu_deployment_name: str | None = None

    # --- Application Insights ---
    applicationinsights_connection_string: str | None = None

    @property
    def app_insights_connection_string(self) -> str | None:
        """Alias for consistency across modules."""
        return self.applicationinsights_connection_string

    # --- Application tuning ---
    row_cap: int = Field(default=1000, ge=1, le=10000)
    query_timeout_seconds: int = Field(default=30, ge=1, le=300)
    cache_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    cache_similarity_threshold: float = Field(default=0.92, ge=0.0, le=1.0)
    evaluation_accuracy_threshold: float = Field(default=0.80, ge=0.0, le=1.0)
    max_retries: int = Field(default=3, ge=1, le=10)
    initial_backoff_seconds: float = Field(default=1.0, ge=0.1, le=60.0)

    # --- Authentication ---
    auth_issuer: str | None = None
    auth_audience: str | None = None

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"


def _is_local_environment() -> bool:
    """Detect local development by absence of Managed Identity endpoint.

    When running on Azure (App Service, Functions, etc.), the environment
    variable IDENTITY_ENDPOINT is set by the platform. Its absence implies
    local development.
    """
    import os

    return os.environ.get("IDENTITY_ENDPOINT") is None


def load_config_from_key_vault(config: AppConfig) -> AppConfig:
    """Overlay secrets from Azure Key Vault onto the existing config.

    Uses DefaultAzureCredential (Managed Identity in production).
    Falls back gracefully if Key Vault is unavailable, logging a warning.
    """
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    try:
        credential = DefaultAzureCredential()
        client = SecretClient(vault_url=config.azure_key_vault_url, credential=credential)

        # Map Key Vault secret names to config fields
        secret_mappings: dict[str, str] = {
            "azure-openai-api-key": "azure_openai_api_key",
            "sql-connection-string": "sql_connection_string",
            "redis-connection-string": "redis_connection_string",
            "azure-search-api-key": "azure_search_api_key",
            "applicationinsights-connection-string": "applicationinsights_connection_string",
        }

        updates: dict[str, str] = {}
        for secret_name, field_name in secret_mappings.items():
            try:
                secret = client.get_secret(secret_name)
                if secret.value:
                    updates[field_name] = secret.value
            except Exception:
                logger.debug("Secret '%s' not found in Key Vault, skipping.", secret_name)

        if updates:
            # Create a new config instance with overlaid secrets
            config = config.model_copy(update=updates)
            logger.info("Loaded %d secret(s) from Key Vault.", len(updates))

    except Exception as exc:
        logger.warning("Unable to load secrets from Key Vault: %s", exc)

    return config


@lru_cache
def get_config() -> AppConfig:
    """Load and return the application configuration (cached singleton).

    In local environments (no Managed Identity endpoint), loads purely from
    .env / environment variables. In production, overlays secrets from
    Key Vault using DefaultAzureCredential.
    """
    config = AppConfig()  # type: ignore[call-arg]

    if not _is_local_environment():
        config = load_config_from_key_vault(config)

    return config
