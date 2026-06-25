"""Multi-Turn Conversation Manager — session context via Azure Cache for Redis.

Maintains conversation history so users can ask follow-up questions like
"Now break that down by category" or "Show me the same for last month".

Assignment Reference: Section 6.5 — Multi-Turn Conversation & Context
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Maximum conversation turns to retain per session
_MAX_HISTORY_TURNS = 10

# Session TTL in seconds (30 minutes of inactivity)
_SESSION_TTL_SECONDS = 1800


class ConversationTurn(BaseModel):
    """A single turn in a conversation (user query + system response)."""

    nl_query: str
    generated_sql: str
    tier: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ConversationSession(BaseModel):
    """Full conversation session with history of turns."""

    session_id: str
    user_id: str
    turns: list[ConversationTurn] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ConversationManager:
    """Manages multi-turn conversation state using Azure Cache for Redis.

    Stores conversation history per session, enabling follow-up queries
    that reference previous results (pronouns, "same filters", etc.).

    Args:
        redis_client: Async Redis client for session storage.
        max_turns: Maximum turns to retain per session (default 10).
        session_ttl: Session expiry in seconds after last activity (default 1800).
    """

    def __init__(
        self,
        redis_client: Any,
        max_turns: int = _MAX_HISTORY_TURNS,
        session_ttl: int = _SESSION_TTL_SECONDS,
    ) -> None:
        self._redis = redis_client
        self._max_turns = max_turns
        self._session_ttl = session_ttl

    async def get_session(self, session_id: str) -> ConversationSession | None:
        """Retrieve an existing conversation session from Redis.

        Args:
            session_id: The session identifier.

        Returns:
            ConversationSession if found and not expired, None otherwise.
        """
        try:
            key = self._make_key(session_id)
            data = await self._redis.get(key)
            if data is None:
                return None
            return ConversationSession.model_validate_json(data)
        except Exception as exc:
            logger.warning("Failed to retrieve session %s: %s", session_id, exc)
            return None

    async def add_turn(
        self,
        session_id: str,
        user_id: str,
        nl_query: str,
        generated_sql: str,
        tier: str,
    ) -> ConversationSession:
        """Add a new turn to the conversation session.

        Creates a new session if none exists. Trims history to max_turns.
        Refreshes the session TTL on every interaction.

        Args:
            session_id: The session identifier.
            user_id: The authenticated user ID.
            nl_query: The user's query for this turn.
            generated_sql: The SQL that was generated.
            tier: The query complexity tier.

        Returns:
            The updated ConversationSession.
        """
        session = await self.get_session(session_id)

        if session is None:
            session = ConversationSession(
                session_id=session_id,
                user_id=user_id,
            )

        turn = ConversationTurn(
            nl_query=nl_query,
            generated_sql=generated_sql,
            tier=tier,
        )

        session.turns.append(turn)

        # Trim to max turns (keep most recent)
        if len(session.turns) > self._max_turns:
            session.turns = session.turns[-self._max_turns:]

        session.updated_at = datetime.now(timezone.utc).isoformat()

        # Persist to Redis with TTL refresh
        try:
            key = self._make_key(session_id)
            await self._redis.set(
                key,
                session.model_dump_json(),
                ex=self._session_ttl,
            )
        except Exception as exc:
            logger.warning("Failed to persist session %s: %s", session_id, exc)

        return session

    async def get_context_for_prompt(self, session_id: str) -> str:
        """Build conversation context string for injection into the LLM prompt.

        Formats previous turns as a conversation history block that helps
        the LLM resolve references like "those customers", "same period",
        "break that down by...".

        Args:
            session_id: The session identifier.

        Returns:
            Formatted conversation history string (empty if no history).
        """
        session = await self.get_session(session_id)

        if session is None or not session.turns:
            return ""

        lines = ["## Previous Conversation Context"]
        for i, turn in enumerate(session.turns[-5:], 1):  # Last 5 turns max
            lines.append(f"Turn {i}:")
            lines.append(f"  User: {turn.nl_query}")
            lines.append(f"  SQL: {turn.generated_sql}")
            lines.append("")

        lines.append("Use the above context to resolve any references in the current question.")
        return "\n".join(lines)

    async def clear_session(self, session_id: str) -> None:
        """Delete a conversation session.

        Args:
            session_id: The session to clear.
        """
        try:
            key = self._make_key(session_id)
            await self._redis.delete(key)
        except Exception as exc:
            logger.warning("Failed to clear session %s: %s", session_id, exc)

    @staticmethod
    def _make_key(session_id: str) -> str:
        """Create a namespaced Redis key for a session.

        Args:
            session_id: The session identifier.

        Returns:
            Redis key string.
        """
        return f"conversation:{session_id}"
