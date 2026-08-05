# fullsend experiments

Experiments for the fullsend platform — each tests a hypothesis about autonomous agent infrastructure, security, tooling, or workflows.

## Experiments

| # | Experiment | Status |
|---|-----------|--------|
| 0001 | [Agent outage fire drill](0001-agent-outage-fire-drill.md) | Active |
| 0002 | [Claude-based ADR drift scanner](0002-claude-scanner/) | Concluded |
| 0003 | [ADR-0046 drift scanner](0003-scanner/) | Concluded |
| 0004 | [Zero-config autonomous bug fix engine](0004-meta-loop-self-improving-engine/) | Concluded |
| 0005 | [Agent scoped tools triage](0005-agent-scoped-tools-triage/) | Concluded |
| 0006 | [Code agent evaluation](0006-code-agent-evaluation/) | Concluded |
| 0007 | [GitHub Actions agent runtime MVP](0007-github-actions-agent-runtime-mvp/) | Concluded |
| 0008 | [Guardrails evaluation](0008-guardrails-eval/) | Concluded |
| 0009 | [Hermes-inspired security patterns](0009-hermes-security-patterns/) | Concluded |
| 0010 | [Host-side API server for sandboxed agents](0010-host-side-api-server/) | Concluded |
| 0011 | [Integration Service design doc drift](0011-integration-service-design-drift/) | Concluded |
| 0012 | [Model Armor vs AI agent triage](0012-model-armor-vs-agent-triage/) | Concluded |
| 0013 | [OpenShell policy bypass](0013-openshell-policy-bypass/) | Concluded |
| 0014 | [OpenShell sandbox evaluation](0014-openshell-sandbox-evaluation.md) | Concluded |
| 0015 | [Prompt injection defense-in-depth](0015-prompt-injection-defense/) | Concluded |
| 0016 | [Promptfoo for agent evaluation in CI](0016-promptfoo-eval/) | Concluded |
| 0017 | [Reasoning monitor](0017-reasoning-monitor/) | Active |
| 0018 | [Runner hello world](0018-runner-hello-world/) | Active |
| 0019 | [Skills](0019-skills/) | Active |
| 0020 | [Target repository skills in triage](0020-target-repo-skills/) | Concluded |
| 0021 | [Tool scoping](0021-tool-scoping/) | Concluded |
| 0022 | [Claude GitHub App auth](0022-claude-github-app-auth/) | Concluded |
| 0023 | [Review cache publication policy](0023-review-cache/) | Concluded |
| 0024 | [CODEOWNERS + GitHub App approval matrix](0024-codeowners-app-matrix/) | Concluded |
| 0025 | [Subagent process isolation via PreToolUse hooks](0025-subagent-process-isolation/) | Active |

## Conventions

Experiments follow a numbered directory convention. See [AGENTS.md](AGENTS.md) for full details.

- **Naming:** `NNNN-short-description/` (zero-padded 4-digit number)
- **Frontmatter:** YAML with `title`, `status`, and optional `topics`
- **Statuses:** Active, Concluded, Abandoned, Merged
- **Template:** [0000-experiment-template](0000-experiment-template/)
- **Linting:** `hack/lint-experiment-numbers` and `hack/lint-experiment-frontmatter` enforce conventions via pre-commit
