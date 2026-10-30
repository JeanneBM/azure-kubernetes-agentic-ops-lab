"""Keep workstation/CI OpenTelemetry settings out of deterministic tests."""
import os

import pytest


@pytest.fixture(autouse=True)
def isolated_otel_environment(monkeypatch):
    for name in list(os.environ):
        if name.startswith("OTEL_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "always_on")
