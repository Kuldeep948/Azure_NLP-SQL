"""Observability Layer — structured logging, distributed tracing, and metrics.

Provides Application Insights integration for the NLP-to-SQL pipeline with
PII redaction on all emitted telemetry. Works without App Insights connection
(logs to console in local development mode).
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# PII patterns for redaction
_EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
)
_PHONE_PATTERN = re.compile(
    r"(\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b"
)
_NATIONAL_ID_PATTERN = re.compile(
    r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b"  # SSN-like pattern (XXX-XX-XXXX)
)
_BEARER_TOKEN_PATTERN = re.compile(
    r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE
)
_SECRET_PATTERN = re.compile(
    r"(?:api[_-]?key|secret|password|token|credential)[\s]*[=:]\s*['\"]?[\w\-./+=]{8,}['\"]?",
    re.IGNORECASE,
)

REDACTED = "[REDACTED]"


@dataclass
class SpanContext:
    """Context for a distributed trace span.

    Attributes:
        trace_id: The distributed trace identifier.
        span_id: Unique identifier for this span within the trace.
        operation_name: Human-readable name of the operation being traced.
        start_time: ISO-formatted UTC timestamp when the span began.
    """

    trace_id: str
    span_id: str
    operation_name: str
    start_time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ObservabilityLayer:
    """Centralized observability for the NLP-to-SQL Azure Harness.

    Integrates with Azure Application Insights for structured logging,
    distributed tracing, and custom metrics. Falls back to standard Python
    logging when App Insights is unavailable (local dev mode).

    Args:
        connection_string: Application Insights connection string.
            If None, operates in local-dev mode (console logging only).
    """

    def __init__(self, connection_string: str | None = None) -> None:
        """Initialize the observability layer.

        Args:
            connection_string: Application Insights connection string.
                If None, uses logging-based fallback for local development.
        """
        self._connection_string = connection_string
        self._exporter: Any = None
        self._metrics_client: Any = None
        self._logger = logging.getLogger("nlp_to_sql.observability")

        # Configure console handler for local dev if not already configured
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
            )
            self._logger.addHandler(handler)
            self._logger.setLevel(logging.DEBUG)

        if connection_string:
            self._init_app_insights(connection_string)
        else:
            self._logger.info(
                "ObservabilityLayer initialized in local-dev mode (no App Insights)"
            )

    def _init_app_insights(self, connection_string: str) -> None:
        """Initialize Application Insights integration.

        Attempts OpenTelemetry first, falls back to OpenCensus, and finally
        to pure logging if neither SDK is available.

        Args:
            connection_string: Application Insights connection string.
        """
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter

            exporter = AzureMonitorTraceExporter(connection_string=connection_string)
            provider = TracerProvider()
            provider.add_span_processor(BatchSpanProcessor(exporter))
            trace.set_tracer_provider(provider)
            self._exporter = exporter
            self._logger.info("Application Insights initialized with OpenTelemetry")
        except ImportError:
            try:
                from opencensus.ext.azure.trace_exporter import AzureExporter
                from opencensus.ext.azure.log_exporter import AzureLogHandler

                self._exporter = AzureExporter(connection_string=connection_string)
                handler = AzureLogHandler(connection_string=connection_string)
                self._logger.addHandler(handler)
                self._logger.info("Application Insights initialized with OpenCensus")
            except ImportError:
                self._logger.warning(
                    "Neither opentelemetry nor opencensus available. "
                    "Using logging-based fallback for observability."
                )

    def log_event(
        self,
        event_type: str,
        trace_id: str,
        span_id: str = "",
        **kwargs: Any,
    ) -> None:
        """Emit a structured JSON log event with PII redaction.

        All string values in kwargs are passed through redact_sensitive()
        before being logged.

        Args:
            event_type: Type of event (e.g., "query_received", "cache_hit").
            trace_id: Distributed trace identifier.
            span_id: Span identifier within the trace.
            **kwargs: Additional event properties (strings are redacted).
        """
        # Redact sensitive data from all string values
        redacted_kwargs: dict[str, Any] = {}
        for key, value in kwargs.items():
            if isinstance(value, str):
                redacted_kwargs[key] = self.redact_sensitive(value)
            else:
                redacted_kwargs[key] = value

        event = {
            "event_type": event_type,
            "trace_id": trace_id,
            "span_id": span_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **redacted_kwargs,
        }

        self._logger.info(json.dumps(event, default=str))

    def record_metric(
        self,
        metric_name: str,
        value: float,
        dimensions: dict[str, str] | None = None,
    ) -> None:
        """Record a custom metric to Application Insights (or log locally).

        Args:
            metric_name: Name of the metric (e.g., "cache_hit_rate", "query_latency_ms").
            value: Numeric metric value.
            dimensions: Optional key-value pairs for metric dimensions/tags.
        """
        metric_data = {
            "metric_name": metric_name,
            "value": value,
            "dimensions": dimensions or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._logger.info("METRIC: %s", json.dumps(metric_data, default=str))

        # Attempt to emit via OpenTelemetry metrics if available
        try:
            from opentelemetry import metrics

            meter = metrics.get_meter("nlp_to_sql")
            gauge = meter.create_gauge(metric_name)
            gauge.set(value, attributes=dimensions or {})
        except (ImportError, Exception):  # noqa: BLE001
            pass  # Fallback already logged above

    def start_span(
        self,
        operation_name: str,
        trace_id: str | None = None,
    ) -> SpanContext:
        """Begin a new distributed trace span.

        Args:
            operation_name: Name of the operation being traced.
            trace_id: Optional existing trace ID to continue a trace.
                Generates a new UUID if None.

        Returns:
            SpanContext with trace_id, span_id, operation_name, and start_time.
        """
        resolved_trace_id = trace_id or uuid.uuid4().hex
        span_id = uuid.uuid4().hex[:16]

        span_context = SpanContext(
            trace_id=resolved_trace_id,
            span_id=span_id,
            operation_name=operation_name,
            start_time=datetime.now(timezone.utc).isoformat(),
        )

        self._logger.debug(
            "Span started: operation=%s, trace_id=%s, span_id=%s",
            operation_name,
            resolved_trace_id,
            span_id,
        )

        return span_context

    def redact_sensitive(self, text: str) -> str:
        """Replace emails, phones, national IDs, bearer tokens, and secret values.

        Applies pattern matching in a specific order to avoid partial matches:
        1. Bearer tokens (longest patterns first)
        2. Secret/credential key-value pairs
        3. Email addresses
        4. National IDs (SSN-like patterns)
        5. Phone numbers

        Args:
            text: Input text potentially containing sensitive information.

        Returns:
            Text with all detected PII/secrets replaced by "[REDACTED]".
        """
        if not text:
            return text

        redacted = text
        redacted = _BEARER_TOKEN_PATTERN.sub(REDACTED, redacted)
        redacted = _SECRET_PATTERN.sub(REDACTED, redacted)
        redacted = _EMAIL_PATTERN.sub(REDACTED, redacted)
        redacted = _NATIONAL_ID_PATTERN.sub(REDACTED, redacted)
        redacted = _PHONE_PATTERN.sub(REDACTED, redacted)

        return redacted
