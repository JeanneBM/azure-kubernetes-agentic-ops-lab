"""Exercise the real HTTP/protobuf exporter against a local receiver."""
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from agentic_ops_lab.demo import run
from agentic_ops_lab.telemetry import configure


def test_otlp_exports_both_services_with_one_trace(monkeypatch):
    requests = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = self.rfile.read(int(self.headers["Content-Length"]))
            message = ExportTraceServiceRequest()
            message.ParseFromString(payload)
            requests.append((self.path, message))
            self.send_response(200)
            self.send_header("Content-Type", "application/x-protobuf")
            self.end_headers()

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Receiver)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
                       f"http://127.0.0.1:{server.server_port}/v1/traces")
    providers = [configure("lab-diagnostic"), configure("lab-remediation")]
    try:
        result = run(*providers)
        assert all(p.force_flush(timeout_millis=5000) for p in providers)
        assert len(requests) == 2
        assert all(path == "/v1/traces" for path, _ in requests)
        resources = [rs for _, message in requests for rs in message.resource_spans]
        services = {a.value.string_value for rs in resources for a in rs.resource.attributes
                    if a.key == "service.name"}
        assert services == {"lab-diagnostic", "lab-remediation"}
        spans = [s for rs in resources for scope in rs.scope_spans for s in scope.spans]
        assert {s.trace_id.hex() for s in spans} == {result["trace_id"]}
        assert len(spans) == 8
    finally:
        for provider in providers:
            provider.shutdown()
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
