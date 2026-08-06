# Host-Side API Server Experiment — Findings

## Experiment overview

This experiment tests whether an AI agent running inside an OpenShell sandbox
can call host-side API servers through the L7 network proxy, and compares three
methods for the agent to discover the API endpoints:

- **baked-instructions** — endpoint documentation hardcoded in a skill (Markdown)
- **openapi-discovery** — agent fetches `/openapi.json` from each server at runtime
- **tooluse-discovery** — agent fetches `/tools.json` (structured tool-use schema) at runtime

Each discovery method was tested under two network policies:

- **full-access** — all endpoints allowed (`/build`, `/push`, `/images`, `/openapi.json`, `/tools.json`, `/repo/provision`, `/repo/status/*`)
- **restricted** — build-only and provision-only (`/build`, `/repo/provision`, `/repo/status/*`); no discovery endpoints

The agent task: clone `fullsend-ai/fullsend` via the provisioner API, then
build `images/sandbox/Containerfile` via the builder API and upload the image
tarball back into the sandbox.

## Execution

6 harnesses were run, one per combination:

```
export GOOGLE_APPLICATION_CREDENTIALS=/tmp/fullsend-agent-key.json
export FULLSEND_GCP_PROJECT_ID=<gcp-project-id>

./run.sh baked-instructions-full
./run.sh baked-instructions-restricted
./run.sh openapi-discovery-full
./run.sh openapi-discovery-restricted
./run.sh tooluse-discovery-full
./run.sh tooluse-discovery-restricted
```

## Results

Each run directory contains the agent transcript (JSONL) and output files:

| Harness | Results |
|---------|---------|
| baked-instructions-full | [results/agent-baked-instructions-full-4005358-1779242542](results/agent-baked-instructions-full-4005358-1779242542) |
| baked-instructions-restricted | [results/agent-baked-instructions-restricted-4080040-1779243702](results/agent-baked-instructions-restricted-4080040-1779243702) |
| openapi-discovery-full | [results/agent-openapi-discovery-full-4038775-1779243123](results/agent-openapi-discovery-full-4038775-1779243123) |
| openapi-discovery-restricted | [results/agent-openapi-discovery-restricted-4097617-1779243949](results/agent-openapi-discovery-restricted-4097617-1779243949) |
| tooluse-discovery-full | [results/agent-tooluse-discovery-full-4061051-1779243439](results/agent-tooluse-discovery-full-4061051-1779243439) |
| tooluse-discovery-restricted | [results/agent-tooluse-discovery-restricted-4121470-1779244303](results/agent-tooluse-discovery-restricted-4121470-1779244303) |

### Replaying sessions

Each result directory contains a `replay.html` file that can be opened in a
browser for an interactive session replay. To regenerate or replay any
transcript:

```bash
# Generate replay HTML from a transcript
claude-replay results/<run-dir>/iteration-1/transcripts/<transcript>.jsonl \
  -o results/<run-dir>/replay.html

# Open in browser
xdg-open results/<run-dir>/replay.html
```

## Architecture validated by the experiment

### Canonical hostname: `host.openshell.internal`

OpenShell's L7 proxy matches outbound requests by **hostname**, not IP address.
Raw private IPs (e.g. `192.168.x.x`) are blocked by SSRF protection. The
canonical hostname `host.openshell.internal` resolves to the host bridge IP
inside the sandbox and must be used in:

- **Env files** delivered into the sandbox (`BUILDER_URL`, `PROVISIONER_URL`)
- **Network policy endpoints** (`host: host.openshell.internal`)

~~The host IP is still needed for `allowed_ips` in network policies (SSRF
allowlisting requires a CIDR, not a hostname). The orchestrator resolves this
at runtime via `getent hosts host.openshell.internal` and renders it into
policy templates with `sed "s/{{HOST_IP}}/$HOST_IP/g"`.~~

**Update (2026-07-16):** `allowed_ips` is no longer required. See
[below](#2026-07-16-allowed_ips-no-longer-required-for-declared-endpoints).

### Server process contract

Both API servers follow a uniform process contract that the orchestrator relies
on:

- **CLI flags**: `--port <port>` and `--token <bearer-token>` (required),
  `--sandbox <name>` (optional, deprecated in favor of per-request `sandbox`
  field)
- **Health endpoint**: `GET /healthz` returns `{"status": "ok"}` — the
  orchestrator polls this before starting the agent
- **Discovery endpoint**: `GET /tools.json` returns an array of tool
  definitions with `name`, `description`, `endpoint`, `method`, and
  `input_schema` per tool
- **Graceful shutdown**: Handles `SIGTERM`/`SIGINT` for clean teardown
- **Authentication**: All non-health endpoints require
  `Authorization: Bearer <token>`
- **Sandbox field**: Mutable endpoints accept a `sandbox` field in the request
  body so the server can exchange files with the correct sandbox via
  `openshell sandbox upload/download`

### Authentication via OpenShell providers

The experiment uses a per-run bearer token with OpenShell's `generic` provider
type for credential isolation:

1. The orchestrator generates a random UUID token at startup
2. A provider definition (`providers/api-server.yaml`) declares:
   ```yaml
   name: api-server
   type: generic
   credentials:
     API_TOKEN: ${API_TOKEN}
   ```
3. The orchestrator exports `API_TOKEN` and creates the provider on the gateway
   via `openshell provider create`
4. The harness attaches the provider to the sandbox (`providers: [api-server]`)
5. Inside the sandbox, `$API_TOKEN` contains a placeholder
   (`openshell:resolve:env:API_TOKEN`). The L7 proxy resolves this placeholder
   to the real token in outgoing `Authorization` headers — the real token never
   enters the sandbox

This implements tier 2 from ADR-0025 (providers + L7 policies). The agent uses
`curl -H "Authorization: Bearer $API_TOKEN"` and the proxy transparently
swaps the placeholder.

### File transfer: `openshell sandbox download/upload`

API servers that need to exchange files with the sandbox use OpenShell's native
file transfer commands on the host side:

- **Download from sandbox**: `openshell sandbox download <name> <sandbox-path> <local-path>`
  — used by the builder to fetch the build context from the sandbox before
  building
- **Upload to sandbox**: `openshell sandbox upload <name> <local-path> <sandbox-path>`
  — used by the provisioner to deliver cloned repos and by the builder to
  deliver image tarballs back into the sandbox

The agent identifies its sandbox by running
`hostname | sed 's/^sandbox-//'` (OpenShell prefixes the hostname with
`sandbox-`) and passes it in the `sandbox` field of API requests. The server
uses this name with the `openshell sandbox` commands.

This design avoids baking the sandbox name into server startup flags (the
sandbox doesn't exist when servers start) and lets a single server instance
serve multiple sandboxes if needed.

### Network policy structure

L7 policies use `protocol: rest` with hostname-based endpoint matching and
binary-level restrictions:

```yaml
network_policies:
  builder:
    name: container-builder
    endpoints:
      - host: host.openshell.internal
        port: 9090
        protocol: rest
        enforcement: enforce
        rules:
          - allow:
              method: POST
              path: /build
          # ...additional allowed paths
    binaries:
      - path: "**/curl"
```

Key elements:
- **`protocol: rest`**: Enables HTTP method + path matching at L7
- **`binaries`**: Restricts which executables can reach the endpoint (`**/curl`
  ensures only curl can call the API, not arbitrary processes)
- **Restricted policies** omit discovery endpoints (`/openapi.json`,
  `/tools.json`) and non-essential operations (`/push`, `/images`) to test
  agent behavior under reduced API surface

> **Note:** The original experiment included `allowed_ips: ["{{HOST_IP}}/32"]`
> in endpoint declarations. This is no longer needed — see
> [update below](#2026-07-16-allowed_ips-no-longer-required-for-declared-endpoints).

### Orchestrator lifecycle

The wrapper script (`run.sh`) manages the full lifecycle:

1. **Build binaries** if needed (reuses `setup.sh`)
2. **Kill stale processes** on ports 9090/9091
3. **Generate bearer token** (UUID) and export as `API_TOKEN`
4. **Start API servers** (builder on :9090, provisioner on :9091) with `--token`
5. **Health-check** both servers (poll `/healthz` up to 15s, verify PIDs alive)
6. **Generate env file** with `BUILDER_URL` and `PROVISIONER_URL` using
   `host.openshell.internal` hostname
7. **Run `fullsend run`** with `--fullsend-dir .` (experiment directory is the
   fullsend directory)
8. **Cleanup on exit** (trap): kill server PIDs, delete provider, remove
    temp env file

> **Note:** The original lifecycle included HOST_IP resolution (step 6) and
> policy template rendering (step 7) for `allowed_ips`. These steps were
> removed in the 2026-07-16 update.

The harness files deliver the env file into the sandbox via `host_files`:
```yaml
host_files:
  - src: ${EXPERIMENT_ENV_FILE}
    dest: /tmp/workspace/.env.d/api-servers.env
```
The fullsend bootstrap sources all `.env.d/*.env` files, making `$BUILDER_URL`
and `$PROVISIONER_URL` available to the agent.

### Bugs found and fixed during the experiment

| Issue | Root cause | Fix |
|-------|-----------|-----|
| All API requests returned 403 | Env file used raw IP (`http://192.168.x.x:9090`); L7 proxy matches by hostname | Changed URLs to `http://host.openshell.internal:9090` |
| Provisioner rejected repo (pre-commit hook) | Git hook scanner flagged `.git/hooks/pre-commit` as high severity | Downgraded executable git hook severity to medium |
| Agent output not found by fullsend | Agent wrote to `output/results.md` relative to CWD; fullsend extracts from `/tmp/workspace/output/` | Updated agent instructions to use absolute path |
| Provisioner didn't upload repo to sandbox | Server started without `--sandbox` (sandbox doesn't exist yet) | Added `sandbox` field to request body; agent passes its name per-request |
| Sandbox name mismatch | Hostname inside sandbox has `sandbox-` prefix; `openshell sandbox` commands use the name without prefix | Agent uses `hostname \| sed 's/^sandbox-//'` |
| Builder built from git URL instead of sandbox files | Builder used local/git paths, not sandbox file transfer | Rewrote builder to download context via `openshell sandbox download`, build locally, upload tarball back |
| Agent ignored skills | Agent had `tools: Bash(curl)` only; `Skill` tool not listed | Added `Skill` to agent tool list |

## Conclusions

### Outcome summary

| Harness | Policy | Clone | Build | Image Upload | Turns | Input | Output | Cache Read | Cache Create | Total Tokens |
|---------|--------|-------|-------|--------------|-------|-------|--------|-----------|-------------|-------------|
| baked-instructions-full | full | ✅ | ✅ | ✅ | 11 | 14 | 2,466 | 83,660 | 14,114 | 100,254 |
| baked-instructions-restricted | restricted | ✅ | ✅ | ✅ | 9 | 12 | 2,196 | 67,624 | 13,923 | 83,755 |
| openapi-discovery-full | full | ✅ | ✅ | ✅ | 10 | 13 | 2,813 | 88,022 | 15,932 | 106,780 |
| openapi-discovery-restricted | restricted | ❌ | ❌ | ❌ | 28 | 31 | 16,277 | 485,115 | 32,219 | 533,642 |
| tooluse-discovery-full | full | ✅ | ✅ | ✅ | 10 | 13 | 2,513 | 76,229 | 14,032 | 92,787 |
| tooluse-discovery-restricted | restricted | ❌ | ⚠️ | ❌ | 19 | 22 | 8,244 | 180,454 | 16,723 | 205,443 |

### Key findings

1. **All three discovery methods succeed under full-access policy.** When
   every endpoint is reachable, the agent completes both tasks regardless of
   how it discovers the API. Token usage is comparable across methods
   (83k–107k).

2. **Discovery-based methods fail under restricted policy.** When
   `/openapi.json` and `/tools.json` are blocked by the L7 proxy, the agent
   cannot discover the API schema and falls back to guessing endpoint paths —
   burning 2x–6x more tokens (205k–534k) across 19–28 turns without
   completing the task.

3. **Baked instructions are the only method resilient to restricted policies.**
   The agent already knows the endpoint paths and request schemas from the
   skill, so it calls the APIs directly without needing a discovery endpoint.
   It also uses the fewest tokens overall.

4. **Token cost correlates with turns, not discovery method.** Successful runs
   take 9–11 turns. Failed discovery runs balloon to 19–28 turns as the agent
   thrashes through path guessing.

### Recommendations

#### API discovery: tool-use (`/tools.json`) as the standard

Despite baked instructions being the most resilient, **tool-use discovery
(`/tools.json`) is the recommended standard** for the following reasons:

- **Structured over prose.** `/tools.json` returns a machine-readable JSON
  schema with `name`, `endpoint`, `method`, and `input_schema` per tool. The
  agent parses structured data rather than interpreting Markdown documentation,
  reducing ambiguity.

- **Single source of truth.** The schema lives in the server, not in a skill
  file that can drift out of sync. When the API changes, the agent
  automatically discovers the new schema.

- **Most token-efficient under full access.** tooluse-discovery-full used
  92,787 tokens — the lowest of all three methods, even beating baked
  instructions (100,254). The structured format requires less back-and-forth.

- **Better degradation than OpenAPI under restricted policy.** When blocked,
  tooluse-restricted used 205k tokens across 19 turns vs. openapi-restricted's
  534k across 28 turns. The simpler `/tools.json` format produces less
  confusion during fallback.

- **OpenAPI is overkill for agent consumption.** OpenAPI specs are designed for
  code generators and documentation tools, not for LLM agents. The verbose
  nested structure adds context tokens without proportional benefit. Tool-use
  schemas are purpose-built for agent consumption.

**For restricted policies**, the recommendation is to combine both: serve
`/tools.json` for runtime discovery, and bake the same schema into a fallback
skill. This way the agent uses live discovery when available and falls back to
baked instructions when the discovery endpoint is blocked.

#### Server process contract for `api_servers` in harness definitions

The experiment validates the `api_servers` field from ADR-0024 (currently
planned, not yet implemented) and establishes a concrete process contract.
Every host-side API server managed by the runner should:

1. Accept `--port` and `--token` CLI flags
2. Serve `GET /healthz` (unauthenticated) for runner readiness checks
3. Serve `GET /tools.json` (unauthenticated or authenticated) for agent
   discovery
4. Handle `SIGTERM` for graceful shutdown
5. Accept a `sandbox` field in request bodies for file transfer operations
6. Use `openshell sandbox download/upload` for host-sandbox file exchange

The runner manages the full lifecycle: start, health-check, token injection
via provider, policy rendering, and cleanup on exit.

#### Server definitions belong in the harness, not a separate config file

The original experiment used a separate `servers.json` file to declare server
binaries, ports, and arguments — read by a Go orchestrator that started them.
This was replaced by hardcoded server commands in `run.sh`, which works for
a fixed experiment but doesn't generalize.

For production, server definitions should live in the harness YAML's
`api_servers` field (ADR-0024), where the runner can read them declaratively:

```yaml
api_servers:
  - name: builder
    command: bin/builder-server
    port: 9090
    env:
      TOKEN: ${API_TOKEN}
  - name: provisioner
    command: python3 servers/repo-provisioner/server.py
    port: 9091
    env:
      TOKEN: ${API_TOKEN}
```

This gives the runner everything it needs to start each server (`command`,
`port`), pass credentials (`env` with `${VAR}` expansion), health-check
(`/healthz` on the declared port), and tear down (`SIGTERM` to the process).
No separate config file, no hardcoded commands — the harness is the single
source of truth for what infrastructure an agent needs.

#### Provider-based auth over direct token injection

Using OpenShell's `generic` provider type with credential placeholders is
preferable to passing real tokens into the sandbox via env files. The
experiment confirms this works end-to-end: the agent uses the placeholder
transparently, and the proxy resolves it in `Authorization` headers without
the real token ever being accessible inside the sandbox.

#### API servers must bind to all interfaces (`0.0.0.0`)

The L7 proxy runs inside the sandbox container (as part of the
`openshell-sandbox` supervisor process), not as a host-side process. When the
proxy forwards a request to a host-side API server, it connects from inside
the container network namespace. This means API servers bound to `127.0.0.1`
are unreachable — the proxy sees the container's loopback, not the host's.

On rootless Podman, the container bridge gateway IP (e.g., `10.88.0.1`) lives
inside the container namespace and cannot be bound to from the host — `bind()`
fails with `EADDRNOTAVAIL`. The only option is `0.0.0.0`, which exposes the
servers on all network interfaces.

This is a security trade-off: on shared hosts (e.g., GitHub Actions runners),
other processes can probe the API server ports. Bearer token authentication
mitigates this, but the attack surface is unnecessarily wide. The
`--bind-address` flag added to both servers defaults to `127.0.0.1` (secure
by default) and the orchestrator explicitly passes `0.0.0.0` when needed.

The root cause is architectural: the supervisor proxy connects from inside
the container, not from the host. If the supervisor could proxy to
`127.0.0.1` on the host side (generalizing the existing `inference.local`
mechanism), API servers could bind to loopback and never be network-exposed.
This has been filed as
[NVIDIA/OpenShell#1633](https://github.com/NVIDIA/OpenShell/issues/1633).

#### Hostname-based URLs, not IPs

All URLs delivered into the sandbox must use `host.openshell.internal`, never
raw IPs. The L7 proxy matches requests by hostname, and SSRF protection blocks
private IP addresses.

### 2026-07-16: `allowed_ips` no longer required for declared endpoints

OpenShell maintainer johntmyers
[confirmed](https://github.com/NVIDIA/OpenShell/issues/1633#issuecomment-1)
that [PR #1560](https://github.com/NVIDIA/OpenShell/pull/1560) removed the
`allowed_ips` requirement when endpoints are explicitly declared with host+port
in the policy.

**Validation (OpenShell v0.0.83, rootless Podman + pasta, Fedora 44 kernel 7.0.9):**

| Endpoint | Port | Policy has `allowed_ips`? | Result from sandbox |
|----------|------|--------------------------|---------------------|
| builder `/tools.json` | 9090 | No | 200 OK |
| provisioner `/tools.json` | 9091 | No | 200 OK |
| `example.com` (not in policy) | 80 | N/A | Blocked |

**What changed:**
- Removed `allowed_ips: ["{{HOST_IP}}/32"]` from both policies
- Removed HOST_IP resolution and policy template rendering from `run.sh`
- Harness files now reference raw policy files directly (no rendered copies)

**Implications:**
- The `{{HOST_IP}}` templating step was the most fragile part of the setup
  (platform-dependent IP resolution, sed rendering, separate rendered files).
  Its removal simplifies the orchestrator significantly.
- Servers still bind to `0.0.0.0` — the remaining motivation for
  [NVIDIA/OpenShell#1633](https://github.com/NVIDIA/OpenShell/issues/1633)
  is eliminating `0.0.0.0` binding in favor of `127.0.0.1` via supervisor-proxied
  `host.local` endpoints.
