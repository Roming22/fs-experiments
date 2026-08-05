#!/usr/bin/env python3
"""Post-script: emits an OTEL span for the spawned subprocess's cost.

Reads .spawned-cost.json from the output directory (written by the
pretooluse hook), then sends a single span to the OTLP endpoint under
the same trace as the parent run. This makes the spawned process's
cost visible in MLflow alongside the parent's cost.

Environment (set by fullsend):
  TRACEPARENT          — W3C traceparent from the parent run
  OTEL_EXPORTER_OTLP_ENDPOINT — OTLP HTTP endpoint (e.g. http://host:4318)
  CWD                  — the run directory (contains iteration-*/output/)
"""

import glob
import json
import os
import struct
import sys
import time
import urllib.request
import urllib.error


def parse_traceparent(tp):
    """Parse W3C traceparent: 00-{trace_id}-{parent_span_id}-{flags}."""
    parts = tp.split("-")
    if len(parts) != 4 or parts[0] != "00":
        return None
    return {"trace_id": parts[1], "parent_span_id": parts[2], "flags": int(parts[3], 16)}


def new_span_id():
    """Generate a random 16-hex-char span ID."""
    return struct.pack(">Q", int.from_bytes(os.urandom(8), "big")).hex()


def build_otlp_payload(trace_id, parent_span_id, cost_data):
    """Build OTLP/JSON ExportTraceServiceRequest with one span."""
    start_ns = cost_data.get("start_time_unix_nano", str(int(time.time() * 1e9)))
    end_ns = cost_data.get("end_time_unix_nano", start_ns)

    usage = cost_data.get("usage", {})
    attributes = [
        {"key": "fullsend.cost_usd", "value": {"doubleValue": cost_data.get("total_cost_usd", 0)}},
        {"key": "fullsend.spawned_session_id", "value": {"stringValue": cost_data.get("session_id", "")}},
        {"key": "gen_ai.request.model", "value": {"stringValue": cost_data.get("model", "")}},
        {"key": "gen_ai.usage.input_tokens", "value": {"intValue": str(usage.get("input_tokens", 0))}},
        {"key": "gen_ai.usage.output_tokens", "value": {"intValue": str(usage.get("output_tokens", 0))}},
        {"key": "gen_ai.usage.cache_creation.input_tokens", "value": {"intValue": str(usage.get("cache_creation_input_tokens", 0))}},
        {"key": "gen_ai.usage.cache_read.input_tokens", "value": {"intValue": str(usage.get("cache_read_input_tokens", 0))}},
        {"key": "fullsend.num_turns", "value": {"intValue": str(cost_data.get("num_turns", 0))}},
    ]

    return {
        "resourceSpans": [{
            "resource": {
                "attributes": [
                    {"key": "service.name", "value": {"stringValue": "fullsend"}},
                ],
            },
            "scopeSpans": [{
                "scope": {"name": "fullsend.post-script"},
                "spans": [{
                    "traceId": trace_id,
                    "spanId": new_span_id(),
                    "parentSpanId": parent_span_id,
                    "name": "spawned_agent",
                    "kind": 1,
                    "startTimeUnixNano": start_ns,
                    "endTimeUnixNano": end_ns,
                    "attributes": attributes,
                    "status": {"code": 1},
                }],
            }],
        }],
    }


def main():
    traceparent = os.environ.get("TRACEPARENT", "")
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")

    if not traceparent:
        print("[post-emit-cost] no TRACEPARENT, skipping", file=sys.stderr)
        return

    if not endpoint:
        print("[post-emit-cost] no OTEL_EXPORTER_OTLP_ENDPOINT, skipping", file=sys.stderr)
        return

    tp = parse_traceparent(traceparent)
    if not tp:
        print(f"[post-emit-cost] invalid TRACEPARENT: {traceparent}", file=sys.stderr)
        return

    cost_files = glob.glob("iteration-*/output/.spawned-cost.json")
    if not cost_files:
        print("[post-emit-cost] no .spawned-cost.json found, skipping", file=sys.stderr)
        return

    for cost_file in cost_files:
        with open(cost_file) as f:
            cost_data = json.load(f)

        cost_usd = cost_data.get("total_cost_usd", 0)
        print(f"[post-emit-cost] found {cost_file}: ${cost_usd:.4f}", file=sys.stderr)

        payload = build_otlp_payload(tp["trace_id"], tp["parent_span_id"], cost_data)
        url = endpoint.rstrip("/") + "/v1/traces"

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                print(f"[post-emit-cost] sent span to {url}: {resp.status}", file=sys.stderr)
        except urllib.error.URLError as e:
            print(f"[post-emit-cost] failed to send span to {url}: {e}", file=sys.stderr)
        except Exception as e:
            print(f"[post-emit-cost] unexpected error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
