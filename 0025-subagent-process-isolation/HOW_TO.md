# How to run the subagent process isolation experiment

## Purpose

Run a fullsend agent that intercepts `Agent()` calls via a PreToolUse hook and executes the subagent work as an isolated `claude` CLI process.

## Requirements

| Requirement | Link |
|-------------|------|
| fullsend CLI v0.33.0+ | https://github.com/fullsend-ai/fullsend |
| OpenShell 0.0.83+ | https://github.com/NVIDIA/OpenShell |
| Podman | https://podman.io/docs/installation |
| Python 3.10+ | https://www.python.org/downloads/ |
| jq | https://jqlang.github.io/jq/download/ |

### Environment variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_VERTEX_PROJECT_ID` | GCP project with Vertex AI API enabled |
| `CLOUD_ML_REGION` | GCP region (e.g., `us-east5`, `europe-west1`, `global`) |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to GCP service account key or ADC JSON |

## Steps

### Basic run

1. Pre-pull the sandbox image:
   ```bash
   podman pull ghcr.io/fullsend-ai/fullsend-sandbox:latest
   ```

2. Set `GOOGLE_APPLICATION_CREDENTIALS`:
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS=~/.config/gcloud/application_default_credentials.json
   ```

3. Clean up previous results:
   ```bash
   rm -rf results/
   ```

4. Create an empty target repo:
   ```bash
   mkdir -p /tmp/empty-target-repo
   git -C /tmp/empty-target-repo init 2>/dev/null
   ```

5. Run the experiment:
   ```bash
   cd 0025-subagent-process-isolation
   fullsend run judge-parent \
     --fullsend-dir .fullsend \
     --target-repo /tmp/empty-target-repo \
     --output-dir results
   ```

6. Verify output files:
   ```bash
   ls results/agent-judge-parent-*/iteration-1/output/
   ```

7. Verify hook interception:
   ```bash
   TRANSCRIPT=$(find results -name '*.jsonl' -path '*/transcripts/*' | head -1)
   python3 -c "
   import json, sys
   for line in open('$TRANSCRIPT'):
       d = json.loads(line)
       a = d.get('attachment', {})
       if a.get('type') == 'hook_success' and 'Agent' in a.get('hookName', ''):
           print('Hook fired:', a['hookName'])
           print('Updated input preview:', json.dumps(a.get('content', ''))[:200])
   "
   ```

8. Compare session IDs across transcripts:
   ```bash
   for f in results/agent-judge-parent-*/iteration-1/transcripts/*.jsonl; do
     echo "=== $(basename "$f") ==="
     head -1 "$f" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  session_id: {d.get(\"sessionId\", d.get(\"session_id\", \"N/A\"))}')"
   done
   ```

### Cost verification with Jaeger

Verify that the spawned process's cost appears as a separate OTEL span
under the same trace as the parent.

1. Start Jaeger with OTLP HTTP support:
   ```bash
   podman run -d --name jaeger \
     -p 16686:16686 \
     -p 4318:4318 \
     docker.io/jaegertracing/jaeger:2.14.0 \
     --set receivers.otlp.protocols.http.endpoint=0.0.0.0:4318
   ```

2. Verify the OTLP endpoint:
   ```bash
   curl -s http://localhost:4318/v1/traces \
     -X POST -H 'Content-Type: application/json' \
     -d '{"resourceSpans":[]}'
   ```

3. Run the experiment with `OTEL_EXPORTER_OTLP_ENDPOINT`:
   ```bash
   rm -rf results/
   OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
   fullsend run judge-parent \
     --fullsend-dir .fullsend \
     --target-repo /tmp/empty-target-repo \
     --output-dir results
   ```

4. Open Jaeger at `http://localhost:16686`, select service `fullsend`,
   and verify 4 spans: `run`, `sandbox_create`, `agent`,
   `spawned_agent` (nested within `agent`).

5. Clean up:
   ```bash
   podman stop jaeger && podman rm jaeger
   ```

## Expected Output

- `output/topic.md` — short paragraph about Python
- `output/evaluation.md` — structured evaluation with scores (1-5)
- `output/summary.md` — one-line summary of the evaluation
- `output/.spawned-cost.json` — spawned process cost and token usage
- Parent transcript contains a `hook_success` attachment for
  `PreToolUse:Agent`
- Three transcripts: parent session, spawned `claude -p` process
  (distinct session ID), and echo-through subagent (shares parent's
  session ID)
- With Jaeger: `spawned_agent` span carries `fullsend.cost_usd` and
  `gen_ai.usage.*` attributes
