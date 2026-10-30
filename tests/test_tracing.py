import pytest
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from agentic_ops_lab.demo import run
from agentic_ops_lab.telemetry import metadata, operation


@pytest.fixture
def tracing():
    exporter = InMemorySpanExporter()
    providers = []
    for service in ("diagnostic", "remediation"):
        provider = TracerProvider(resource=Resource.create({"service.name": service}))
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        providers.append(provider)
    yield providers, exporter
    for provider in providers:
        provider.shutdown()


def test_handoff_keeps_one_trace_and_remote_parent(tracing):
    providers, exporter = tracing
    result = run(*providers)
    spans = exporter.get_finished_spans()
    assert len({s.context.trace_id for s in spans}) == 1
    assert all(s.attributes["lab.task.id"] == result["task_id"] for s in spans)
    by_name = {s.name: s for s in spans}
    receiver = by_name["remediation.receive"]
    assert receiver.parent.is_remote
    assert receiver.parent.span_id == by_name["diagnostic.handoff"].context.span_id
    assert {s.resource.attributes["service.name"] for s in spans} == {"diagnostic", "remediation"}
    assert result["executions"] == ["stub.image_correction"]
    assert "remediation.verify" in by_name


@pytest.mark.parametrize("scenario,outcome,missing", [
    ("policy-denied", "escalated", "remediation.execute"),
    ("model-timeout", "escalated", "remediation.receive"),
    ("tool-error", "failed", "remediation.verify"),
])
def test_failures_do_not_continue_to_execution_or_verification(tracing, scenario, outcome, missing):
    providers, exporter = tracing
    result = run(*providers, scenario=scenario)
    spans = exporter.get_finished_spans()
    assert result["outcome"] == outcome
    assert result["executions"] == []
    assert missing not in {s.name for s in spans}
    if scenario != "policy-denied":
        assert any(s.status.status_code == StatusCode.ERROR for s in spans)
    else:
        gate = next(s for s in spans if s.name == "policy.evaluate")
        assert gate.attributes["lab.policy.decision"] == "deny"


def test_exception_does_not_export_sensitive_text(tracing):
    providers, exporter = tracing
    with pytest.raises(RuntimeError):
        with operation(providers[0].get_tracer("test"), "test.failure", task_id="opaque-id"):
            raise RuntimeError("secret-token-do-not-export")
    span = exporter.get_finished_spans()[0]
    assert span.status.status_code == StatusCode.ERROR
    assert not span.events
    assert "secret-token-do-not-export" not in span.to_json()


def test_metadata_rejects_prompt_capture(tracing):
    providers, exporter = tracing
    with operation(providers[0].get_tracer("test"), "test.metadata", task_id="opaque-id") as span:
        with pytest.raises(ValueError):
            metadata(span, **{"prompt": "secret-prompt"})
    assert "secret-prompt" not in exporter.get_finished_spans()[0].to_json()
