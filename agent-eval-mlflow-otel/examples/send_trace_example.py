"""Simplified example of sending an agent trace to MLflow via OTLP.

This demonstrates the core pattern: reconstruct a span tree from agent
artifacts and export via OTLP HTTP. The production version (send-trace.py)
handles many more edge cases and data sources.

Env:
    OTEL_EXPORTER_OTLP_TRACES_ENDPOINT — MLflow OTLP endpoint (e.g. https://<host>/v1/traces)
    MLFLOW_OTLP_TOKEN — Bearer token for OTLP + Basic auth for tag API
"""
import os
import time

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

OTLP_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "")
MLFLOW_TOKEN = os.environ.get("MLFLOW_OTLP_TOKEN", "")


def send_example_trace():
    """Send a minimal agent trace to MLflow."""
    headers = {}
    if MLFLOW_TOKEN:
        headers["Authorization"] = f"Bearer {MLFLOW_TOKEN}"
        headers["x-mlflow-experiment-id"] = "0"

    provider = TracerProvider()
    exporter = OTLPSpanExporter(endpoint=OTLP_ENDPOINT, headers=headers)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer("fullsend")

    with tracer.start_as_current_span("explore-pipeline") as root:
        root.set_attribute("openinference.span.kind", "CHAIN")
        root.set_attribute("agent", "explore")
        root.set_attribute("session.id", "github:84")
        root.set_attribute("input.value", "Explore issue #84: Regression test suite")
        root.set_attribute("llm.cost", 0.36)

        with tracer.start_as_current_span("pre-explore") as pre:
            pre.set_attribute("pipeline.phase", "pre-explore")
            time.sleep(0.01)

            with tracer.start_as_current_span("pre-explore:fetch-issue") as fetch:
                fetch.set_attribute("pipeline.step", "fetch-issue")
                time.sleep(0.01)

        with tracer.start_as_current_span("fullsend:agent-execution") as exec_span:
            exec_span.set_attribute("fullsend.step", "agent-execution")

            with tracer.start_as_current_span("explore-agent") as agent:
                agent.set_attribute("openinference.span.kind", "LLM")
                agent.set_attribute("llm.model_name", "claude-opus-4-6")
                agent.set_attribute("tool_call_count", 8)
                agent.set_attribute("reasoning_turn_count", 5)
                agent.set_attribute("confidence.overall", 72)
                time.sleep(0.01)

        with tracer.start_as_current_span("fullsend:results") as results:
            results.set_attribute("result.validation", "passed")
            results.set_attribute("output.value", '{"summary": "...", "confidence": {"overall": 72}}')

        root.set_attribute("output.value", "Exploration complete. Confidence: 72/100")

    provider.shutdown()
    print("Trace sent to MLflow via OTLP")


if __name__ == "__main__":
    if not OTLP_ENDPOINT:
        print("Set OTEL_EXPORTER_OTLP_TRACES_ENDPOINT to your MLflow instance")
    else:
        send_example_trace()
