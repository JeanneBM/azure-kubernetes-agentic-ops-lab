"""Explicit tracing, W3C handoff and an allowlist of metadata safe to export.

Do not pass prompts, logs, tool arguments, credentials or exception messages.
Application code should translate failures into bounded error categories.
"""
from contextlib import contextmanager
from typing import Iterator, Mapping

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.trace import Span, SpanKind, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

# lab.* attributes are a local contract, not claims of GenAI semantic compliance.
_ALLOWED = frozenset({
    "lab.task.id", "lab.scenario", "lab.mode", "lab.outcome",
    "lab.policy.decision", "lab.policy.version", "lab.action", "lab.error.type",
    "lab.model.name", "lab.tokens.input", "lab.tokens.output", "lab.attempt",
})
_PROPAGATOR = TraceContextTextMapPropagator()


def configure(service_name: str, *, console: bool = False) -> TracerProvider:
    """Return an owned provider. Call once per service and shut down on exit.

    OTLP uses standard OTEL_EXPORTER_OTLP_* environment variables. Providers
    are explicit so tests and multiple simulated services do not alter globals.
    """
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    exporter = ConsoleSpanExporter() if console else OTLPSpanExporter()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    return provider


def metadata(span: Span, **attributes: str | int | bool) -> None:
    for key, value in attributes.items():
        if key not in _ALLOWED:
            raise ValueError("Attribute is outside the telemetry allowlist")
        span.set_attribute(key, value)


@contextmanager
def operation(tracer: trace.Tracer, name: str, *, task_id: str,
              context: Context | None = None,
              kind: SpanKind = SpanKind.INTERNAL) -> Iterator[Span]:
    """Record failure status without exporting raw exception text/stack traces."""
    with tracer.start_as_current_span(
        name, context=context, kind=kind,
        record_exception=False, set_status_on_exception=False,
    ) as span:
        metadata(span, **{"lab.task.id": task_id})
        try:
            yield span
        except Exception:
            metadata(span, **{"lab.error.type": "operation_failed"})
            span.set_status(Status(StatusCode.ERROR))
            raise


def handoff_headers() -> dict[str, str]:
    """Attach to an outgoing HTTP request/message; task ID travels separately."""
    headers: dict[str, str] = {}
    _PROPAGATOR.inject(headers)
    return headers


def receive_context(headers: Mapping[str, str]) -> Context:
    """Extract only W3C trace context, without propagating arbitrary baggage."""
    return _PROPAGATOR.extract(dict(headers))
