---
title: "26. Statistical significance for non-deterministic evals"
status: Concluded
topics:
  - evaluation
  - testing
---

# 26. Statistical significance for non-deterministic evals

**Relates to:** [fullsend-ai/fullsend#2460](https://github.com/fullsend-ai/fullsend/issues/2460) · `testing-agents.md` open question #1 · `0016-promptfoo-eval` · `0006-code-agent-evaluation`

## Hypothesis

A small, dependency-free statistical layer can supply the "threshold wrapper"
that `promptfoo-eval` flagged as missing, and — applied to the conclusions in
`code-agent-evaluation` — will show that comparisons reported as "within noise"
or "statistically equivalent" were underpowered at the trial counts used: the
experiment could not have detected those differences either way.

## Background

Two existing experiments establish the gap:

- **promptfoo-eval** — *"For statistical thresholds ('pass if 90% succeed'), you
  need a script that parses the JSON output and computes the pass rate. This is
  ~20 lines of code but it's custom."* and *"The real non-determinism test
  requires temperature>0 and statistical thresholds, which we didn't exercise."*
- **code-agent-evaluation** — draws conclusions in statistical language
  (*"within noise for 60 trials"*, *"statistically equivalent"*, *"small sample
  size (6 trials)… suggestive, not conclusive"*) without a significance test or
  power analysis behind them.

Neither ships a reusable utility, and neither answers the underlying question:
*how many noisy trials do you need before an eval delta is a real signal?*

## Method

1. Build `significance.py` (standard library only):
   - **Binary gates:** Wilson score interval + a `threshold_test` that gates on
     the lower confidence bound.
   - **Continuous judge scores:** percentile `bootstrap_ci` + `compare_means`
     (bootstrap difference-of-means), which doubles as the mutation
     kill/survive decision rule.
   - **Planning:** `min_trials_for_proportion` / `min_trials_for_mean` — given a
     target effect, α and power, the trials/arm required.
2. Ship `threshold_check.py` — a CI-pluggable CLI that parses promptfoo results
   JSON and exits 0/1 against a statistical threshold.
3. Re-examine `code-agent-evaluation`'s conclusions at its stated trial counts
   and produce sizing tables across a plausible σ range (raw per-trial scores
   are not published, so σ is spanned, not assumed).

## Deliverables

| File | What it is |
|---|---|
| `significance.py` | Wilson/bootstrap CIs, `compare_means`, min-trials calculators. Stdlib only. |
| `threshold_check.py` | CLI: promptfoo JSON → pass/fail against a statistical threshold. |
| `test_significance.py` | 24 unit tests, incl. the four triage requested on #2460. `python -m unittest`. |
| `fixtures/promptfoo_sample.json` | 19/20 sample results for the CLI test. |
| `RECOMMENDATION.md` | The power tables, the re-examination, and recommended defaults. |

## Results

- **The four triage-requested checks pass**, including
  `min_trials_for_proportion(0.95, 0.10) == 141` (trials/arm to detect a
  10-point drop from a 95% baseline at α=0.05, power=0.80).
- **The gating point is concrete:** 19/20 (95%) *fails* a 90% target — its 95%
  CI is [76.4%, 99.1%] — while 190/200 at the same rate passes. Same rate,
  opposite verdict.
- **A power lens on `code-agent-evaluation`:** the "V8 ≈ V5/V7" comparison rests
  on a ~0.04 judge-score delta at 3 trials/cell. Across any plausible judge
  noise (σ ∈ [0.1, 1.0] → ~100 to ~9,800 trials/arm), that is underpowered — by
  an amount we can't pin, since raw per-trial scores aren't published and their
  design is paired-by-scenario while our calculator is unpaired (so our figures
  are an upper bound). Their hedged language ("within noise," "suggestive") is
  correct; only *"statistically equivalent"* reaches past the data, since
  non-detection isn't equivalence. Full treatment in
  [`RECOMMENDATION.md`](RECOMMENDATION.md).

## How to run

```bash
cd 0026-eval-statistical-significance
python -m unittest -v                                   # 24 tests, no install
python threshold_check.py fixtures/promptfoo_sample.json --target 0.90  # -> FAIL, exit 1
python threshold_check.py fixtures/promptfoo_sample.json --target 0.70  # -> PASS, exit 0
```

## Limitations

- **No raw per-trial data published**, so judge-score variance is spanned across
  σ ∈ {0.3, 0.5, 0.8} rather than measured. The power *statements* ("could not
  have detected 0.04 at 3 trials") hold across that whole range; only the exact
  trial counts move with σ. The harness ingests real logs unchanged if they
  surface.
- Scope is single-cell and pairwise. Multiple-comparison correction across the
  full scenario×variant grid is noted as follow-up, not built here.
- Bootstrap/coverage tests are seeded for determinism; they assert coverage
  bands, not exact values.

## Follow-on

This is step 1. A mutation harness (the `muteval` approach) is the documented
next step — it needs `compare_means` to decide killed vs. survived on a noisy
eval. Tracked separately, not in this experiment.
