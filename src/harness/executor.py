"""Query Executor for running validated SQL against Azure SQL Database.

Executes SQL queries using aioodbc with Azure Identity token authentication,
enforcing configurable timeouts and row limits. Returns structured results
with column metadata.

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5
"""

from __future__ import annotations

import asyncio
import logging
import struct
from typing import Any

from src.nlp_to_sql.exceptions import QueryExecutionError

logger = logging.getLogger(__name__)

# Maximum rows to return before truncation
MAX_ROWS = 10_000


class QueryExecutor:
    """Executes SQL queries against Azure SQL Database with timeout and token auth.

    Uses aioodbc for async database connectivity. Supports Azure AD token
    authentication via DefaultAzureCredential for production environments,
    or connection-string-based auth for local development.

    Args:
        connection_string: ODBC connection string for Azure SQL Database.
        timeout_seconds: Maximum seconds to wait for query execution. Defaults to 30.
    """

    def __init__(self, connection_string: str, timeout_seconds: int = 30) -> None:
        self._connection_string = connection_string
        self._timeout_seconds = timeout_seconds
        self._token_credential: Any = None

    async def _get_access_token(self) -> bytes:
        """Obtain an Azure AD access token for SQL Database authentication.

        Uses DefaultAzureCredential which supports Managed Identity in production
        and developer credentials locally.

        Returns:
            Token bytes formatted for ODBC SQL_COPT_SS_ACCESS_TOKEN attribute.
        """
        if self._token_credential is None:
            from azure.identity.aio import DefaultAzureCredential
            self._token_credential = DefaultAzureCredential()

        token = await self._token_credential.get_token(
            "https://database.windows.net/.default"
        )
        # Pack token for ODBC driver: UTF-16-LE encoded with length prefix
        token_bytes = token.token.encode("UTF-16-LE")
        token_struct = struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)
        return token_struct

    def _uses_token_auth(self) -> bool:
        """Determine if the connection string uses Azure AD token authentication."""
        conn_lower = self._connection_string.lower()
        return "authentication=activedirectorydefault" in conn_lower

    async def execute(self, sql: str) -> dict:
        """Execute a SQL query and return structured results.

        Args:
            sql: The validated SQL query to execute.

        Returns:
            Dictionary with keys:
                - columns: list of dicts with 'name' and 'data_type'
                - rows: list of row dicts (column_name -> value)
                - row_count: number of rows returned
                - truncated: True if results exceeded MAX_ROWS (10000)

        Raises:
            QueryExecutionError: On connection failure, timeout, or SQL runtime error.
        """
        try:
            return await asyncio.wait_for(
                self._execute_internal(sql),
                timeout=self._timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.error(
                "Query execution timed out after %d seconds", self._timeout_seconds
            )
            raise QueryExecutionError(
                f"Query execution timed out after {self._timeout_seconds} seconds",
                detail="Consider simplifying the query or increasing the timeout.",
            )
        except QueryExecutionError:
            raise
        except Exception as exc:
            logger.error("Query execution failed: %s", exc)
            raise QueryExecutionError(
                "Query execution failed",
                detail=str(exc),
            ) from exc

    async def _execute_internal(self, sql: str) -> dict:
        """Internal execution logic without timeout wrapper.

        Connects to the database, executes the query, and fetches results
        up to MAX_ROWS + 1 to detect truncation.
        """
        import aioodbc

        connect_kwargs: dict[str, Any] = {"dsn": self._connection_string}

        # If using Azure AD token auth, obtain token and set connection attribute
        if self._uses_token_auth():
            try:
                token_struct = await self._get_access_token()
                # SQL_COPT_SS_ACCESS_TOKEN = 1256
                connect_kwargs["attrs_before"] = {1256: token_struct}
                # Remove Authentication keyword from DSN since we're using token directly
                import re
                connect_kwargs["dsn"] = re.sub(
                    r"Authentication=[^;]*;?",
                    "",
                    self._connection_string,
                    flags=re.IGNORECASE,
                )
            except Exception as exc:
                logger.error("Failed to obtain Azure AD token: %s", exc)
                raise QueryExecutionError(
                    "Database authentication failed",
                    detail=f"Unable to obtain Azure AD access token: {exc}",
                ) from exc

        try:
            async with aioodbc.connect(**connect_kwargs) as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(sql)

                    # Get column metadata from cursor description
                    columns = self._extract_columns(cursor.description)

                    # Fetch rows up to MAX_ROWS + 1 to detect truncation
                    rows_raw = await cursor.fetchmany(MAX_ROWS + 1)

                    truncated = len(rows_raw) > MAX_ROWS
                    if truncated:
                        rows_raw = rows_raw[:MAX_ROWS]

                    # Convert rows to list of dicts
                    column_names = [col["name"] for col in columns]
                    rows = [
                        dict(zip(column_names, row))
                        for row in rows_raw
                    ]

                    return {
                        "columns": columns,
                        "rows": rows,
                        "row_count": len(rows),
                        "truncated": truncated,
                    }

        except QueryExecutionError:
            raise
        except Exception as exc:
            logger.error("Database query execution error: %s", exc)
            raise QueryExecutionError(
                "Database query execution failed",
                detail=str(exc),
            ) from exc

    @staticmethod
    def _extract_columns(description: Any) -> list[dict[str, str]]:
        """Extract column metadata from a cursor description.

        Args:
            description: The cursor.description tuple from pyodbc/aioodbc.

        Returns:
            List of dicts with 'name' and 'data_type' for each column.
        """
        if not description:
            return []

        # ODBC type code to friendly name mapping
        type_map: dict[type, str] = {
            int: "int",
            float: "float",
            str: "str",
            bool: "bool",
            bytes: "bytes",
        }

        columns: list[dict[str, str]] = []
        for col_desc in description:
            name = col_desc[0]
            type_code = col_desc[1]

            # Attempt to get a friendly type name
            data_type = type_map.get(type_code, type_code.__name__ if hasattr(type_code, "__name__") else str(type_code))

            columns.append({"name": name, "data_type": data_type})

        return columns

    async def close(self) -> None:
        """Clean up resources (close token credential if needed)."""
        if self._token_credential is not None:
            await self._token_credential.close()
            self._token_credential = None
