"""Seed few-shot examples into Azure AI Search for retrieval-augmented generation.

Loads curated (nl_query, sql) pairs from data/few_shot_examples.json, generates
embeddings using Azure OpenAI, and uploads them to the few-shot Azure AI Search index.

Usage:
    python scripts/seed_few_shot_index.py

Requires environment variables (or .env file):
    - AZURE_OPENAI_ENDPOINT
    - AZURE_OPENAI_API_KEY
    - AZURE_OPENAI_EMBEDDING_DEPLOYMENT
    - AZURE_SEARCH_ENDPOINT
    - AZURE_SEARCH_API_KEY
    - AZURE_SEARCH_FEWSHOT_INDEX (default: "few-shot-index")
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root
project_root = Path(__file__).resolve().parent.parent
load_dotenv(project_root / ".env")


def get_env(name: str, default: str | None = None) -> str:
    """Get environment variable or exit with error."""
    value = os.environ.get(name, default)
    if value is None:
        print(f"ERROR: Required environment variable '{name}' is not set.")
        sys.exit(1)
    return value


def load_few_shot_examples() -> list[dict]:
    """Load few-shot examples from the JSON data file."""
    examples_path = project_root / "data" / "few_shot_examples.json"
    if not examples_path.exists():
        print(f"ERROR: Few-shot examples file not found: {examples_path}")
        sys.exit(1)

    with open(examples_path, "r", encoding="utf-8") as f:
        examples = json.load(f)

    print(f"Loaded {len(examples)} few-shot examples from {examples_path}")
    return examples


def create_embedding_client():
    """Create Azure OpenAI client for generating embeddings."""
    from openai import AzureOpenAI

    endpoint = get_env("AZURE_OPENAI_ENDPOINT")
    api_key = get_env("AZURE_OPENAI_API_KEY")
    api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01")

    return AzureOpenAI(
        azure_endpoint=endpoint,
        api_key=api_key,
        api_version=api_version,
    )


def generate_embeddings(client, texts: list[str], model: str) -> list[list[float]]:
    """Generate embeddings for a batch of texts."""
    print(f"Generating embeddings for {len(texts)} texts...")
    response = client.embeddings.create(input=texts, model=model)
    embeddings = [item.embedding for item in response.data]
    print(f"Generated {len(embeddings)} embeddings (dimension: {len(embeddings[0])})")
    return embeddings


def create_search_index(search_endpoint: str, api_key: str, index_name: str, vector_dimension: int):
    """Create or update the Azure AI Search index with the required schema."""
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents.indexes import SearchIndexClient
    from azure.search.documents.indexes.models import (
        HnswAlgorithmConfiguration,
        SearchableField,
        SearchField,
        SearchFieldDataType,
        SearchIndex,
        SimpleField,
        VectorSearch,
        VectorSearchProfile,
    )

    index_client = SearchIndexClient(
        endpoint=search_endpoint,
        credential=AzureKeyCredential(api_key),
    )

    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True, filterable=True),
        SearchableField(name="nl_query", type=SearchFieldDataType.String),
        SimpleField(name="sql", type=SearchFieldDataType.String),
        SearchField(
            name="embedding",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=vector_dimension,
            vector_search_profile_name="default-profile",
        ),
    ]

    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name="default-algorithm")],
        profiles=[
            VectorSearchProfile(name="default-profile", algorithm_configuration_name="default-algorithm")
        ],
    )

    index = SearchIndex(name=index_name, fields=fields, vector_search=vector_search)

    try:
        index_client.create_or_update_index(index)
        print(f"Search index '{index_name}' created/updated successfully.")
    except Exception as exc:
        print(f"WARNING: Could not create/update index: {exc}")
        print("Attempting to upload documents to existing index...")


def upload_documents(search_endpoint: str, api_key: str, index_name: str, documents: list[dict]):
    """Upload documents to the Azure AI Search index."""
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient

    client = SearchClient(
        endpoint=search_endpoint,
        index_name=index_name,
        credential=AzureKeyCredential(api_key),
    )

    # Upload in batches of 100
    batch_size = 100
    total_uploaded = 0

    for i in range(0, len(documents), batch_size):
        batch = documents[i : i + batch_size]
        result = client.upload_documents(documents=batch)
        succeeded = sum(1 for r in result if r.succeeded)
        total_uploaded += succeeded
        print(f"  Batch {i // batch_size + 1}: uploaded {succeeded}/{len(batch)} documents")

    print(f"Total documents uploaded: {total_uploaded}/{len(documents)}")


def main():
    """Main entry point for seeding the few-shot index."""
    print("=" * 60)
    print("NLP-to-SQL Few-Shot Index Seeder")
    print("=" * 60)

    # Load examples
    examples = load_few_shot_examples()

    # Configuration
    embedding_model = get_env("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-ada-002")
    search_endpoint = get_env("AZURE_SEARCH_ENDPOINT")
    search_api_key = get_env("AZURE_SEARCH_API_KEY")
    index_name = os.environ.get("AZURE_SEARCH_FEWSHOT_INDEX", "few-shot-index")

    # Create embedding client and generate embeddings
    embedding_client = create_embedding_client()
    nl_queries = [ex["nl_query"] for ex in examples]
    embeddings = generate_embeddings(embedding_client, nl_queries, embedding_model)

    # Determine vector dimension from first embedding
    vector_dimension = len(embeddings[0])

    # Create/update the search index
    print(f"\nConfiguring search index '{index_name}'...")
    create_search_index(search_endpoint, search_api_key, index_name, vector_dimension)

    # Build documents for upload
    documents = []
    for i, (example, embedding) in enumerate(zip(examples, embeddings)):
        doc = {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, example["nl_query"])),
            "nl_query": example["nl_query"],
            "sql": example["sql"],
            "embedding": embedding,
        }
        documents.append(doc)

    # Upload to index
    print(f"\nUploading {len(documents)} documents to index '{index_name}'...")
    upload_documents(search_endpoint, search_api_key, index_name, documents)

    print("\n" + "=" * 60)
    print("Seeding complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
