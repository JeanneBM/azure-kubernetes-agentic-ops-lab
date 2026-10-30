"""Synthetic flow: no model API, Kubernetes credentials or cluster mutations."""
import argparse
import json
from uuid import uuid4

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import SpanKind, Status, StatusCode

from .telemetry import configure, handoff_headers, metadata, operation, receive_context

SCENARIOS = ("success", "policy-denied", "model-timeout", "tool-error")


def remediate(provider: TracerProvider, headers: dict[str, str], task_id: str,
              scenario: str, executions: list[str]) -> str:
    tracer = provider.get_tracer("agentic_ops_lab.remediation")
    with operation(tracer, "remediation.receive", task_id=task_id,
                   context=receive_context(headers), kind=SpanKind.SERVER) as receiver:
        with operation(tracer, "policy.evaluate", task_id=task_id) as gate:
            decision = "deny" if scenario == "policy-denied" else "allow"
            metadata(gate, **{"lab.policy.decision": decision, "lab.policy.version": "demo-v1"})
        if decision == "deny":
            metadata(receiver, **{"lab.outcome": "escalated"})
            return "escalated"
        with operation(tracer, "remediation.execute", task_id=task_id) as execution:
            metadata(execution, **{"lab.action": "stub.image_correction"})
            if scenario == "tool-error":
                metadata(execution, **{"lab.error.type": "tool_unavailable"})
                execution.set_status(Status(StatusCode.ERROR))
                receiver.set_status(Status(StatusCode.ERROR))
                metadata(receiver, **{"lab.outcome": "failed"})
                return "failed"
            executions.append("stub.image_correction")
        with operation(tracer, "remediation.verify", task_id=task_id) as verification:
            metadata(verification, **{"lab.outcome": "simulated_healthy"})
        metadata(receiver, **{"lab.outcome": "resolved"})
        return "resolved"


def run(diagnostic: TracerProvider, remediation: TracerProvider,
        scenario: str = "success", task_id: str | None = None) -> dict:
    if scenario not in SCENARIOS:
        raise ValueError("Unknown demo scenario")
    task_id = task_id or str(uuid4())
    executions: list[str] = []
    tracer = diagnostic.get_tracer("agentic_ops_lab.diagnostic")
    with operation(tracer, "incident.run", task_id=task_id) as root:
        metadata(root, **{"lab.scenario": scenario, "lab.mode": "synthetic"})
        with operation(tracer, "diagnostic.collect", task_id=task_id):
            pass  # Future adapter: collect bounded observations from Kubernetes.
        with operation(tracer, "diagnostic.model", task_id=task_id) as model:
            metadata(model, **{"lab.model.name": "stub-no-model", "lab.attempt": 1})
            if scenario == "model-timeout":
                metadata(model, **{"lab.error.type": "model_timeout"})
                model.set_status(Status(StatusCode.ERROR))
        if scenario == "model-timeout":
            outcome = "escalated"
            root.set_status(Status(StatusCode.ERROR))
        else:
            with operation(tracer, "diagnostic.handoff", task_id=task_id,
                           kind=SpanKind.CLIENT) as sender:
                # Serialization boundary: receiver reconstructs context from headers.
                headers = json.loads(json.dumps(handoff_headers()))
                outcome = remediate(remediation, headers, task_id, scenario, executions)
                if outcome == "failed":
                    sender.set_status(Status(StatusCode.ERROR))
                    root.set_status(Status(StatusCode.ERROR))
        metadata(root, **{"lab.outcome": outcome})
        trace_id = format(root.get_span_context().trace_id, "032x")
    return {"task_id": task_id, "trace_id": trace_id, "scenario": scenario,
            "outcome": outcome, "mode": "synthetic", "executions": executions}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, default="success")
    parser.add_argument("--console", action="store_true", help="Print spans instead of OTLP export")
    args = parser.parse_args()
    diagnostic = configure("lab-diagnostic", console=args.console)
    remediation = configure("lab-remediation", console=args.console)
    try:
        print(json.dumps(run(diagnostic, remediation, args.scenario)))
        for provider in (diagnostic, remediation):
            if not provider.force_flush(timeout_millis=10000):
                raise RuntimeError("Telemetry flush did not complete")
    finally:
        diagnostic.shutdown()
        remediation.shutdown()


if __name__ == "__main__":
    main()
