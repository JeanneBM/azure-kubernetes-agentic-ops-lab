# OpenTelemetry foundation

## Available now

A reusable Python tracing module and a **synthetic** diagnostic → policy → remediation
flow. It does not call a model, connect to Kubernetes, fix a workload, or implement
record/replay. The existing four-role design remains Diagnostic, Remediation,
Saboteur and Investigator. Telemetry is supporting infrastructure.

The demo simulates two services with separate tracer providers. It serializes W3C
`traceparent` headers at the handoff and extracts them on the receiver. There is no
HTTP agent server yet. OTLP export itself uses real HTTP/protobuf.

## Run without Docker or cloud access

Python 3.11+ (Windows Git Bash included):

```bash
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows Git Bash instead:
# source .venv/Scripts/activate
python -m pip install -e '.[dev]'
python -m pytest -q
python -m agentic_ops_lab.demo --console
```

Console mode writes spans locally and makes no telemetry network requests. Package
installation requires access to the Python package index.

## Local trace UI

With Docker Engine / Docker Desktop running, from the repository root:

```bash
docker compose -f observability/compose.yaml up -d
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:4318/v1/traces
export OTEL_TRACES_SAMPLER=always_on
python -m agentic_ops_lab.demo --scenario success
python -m agentic_ops_lab.demo --scenario policy-denied
python -m agentic_ops_lab.demo --scenario model-timeout
python -m agentic_ops_lab.demo --scenario tool-error
```

The demo respects standard OpenTelemetry sampling settings. `always_on` above
keeps every span for local experiments; review sampling for production use.
Wait for services to start before running the demo. Open http://localhost:3000,
log in with Grafana's initial `admin` / `admin` credentials and change the password.
In **Explore → Tempo**, select **Trace ID**, paste the printed `trace_id` and run
the query. Allow a few seconds for batching; retry if needed.

Only Grafana and Collector HTTP ingest are published, both on host loopback.
Tempo is internal to the Compose network. This unauthenticated ingest configuration
is for local development only, not a production or shared-cluster deployment.

```bash
docker compose -f observability/compose.yaml down
# Delete locally retained traces and Grafana settings when desired:
# docker compose -f observability/compose.yaml down -v
```

| Synthetic scenario | Expected behavior |
| --- | --- |
| success | Stub execution and stub verification; outcome `resolved` |
| policy-denied | Gate says deny; no execution or verification; `escalated` |
| model-timeout | Model span marked ERROR; no handoff or execution; `escalated` |
| tool-error | Execution span marked ERROR; no verification; `failed` |

A policy denial is an expected control outcome, not a telemetry error. Outcomes in
this demo are simulated, not evidence of live remediation quality. Token counts
are intentionally absent because no model was called.

## Integrate real agents next

1. Configure one provider per service at startup; use standard OTLP endpoint,
   headers and TLS environment settings for the destination. Flush/shut down at exit.
2. Wrap actual collection, model requests, policy, execution and rollout checks
   with `operation`. Keep task IDs opaque and pass the same ID in the task envelope.
3. Attach `handoff_headers()` to the outgoing task HTTP request/message. On the
   other service pass `receive_context(headers)` to its receiving span. Accept
   trace headers only across a trusted boundary; tracing conveys no authorization.
4. Add allowlisted token counts from the actual model response when available.
   Do not infer token use from text length or count retry totals twice.
5. Keep authorization and rollout assertions in deterministic application code.
   Tracing reports what happened and must not become an authorization mechanism.

Example outgoing boundary:

```python
with operation(tracer, "diagnostic.handoff", task_id=task_id, kind=SpanKind.CLIENT):
    headers = handoff_headers()
    # Send headers and task_id with the real request here.
```

Receiving boundary:

```python
with operation(tracer, "remediation.receive", task_id=task_id,
               context=receive_context(headers), kind=SpanKind.SERVER):
    # Validate policy and execute permitted action here.
    ...
```

Import `SpanKind` from `opentelemetry.trace` and the helpers from
`agentic_ops_lab.telemetry`. Span names should be static; avoid resource names or
user content in span names and task IDs.

## Data contract and limitations

- `lab.*` metadata is a small project-specific contract. It does not claim conformance
  to evolving GenAI semantic conventions.
- The helper rejects unknown attribute keys. It does not sanitize arbitrary values:
  callers must supply bounded categories, opaque IDs and approved model identifiers.
- Raw prompts, model responses, logs, arguments, credentials and exception text are
  not recorded by these helpers. Exceptions produce a generic error category.
- Direct SDK calls or future auto-instrumentation can bypass these helpers; review
  their capture behavior before enabling them.
- Traces contain timing, parentage and selected metadata. They are not the full
  redacted evidence recordings required for replay.
- This increment implements traces only. Metrics, log correlation, retry policies,
  real token accounting and live agent integration remain future work.
- In-memory tests cover parentage, control-flow boundaries and sensitive exception
  omission. An HTTP receiver test checks the real OTLP protobuf payload. Full
  Collector/Tempo/Grafana startup must be verified in a Docker-enabled environment.

## References

- [OpenTelemetry Python tracing](https://opentelemetry.io/docs/languages/python/instrumentation/)
- [GenAI conventions](https://github.com/open-telemetry/semantic-conventions-genai)
- [Collector configuration](https://opentelemetry.io/docs/collector/configuration/)
