# Recommendation: statistical thresholds for non-deterministic evals

Provides machinery and defaults for `testing-agents.md` open question #1 —
*"What's the right statistical threshold for non-deterministic tests? How many
runs constitute a reliable signal, and what pass rate is acceptable?"* — with
numbers you can put in a CI config. It does not settle the policy half of the
question ("what pass rate is acceptable" is a risk decision, not a statistic);
it gives the calculator and conventional α/power defaults, and applies a power
*lens* to the conclusions in `code-agent-evaluation`.

All figures below are produced by `significance.py` (`python -m unittest` for
the checks that pin them). Reproduce the tables with the snippet at the end.

## 1. Binary gates: how many trials before a pass rate is evidence?

There are two distinct questions here, and they have different sample sizes —
worth separating cleanly:

**(a) Detecting a regression (two-sample).** "Has the pass rate dropped from its
baseline?" compares two arms. Trials *per arm* to detect a given drop from a 95%
baseline (α=0.05, power=0.80, two-sided, via `min_trials_for_proportion`):

| Drop to detect from a 95% baseline | Trials/arm |
|---|---|
| 5 points (95% → 90%) | 435 |
| 10 points (95% → 85%) | 141 |
| 15 points (95% → 80%) | 76 |
| 20 points (95% → 75%) | 49 |

**(b) Certifying a floor (one-sample).** "Is the true rate at least 90%?" is a
single-arm question, and it's what `threshold_test` answers via the lower Wilson
bound — no second arm involved. Here 95% observed against a 90% target:

```
threshold_test(19,  20,  0.90)  ->  FAIL  (95% CI [76.4%, 99.1%])
threshold_test(190, 200, 0.90)  ->  PASS  (95% CI [91.0%, 97.3%])
```

Identical pass rate, opposite verdict. 19/20 *looks* like it clears 90%, but
its interval reaches down to 76%. **Recommendation:** gate on the lower
confidence bound, not the point estimate, and size the suite to the smallest
regression you care about (≈140 trials/arm to catch a 10-point drop).

## 2. Judge-score gates: the small-delta trap

For a 1–5 LLM-as-judge score, the trials needed to detect a mean difference
depend on the run-to-run standard deviation. Because per-trial judge scores
aren't published anywhere in this repo, the table spans a plausible σ range
rather than asserting one value:

| Delta to detect | σ=0.3 | σ=0.5 | σ=0.8 |
|---|---|---|---|
| 0.04 | 883 | 2,453 | 6,280 |
| 0.10 | 142 | 393 | 1,005 |
| 0.20 | 36 | 99 | 252 |
| 0.40 | 9 | 25 | 63 |

The dependence on the *square* of the effect is the whole story: halving the
delta you want to catch quadruples the trials. Sub-0.1 deltas are effectively
undetectable at any trial count a per-PR CI job can afford.

## 3. A power lens on `code-agent-evaluation`

This is a lens, not a verdict — and two honest caveats bound it, because the
raw per-trial scores aren't published:

1. **σ is unknown.** The trials needed for a 0.04 delta swing enormously with the
   judge's run-to-run noise: ~100 at σ=0.1, ~2,450 at σ=0.5, ~9,800 at σ=1.0.
   So we can say the direction (underpowered) but not a precise magnitude.
2. **The design is paired; our calculator is not.** That experiment compares
   variants on the *same* 20 scenarios, which a proper analysis would pair by
   scenario (cancelling between-scenario variance and needing *fewer* trials).
   Our unpaired `min_trials_for_mean` therefore gives an **upper bound** on the
   trials required, not the exact figure.

With those bounds stated: that experiment ran **3 trials per cell** and drew
conclusions from judge-score deltas of 0.02–0.40. Across any plausible σ, a
0.04 delta needs far more than 3 trials/arm to detect — so the comparison
behind *"V8 is statistically equivalent to V5/V7"* was underpowered, by an
amount we can't pin without the raw data.

The takeaway isn't "their conclusions are wrong." Their hedged language
("within noise," "suggestive, not conclusive") is **correct and appropriate**.
The only phrase that reaches past the data is *"statistically equivalent"* —
because failing to detect a difference is not the same as demonstrating
equivalence (that needs an equivalence test like TOST against a pre-specified
margin). The point of a significance layer is to make that distinction visible
*before* the claim is written — which is exactly what it would do here.

## 4. Recommended defaults

- **Binary gates:** gate on the lower Wilson bound; size to ~140 trials/arm for
  a 10-point detectable drop. Fewer trials only certify larger regressions —
  state that explicitly rather than implying tighter sensitivity.
- **Judge-score gates:** measure σ first (a handful of repeated runs), then use
  `min_trials_for_mean` to size the suite. Do not compare deltas below ~0.1
  unless you can afford hundreds of trials/arm. Never assert equivalence from a
  non-significant difference without an equivalence test.
- **Cadence:** this rigor is affordable per-release, not per-commit. Run the
  cheap prompt-regression layer on every change; run the powered gate
  periodically.

## 5. Why this is the prerequisite for mutation testing

`testing-agents.md` lists mutation testing (Approach 4) as the way to measure
whether a golden set would catch a silent capability loss. On a
non-deterministic eval you cannot label a mutant "killed" without a decision of
the form `compare_means` implements: is the score drop under mutation larger
than run-to-run noise? Without it, mutation scores measure randomness. This
layer is step 1; a mutation harness (the `muteval` approach) is the documented
follow-on that builds on it.

**`compare_means` is provisional in v1**, and two limits keep it from being
load-bearing yet: it is two-sided (a mutation "kill" only cares about a *drop*,
so a one-sided test is more appropriate), and a non-significant result must not
be read as a definite "survived" — at low trial counts that is just the
underpowered case, the same equivalence fallacy §3 warns about. Hardening it
(one-sided, with an explicit "underpowered / inconclusive" verdict) is the
first task of the mutation follow-on, not this experiment.

## Relationship to existing tools

deepeval already offers confidence intervals and sample-size calculation, and
statsmodels/scipy implement all of the underlying tests. This module does not
claim to out-stat them. What it offers is packaging for a specific niche: it is
standard-library-only so it drops into a CI job with no install, and it is
framework-agnostic (scores promptfoo/Inspect JSON rather than living inside one
metric framework). Where a project already runs deepeval, its interval and
sample-size machinery is a fine substitute for §1–§2 — use it. The parts that
are genuinely additive here are the framework-agnostic `threshold_check` gate
and the mutation kill/survive decision (§5), and the latter is still
provisional.

---

*Reproduce the tables:*

```python
import significance as s
for eff in (0.05, 0.10, 0.15, 0.20):
    print(eff, s.min_trials_for_proportion(0.95, eff))
for delta in (0.04, 0.10, 0.20, 0.40):
    print(delta, [s.min_trials_for_mean(sd, delta) for sd in (0.3, 0.5, 0.8)])
```
