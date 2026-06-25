"""Role-based schema filtering for the NLP-to-SQL Azure Harness.

Filters SchemaMetadata to only include tables the user's roles permit access to,
ensuring the LLM prompt only contains schema information the user is authorized to query.

Requirements: 6.6
"""

from __future__ import annotations

from src.schema.metadata import SchemaMetadata, TableSchema


def filter_schema_by_roles(
    schema: SchemaMetadata,
    user_roles: list[str],
    table_permissions: dict[str, list[str]],
) -> SchemaMetadata:
    """Filter schema to only include tables the user's roles permit access to.

    If table_permissions is empty, return full schema (permissive default).
    Otherwise, collects all tables that any of the user's roles grants access to
    and returns a new SchemaMetadata containing only those tables.

    Args:
        schema: The full SchemaMetadata with all table definitions.
        user_roles: List of role names assigned to the authenticated user.
        table_permissions: Mapping of role name to list of permitted table names.

    Returns:
        A new SchemaMetadata instance containing only permitted tables.
    """
    if not table_permissions:
        return schema

    # Collect all tables the user can access based on their roles
    permitted_tables: set[str] = set()
    for role in user_roles:
        role_tables = table_permissions.get(role, [])
        permitted_tables.update(t.lower() for t in role_tables)

    # If no roles match any permissions, return empty schema
    if not permitted_tables:
        return SchemaMetadata(tables={})

    # Filter tables
    filtered_tables: dict[str, TableSchema] = {}
    for table_name, table_schema in schema.tables.items():
        if table_name.lower() in permitted_tables:
            filtered_tables[table_name] = table_schema

    return SchemaMetadata(tables=filtered_tables)
