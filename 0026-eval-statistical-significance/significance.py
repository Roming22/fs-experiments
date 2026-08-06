"""Statistical significance utilities for non-deterministic agent evals.

Answers `testing-agents.md` open question #1: "What's the right statistical
threshold for non-deterministic tests? How many runs constitute a reliable
signal, and what pass rate is acceptable?"

Two eval shapes are supported:

* **Binary gates** ("did the agent resist the injection?") -> proportions.
  Use `wilson_interval` and `threshold_test`.
* **Continuous judge scores** (a 1-5 LLM-as-judge rubric) -> means.
  Use `bootstrap_ci` and `compare_means`.

`min_trials_for_proportion` / `min_trials_for_mean` answer the planning
question in the other direction: given an effect you care about detecting,
how many trials per cell do you actually need?

Standard library only, by design -- this is meant to drop into a CI job with
no install step. deepeval offers confidence intervals and sample-size
calculation inside its own metric framework; this module is deliberately
framework-agnostic so it can score promptfoo, Inspect AI, or raw JSON, and
`compare_means` adds the mutation kill/survive decision that generic eval
stats do not provide.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from statistics import mean as _mean
from typing import Callable, Sequence

__all__ = [
    "norm_ppf",
    "wilson_interval",
    "bootstrap_ci",
    "threshold_test",
    "compare_means",
    "min_trials_for_proportion",
    "min_trials_for_mean",
    "ThresholdResult",
    "ComparisonResult",
]


# --------------------------------------------------------------------------
# Normal quantile
# --------------------------------------------------------------------------

# Acklam's rational approximation to the inverse standard normal CDF.
# Relative error < 1.15e-9 across the open interval (0, 1).
_A = (-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
      1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00)
_B = (-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
      6.680131188771972e01, -1.328068155288572e01)
_C = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
      -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00)
_D = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
      3.754408661907416e00)

_P_LOW = 0.02425
_P_HIGH = 1.0 - _P_LOW


def norm_ppf(p: float) -> float:
    """Inverse CDF (quantile function) of the standard normal distribution."""
    if not 0.0 < p < 1.0:
        raise ValueError(f"p must be in (0, 1), got {p!r}")

    if p < _P_LOW:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / \
               ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0)

    if p > _P_HIGH:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5]) / \
                ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0)

    q = p - 0.5
    r = q * q
    return (((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5]) * q / \
           (((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1.0)


def _z_two_sided(confidence: float) -> float:
    """z for a two-sided interval at the given confidence (0.95 -> 1.95996)."""
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be in (0, 1), got {confidence!r}")
    return norm_ppf(1.0 - (1.0 - confidence) / 2.0)


# --------------------------------------------------------------------------
# Binary gates -> proportions
# --------------------------------------------------------------------------

def wilson_interval(successes: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Preferred over the normal-approximation ("Wald") interval, which badly
    undercovers at the extreme pass rates agent evals typically live at
    (e.g. 19/20). Returns (lower, upper), both clamped to [0, 1].
    """
    if n <= 0:
        raise ValueError(f"n must be positive, got {n!r}")
    if not 0 <= successes <= n:
        raise ValueError(f"successes must be in [0, {n}], got {successes!r}")

    z = _z_two_sided(confidence)
    p_hat = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p_hat + z2 / (2.0 * n)) / denom
    margin = (z / denom) * math.sqrt(p_hat * (1.0 - p_hat) / n + z2 / (4.0 * n * n))
    return max(0.0, center - margin), min(1.0, center + margin)


@dataclass(frozen=True)
class ThresholdResult:
    """Outcome of gating a pass rate against a target."""

    passed: bool
    observed_rate: float
    lower_bound: float
    upper_bound: float
    target_rate: float
    n: int
    confidence: float = 0.95

    def __str__(self) -> str:  # pragma: no cover - display only
        verdict = "PASS" if self.passed else "FAIL"
        return (
            f"{verdict}: {self.observed_rate:.1%} observed over {self.n} trials "
            f"({self.confidence:.0%} CI [{self.lower_bound:.1%}, {self.upper_bound:.1%}], "
            f"target {self.target_rate:.1%})"
        )


def threshold_test(
    successes: int,
    n: int,
    target_rate: float,
    confidence: float = 0.95,
) -> ThresholdResult:
    """Gate a binary eval on a target pass rate, accounting for sample size.

    Passes only when the *lower* bound of the confidence interval clears the
    target. This is the conservative choice: 19/20 successes has a point
    estimate of 95%, but its 95% CI reaches down to ~76% -- not enough
    evidence to certify a 90% target. Ten times the trials at the same rate
    would clear it.
    """
    if not 0.0 <= target_rate <= 1.0:
        raise ValueError(f"target_rate must be in [0, 1], got {target_rate!r}")

    lower, upper = wilson_interval(successes, n, confidence)
    return ThresholdResult(
        passed=lower >= target_rate,
        observed_rate=successes / n,
        lower_bound=lower,
        upper_bound=upper,
        target_rate=target_rate,
        n=n,
        confidence=confidence,
    )


# --------------------------------------------------------------------------
# Continuous judge scores -> means
# --------------------------------------------------------------------------

def bootstrap_ci(
    samples: Sequence[float],
    confidence: float = 0.95,
    iterations: int = 10_000,
    statistic: Callable[[Sequence[float]], float] = _mean,
    seed: int | None = None,
) -> tuple[float, float]:
    """Percentile bootstrap confidence interval for an arbitrary statistic.

    Makes no normality assumption, which matters for bounded judge scales
    (1-5) where the sampling distribution is skewed near the ceiling.

    `seed` is required for reproducible CI runs; leave it None for analysis.
    """
    if len(samples) < 2:
        raise ValueError("need at least 2 samples to bootstrap")
    if iterations < 1:
        raise ValueError(f"iterations must be positive, got {iterations!r}")
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be in (0, 1), got {confidence!r}")

    rng = random.Random(seed)
    n = len(samples)
    resampled = [
        statistic([samples[rng.randrange(n)] for _ in range(n)])
        for _ in range(iterations)
    ]
    resampled.sort()

    alpha = 1.0 - confidence
    lo_idx = int(math.floor((alpha / 2.0) * iterations))
    hi_idx = min(int(math.ceil((1.0 - alpha / 2.0) * iterations)) - 1, iterations - 1)
    return resampled[lo_idx], resampled[hi_idx]


@dataclass(frozen=True)
class ComparisonResult:
    """Outcome of comparing two arms (e.g. baseline vs mutant)."""

    significant: bool
    difference: float
    lower_bound: float
    upper_bound: float
    n_a: int
    n_b: int
    confidence: float = 0.95

    def __str__(self) -> str:  # pragma: no cover - display only
        verdict = "SIGNIFICANT" if self.significant else "NOT SIGNIFICANT"
        return (
            f"{verdict}: difference {self.difference:+.3f} "
            f"({self.confidence:.0%} CI [{self.lower_bound:+.3f}, {self.upper_bound:+.3f}], "
            f"n={self.n_a} vs {self.n_b})"
        )


def compare_means(
    a: Sequence[float],
    b: Sequence[float],
    confidence: float = 0.95,
    iterations: int = 10_000,
    seed: int | None = None,
) -> ComparisonResult:
    """Bootstrap the difference of means between two arms.

    A difference is called significant when the confidence interval on
    `mean(b) - mean(a)` excludes zero.

    This is the seed of the decision rule mutation testing needs: `a` is the
    unmutated baseline, `b` is the mutant. A significant drop means the eval
    suite noticed the injected fault -- the mutant is killed.

    PROVISIONAL: a non-significant difference is NOT proof the mutant survived --
    at low trial counts it is usually just underpowered (the equivalence
    fallacy). And a "kill" only cares about a drop, so a one-sided test is more
    appropriate. Hardening this into a real kill/survive rule (one-sided, with an
    explicit inconclusive verdict) is the mutation follow-on's job, not v1's.
    """
    if len(a) < 2 or len(b) < 2:
        raise ValueError("need at least 2 samples per arm")
    if iterations < 1:
        raise ValueError(f"iterations must be positive, got {iterations!r}")
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be in (0, 1), got {confidence!r}")

    rng = random.Random(seed)
    n_a, n_b = len(a), len(b)
    diffs = []
    for _ in range(iterations):
        boot_a = _mean([a[rng.randrange(n_a)] for _ in range(n_a)])
        boot_b = _mean([b[rng.randrange(n_b)] for _ in range(n_b)])
        diffs.append(boot_b - boot_a)
    diffs.sort()

    alpha = 1.0 - confidence
    lo_idx = int(math.floor((alpha / 2.0) * iterations))
    hi_idx = min(int(math.ceil((1.0 - alpha / 2.0) * iterations)) - 1, iterations - 1)
    lower, upper = diffs[lo_idx], diffs[hi_idx]

    return ComparisonResult(
        significant=(lower > 0.0) or (upper < 0.0),
        difference=_mean(b) - _mean(a),
        lower_bound=lower,
        upper_bound=upper,
        n_a=n_a,
        n_b=n_b,
        confidence=confidence,
    )


# --------------------------------------------------------------------------
# Planning: how many trials do we actually need?
# --------------------------------------------------------------------------

def min_trials_for_proportion(
    baseline_rate: float,
    effect_size: float,
    alpha: float = 0.05,
    power: float = 0.80,
) -> int:
    """Trials *per arm* needed to detect a drop of `effect_size` in a pass rate.

    Two-proportion, two-sided test. `effect_size` is expressed in absolute
    percentage points: detecting a 10-point drop from a 95% baseline is
    `min_trials_for_proportion(0.95, 0.10)`.

    The answer is sobering, and that is the point: the number is far larger
    than the 3-trials-per-cell that agent evals typically run.
    """
    if not 0.0 < baseline_rate < 1.0:
        raise ValueError(f"baseline_rate must be in (0, 1), got {baseline_rate!r}")
    if not 0.0 < effect_size < baseline_rate:
        raise ValueError(f"effect_size must be in (0, {baseline_rate}), got {effect_size!r}")

    p1 = baseline_rate
    p2 = baseline_rate - effect_size
    p_bar = (p1 + p2) / 2.0

    z_alpha = norm_ppf(1.0 - alpha / 2.0)
    z_power = norm_ppf(power)

    numerator = (
        z_alpha * math.sqrt(2.0 * p_bar * (1.0 - p_bar))
        + z_power * math.sqrt(p1 * (1.0 - p1) + p2 * (1.0 - p2))
    ) ** 2
    return math.ceil(numerator / (effect_size ** 2))


def min_trials_for_mean(
    std_dev: float,
    effect_size: float,
    alpha: float = 0.05,
    power: float = 0.80,
) -> int:
    """Trials *per arm* needed to detect a shift of `effect_size` in a mean.

    Two-sample, two-sided, equal-variance, normal approximation (uses z, not t,
    so it slightly understates n for small samples). It also assumes independent
    arms; a paired design needs fewer trials, so treat this as an upper bound
    there. Even so, on a 1-5 judge scale a sub-0.1 delta needs hundreds to
    thousands of trials per arm -- far more than the 3 typically run.
    """
    if std_dev <= 0.0:
        raise ValueError(f"std_dev must be positive, got {std_dev!r}")
    if effect_size <= 0.0:
        raise ValueError(f"effect_size must be positive, got {effect_size!r}")

    z_alpha = norm_ppf(1.0 - alpha / 2.0)
    z_power = norm_ppf(power)
    return math.ceil(2.0 * ((z_alpha + z_power) ** 2) * (std_dev ** 2) / (effect_size ** 2))
