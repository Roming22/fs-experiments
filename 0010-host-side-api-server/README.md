---
title: "10. Host-side API server for sandboxed agents"
status: Concluded
topics:
  - sandbox
  - tooling
---

# 10. Host-side API server for sandboxed agents

Tracking issue: [fullsend-ai/experiments#25](https://github.com/fullsend-ai/experiments/issues/25)

## What this experiment covers

1. **Basic API server lifecycle** — two API servers started by the
   orchestrator, callable from inside an OpenShell sandbox via the L7 proxy
2. **Credential isolation** — servers hold credentials internally, agents
   never see them
3. **Container build delegation** — Go server builds images via podman
   on the host, working around OpenShell's seccomp restrictions
4. **API discoverability** — three approaches compared: OpenAPI spec,
   tool-use schema, baked-in agent instructions
5. **Per-run auth** — UUID bearer token generated per run
6. **Long-running operations** — container builds that exceed MCP timeout
7. **L7 policy tuning** — most restrictive policy that allows the API

## Architecture

See [design spec](superpowers/2026-05-14-host-side-api-server-design.md).

## Quick start

See [HOW_TO.md](HOW_TO.md).

## Key design decisions

- **Two servers in different languages** (Go + Python) to validate the
  language-agnostic process contract
- **Uniform process contract**: `--port`, `--token`, `/healthz`, SIGTERM
- **Repo provisioner depends on OpenShell#1272**: if content inspection hooks
  ship in OpenShell, the scan-before-copy flow could be handled natively

## Changelog

### 2026-07-16: Remove `allowed_ips` requirement

OpenShell maintainer [johntmyers confirmed](https://github.com/NVIDIA/OpenShell/issues/1633#issuecomment-1)
that PR [NVIDIA/OpenShell#1560](https://github.com/NVIDIA/OpenShell/pull/1560) removed
the `allowed_ips` requirement when endpoints are explicitly declared with host+port in
the policy. Validated locally on OpenShell v0.0.83 (rootless Podman + pasta, Fedora 44):

- Both builder (`:9090`) and provisioner (`:9091`) reachable from sandbox without `allowed_ips`
- Undeclared endpoints still blocked by the proxy

Changes:
- Removed `allowed_ips: ["{{HOST_IP}}/32"]` from both policies
- Removed HOST_IP resolution and policy template rendering from `run.sh`
- Harness files now reference raw policies directly (no rendered copies)
- Added `role: experiment` to all harness files (required by current fullsend)

Servers still bind to `0.0.0.0` — the remaining motivation for
[NVIDIA/OpenShell#1633](https://github.com/NVIDIA/OpenShell/issues/1633) (`host.local`
supervisor-proxied endpoints) is eliminating `0.0.0.0` binding in favor of `127.0.0.1`.

## Findings

See [results/findings.md](results/findings.md) (populated after running).
