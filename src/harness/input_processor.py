"""Input Processor for intent classification, ambiguity detection, and entity resolution.

Classifies NL queries into complexity tiers using Azure CLU (primary) with
keyword-heuristic fallback. Resolves unrecognized entity references against
schema metadata using fuzzy matching.

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7
"""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher
from enum import Enum

from pydantic import BaseModel

from src.schema.metadata import SchemaMetadata

logger = logging.getLogger(__name__)

# Attempt to import CLU client type; allow None when not installed
try:
    from azure.ai.language.conversations import ConversationAnalysisClient
except ImportError:  # pragma: no cover
    ConversationAnalysisClient = None  # type: ignore[misc, assignment]


class Tier(str, Enum):
    """Query complexity tier classification."""

    SIMPLE = "simple"
    FILTERED = "filtered"
    JOIN = "join"
    ADVANCED = "advanced"
    AMBIGUOUS = "ambiguous"


class ClassificationResult(BaseModel):
    """Result of NL query classification."""

    tier: Tier
    confidence: float
    resolved_entities: dict[str, str]  # original_term -> schema_term
    clarification_prompt: str | None = None


# ---------------------------------------------------------------------------
# Keyword pattern definitions for heuristic classification
# ---------------------------------------------------------------------------

# Advanced patterns: window functions, CTEs, subqueries
_ADVANCED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(rank|dense_rank|row_number|ntile|lead|lag)\b", re.IGNORECASE),
    re.compile(r"\bover\s*\(", re.IGNORECASE),
    re.compile(r"\bwith\s+\w+\s+as\s*\(", re.IGNORECASE),
    re.compile(r"\b(partition\s+by)\b", re.IGNORECASE),
    re.compile(r"\b(percentile|cumulative|running\s+total|moving\s+average)\b", re.IGNORECASE),
    re.compile(r"\b(subquery|nested|recursive)\b", re.IGNORECASE),
    re.compile(r"\b(pivot|unpivot|rollup|cube)\b", re.IGNORECASE),
]

# Join patterns: explicit join keywords or multi-table references
_JOIN_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bjoin\b", re.IGNORECASE),
    re.compile(r"\b(inner|left|right|full|cross)\s+join\b", re.IGNORECASE),
    re.compile(r"\b(combine|merge|link|relate|connect)\b.*\b(table|data)\b", re.IGNORECASE),
    re.compile(r"\b(along\s+with|together\s+with|combined\s+with)\b", re.IGNORECASE),
    re.compile(r"\b(from\s+\w+\s+and\s+\w+)\b", re.IGNORECASE),
    re.compile(r"\b(customers?\s+.*\s+orders?|orders?\s+.*\s+products?)\b", re.IGNORECASE),
]

# Filtered patterns: aggregation, WHERE conditions, GROUP BY
_FILTERED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(where|filter|greater|less|between|more\s+than|less\s+than)\b", re.IGNORECASE),
    re.compile(r"\b(total|sum|count|average|avg|min|max|group)\b", re.IGNORECASE),
    re.compile(r"\b(top\s+\d+|highest|lowest|most|least|best|worst)\b", re.IGNORECASE),
    re.compile(r"\b(last|past|since|before|after|during|this)\s+(week|month|year|quarter|day)\b", re.IGNORECASE),
    re.compile(r"\b(greater|less|equal|above|below|over|under)\s+(than)?\s*\d+", re.IGNORECASE),
    re.compile(r"\b(how\s+many|how\s+much)\b", re.IGNORECASE),
]

# Simple patterns: basic lookups, list/show
_SIMPLE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(show|list|get|display|what|give\s+me|fetch)\b", re.IGNORECASE),
    re.compile(r"\b(all|every)\b", re.IGNORECASE),
    re.compile(r"\b(select|find)\b", re.IGNORECASE),
]

# Common English stop words to skip during entity resolution
_STOP_WORDS: set[str] = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "up", "about", "into", "through", "during", "before", "after",
    "above", "below", "between", "out", "off", "over", "under",
    "again", "further", "then", "once", "here", "there", "when",
    "where", "why", "how", "all", "each", "every", "both", "few",
    "more", "most", "other", "some", "such", "no", "nor", "not",
    "only", "own", "same", "so", "than", "too", "very", "just",
    "because", "as", "until", "while", "although", "though",
    "and", "but", "or", "if", "that", "which", "who", "whom",
    "this", "these", "those", "am", "what", "me", "my", "i",
    "show", "list", "get", "give", "find", "fetch", "display",
    "many", "much", "their", "its",
}

# Fuzzy match threshold for entity resolution
_ENTITY_MATCH_THRESHOLD: float = 0.7


class InputProcessor:
    """Classifies NL queries and resolves entities against schema metadata.

    Uses Azure CLU as the primary classifier when available, falling back to
    keyword-based heuristics. Entity resolution uses fuzzy matching (difflib)
    against known table and column names from the schema.

    Args:
        clu_client: Optional Azure CLU client. If None, heuristics are used directly.
        schema: The current schema metadata containing table/column definitions.
        clu_project_name: CLU project name for intent classification.
        clu_deployment_name: CLU deployment name.
    """

    def __init__(
        self,
        clu_client: ConversationAnalysisClient | None,
        schema: SchemaMetadata,
        clu_project_name: str = "nlp-to-sql-intents",
        clu_deployment_name: str = "production",
    ) -> None:
        self._clu_client = clu_client
        self._schema = schema
        self._clu_project_name = clu_project_name
        self._clu_deployment_name = clu_deployment_name

        # Build a flat set of schema terms for entity resolution
        self._schema_terms: set[str] = self._build_schema_terms()

    def _build_schema_terms(self) -> set[str]:
        """Extract all table and column names from schema metadata."""
        terms: set[str] = set()
        for table_name, table_schema in self._schema.tables.items():
            terms.add(table_name.lower())
            for col in table_schema.columns:
                terms.add(col.name.lower())
        return terms

    async def classify(self, nl_query: str) -> ClassificationResult:
        """Classify the NL query into a complexity tier.

        Attempts CLU classification first (if client available), then falls
        back to keyword heuristics. Resolves entities via fuzzy matching.
        Returns Ambiguous tier if confidence is below 0.6.

        Args:
            nl_query: The natural language question to classify.

        Returns:
            ClassificationResult with tier, confidence, resolved entities,
            and optional clarification prompt.
        """
        # Resolve entities first
        resolved_entities = self._resolve_entities(nl_query)

        # Attempt CLU classification
        tier: Tier | None = None
        confidence: float = 0.0

        if self._clu_client is not None:
            try:
                tier, confidence = await self._classify_with_clu(nl_query)
            except Exception as exc:
                logger.warning(
                    "CLU classification failed, falling back to heuristics: %s", exc
                )
                tier = None

        # Fallback to keyword heuristics if CLU unavailable or failed
        if tier is None:
            tier, confidence = self._keyword_heuristics(nl_query)

        # Low confidence → Ambiguous (Requirement 3.3)
        if confidence < 0.6:
            tier = Tier.AMBIGUOUS

        # Check for unresolved entities that might indicate ambiguity
        clarification_prompt: str | None = None
        if tier == Tier.AMBIGUOUS:
            clarification_prompt = self._generate_clarification(nl_query, resolved_entities)

        return ClassificationResult(
            tier=tier,
            confidence=confidence,
            resolved_entities=resolved_entities,
            clarification_prompt=clarification_prompt,
        )

    async def _classify_with_clu(self, nl_query: str) -> tuple[Tier, float]:
        """Classify using Azure CLU service.

        Args:
            nl_query: The query text to classify.

        Returns:
            Tuple of (tier, confidence) from CLU response.

        Raises:
            Exception: If CLU is unreachable or returns an error.
        """
        task = {
            "kind": "Conversation",
            "analysisInput": {
                "conversationItem": {
                    "id": "1",
                    "participantId": "user",
                    "text": nl_query,
                }
            },
            "parameters": {
                "projectName": self._clu_project_name,
                "deploymentName": self._clu_deployment_name,
            },
        }

        # CLU client call (synchronous SDK wrapped)
        response = self._clu_client.analyze_conversation(task=task)  # type: ignore[union-attr]

        # Extract the top intent
        prediction = response["result"]["prediction"]
        top_intent = prediction["topIntent"]
        intents = prediction.get("intents", [])

        # Find confidence for top intent
        confidence = 0.0
        for intent in intents:
            if intent["category"] == top_intent:
                confidence = intent["confidenceScore"]
                break

        # Map CLU intent names to Tier enum
        tier = self._map_clu_intent_to_tier(top_intent)

        return tier, confidence

    @staticmethod
    def _map_clu_intent_to_tier(intent_name: str) -> Tier:
        """Map a CLU intent name to the corresponding Tier enum value."""
        mapping: dict[str, Tier] = {
            "simple": Tier.SIMPLE,
            "Simple": Tier.SIMPLE,
            "filtered": Tier.FILTERED,
            "Filtered": Tier.FILTERED,
            "join": Tier.JOIN,
            "Join": Tier.JOIN,
            "advanced": Tier.ADVANCED,
            "Advanced": Tier.ADVANCED,
            "ambiguous": Tier.AMBIGUOUS,
            "Ambiguous": Tier.AMBIGUOUS,
            "None": Tier.AMBIGUOUS,
        }
        return mapping.get(intent_name, Tier.AMBIGUOUS)

    def _keyword_heuristics(self, nl_query: str) -> tuple[Tier, float]:
        """Rule-based tier assignment using keyword pattern matching.

        Scores patterns from most complex (Advanced) to simplest (Simple).
        Confidence is derived from the number of matching patterns relative
        to total patterns in that category.

        Args:
            nl_query: The query text to classify.

        Returns:
            Tuple of (tier, confidence). Confidence below 0.6 will cause
            the caller to override tier to Ambiguous.
        """
        query_lower = nl_query.lower()

        # Check Advanced patterns
        advanced_matches = sum(
            1 for p in _ADVANCED_PATTERNS if p.search(query_lower)
        )
        if advanced_matches > 0:
            confidence = min(0.6 + (advanced_matches / len(_ADVANCED_PATTERNS)) * 0.4, 1.0)
            return Tier.ADVANCED, confidence

        # Check Join patterns
        join_matches = sum(1 for p in _JOIN_PATTERNS if p.search(query_lower))
        if join_matches > 0:
            confidence = min(0.55 + (join_matches / len(_JOIN_PATTERNS)) * 0.45, 1.0)
            return Tier.JOIN, confidence

        # Check Filtered patterns
        filtered_matches = sum(
            1 for p in _FILTERED_PATTERNS if p.search(query_lower)
        )
        if filtered_matches > 0:
            confidence = min(0.5 + (filtered_matches / len(_FILTERED_PATTERNS)) * 0.5, 1.0)
            return Tier.FILTERED, confidence

        # Check Simple patterns
        simple_matches = sum(1 for p in _SIMPLE_PATTERNS if p.search(query_lower))
        if simple_matches > 0:
            confidence = min(0.5 + (simple_matches / len(_SIMPLE_PATTERNS)) * 0.5, 1.0)
            return Tier.SIMPLE, confidence

        # No patterns matched → low confidence
        return Tier.AMBIGUOUS, 0.3

    def _resolve_entities(self, nl_query: str) -> dict[str, str]:
        """Fuzzy-match unrecognized terms against schema metadata.

        Tokenizes the query and checks each non-stop-word token against
        known table and column names using SequenceMatcher. Matches with
        a ratio >= 0.7 are included.

        Args:
            nl_query: The query text to scan for entity references.

        Returns:
            Dictionary mapping original terms to matched schema terms.
            Only includes terms that matched above threshold.
        """
        resolved: dict[str, str] = {}

        # Tokenize: split on non-alphanumeric, keep underscores
        tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", nl_query)

        for token in tokens:
            token_lower = token.lower()

            # Skip stop words and very short tokens
            if token_lower in _STOP_WORDS or len(token_lower) < 3:
                continue

            # Skip if it already exactly matches a schema term
            if token_lower in self._schema_terms:
                continue

            # Fuzzy match against schema terms
            best_match: str | None = None
            best_score: float = 0.0

            for schema_term in self._schema_terms:
                score = SequenceMatcher(
                    None, token_lower, schema_term
                ).ratio()
                if score > best_score:
                    best_score = score
                    best_match = schema_term

            if best_match is not None and best_score >= _ENTITY_MATCH_THRESHOLD:
                resolved[token] = best_match

        return resolved

    def _generate_clarification(
        self, nl_query: str, resolved_entities: dict[str, str]
    ) -> str:
        """Generate a clarification prompt for ambiguous queries.

        Args:
            nl_query: The original query.
            resolved_entities: Any entities that were resolved.

        Returns:
            A user-friendly clarification prompt.
        """
        if not nl_query.strip():
            return "Could you please provide a more specific question about your data?"

        # Build a clarification message
        available_tables = ", ".join(sorted(self._schema.tables.keys()))
        prompt = (
            f"I wasn't able to determine exactly what you're looking for. "
            f"Could you please rephrase your question? "
            f"Available data includes: {available_tables}."
        )

        if resolved_entities:
            resolved_info = ", ".join(
                f'"{orig}" → "{matched}"'
                for orig, matched in resolved_entities.items()
            )
            prompt += f" I matched these terms: {resolved_info}."

        return prompt
