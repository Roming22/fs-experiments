"""Unit tests for the significance layer.

Covers the four cases the triage bot asked for on fullsend-ai/fullsend#2460:

1. Wilson CI contains the true proportion for known binomial samples
2. Bootstrap CI achieves nominal coverage on synthetic normal data
3. Power calculator returns correct minimum n for a known effect size
   (detect a 10-point drop from a 95% baseline, alpha=0.05, power=0.80)
4. Threshold wrapper parses sample promptfoo JSON and emits pass/fail
   matching a manual calculation

...plus quantile accuracy and input-validation tests. Standard library only;
run with `python -m unittest` -- no install step.
"""

from __future__ import annotations

import json
import os
import random
import unittest

import significance as s
import threshold_check as tc

_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "promptfoo_sample.json")


class TestNormPpf(unittest.TestCase):
    def test_known_quantiles(self):
        self.assertAlmostEqual(s.norm_ppf(0.5), 0.0, places=6)
        self.assertAlmostEqual(s.norm_ppf(0.975), 1.959964, places=5)
        self.assertAlmostEqual(s.norm_ppf(0.80), 0.841621, places=5)
        self.assertAlmostEqual(s.norm_ppf(0.025), -1.959964, places=5)

    def test_symmetry(self):
        for p in (0.01, 0.1, 0.3, 0.45):
            self.assertAlmostEqual(s.norm_ppf(p), -s.norm_ppf(1.0 - p), places=6)

    def test_domain(self):
        for bad in (0.0, 1.0, -0.1, 1.5):
            with self.assertRaises(ValueError):
                s.norm_ppf(bad)


class TestWilsonInterval(unittest.TestCase):
    def test_known_value(self):
        # 19/20 at 95%: hand-computed interval.
        lo, hi = s.wilson_interval(19, 20, 0.95)
        self.assertAlmostEqual(lo, 0.763869, places=5)
        self.assertAlmostEqual(hi, 0.991119, places=5)

    def test_contains_true_proportion(self):
        # Triage test #1: Wilson coverage on known binomial samples.
        # Simulate many binomial draws; the 95% interval should contain the
        # true p at roughly nominal rate. Seeded, so this is deterministic.
        rng = random.Random(20260619)
        true_p, n, trials = 0.8, 60, 2000
        covered = 0
        for _ in range(trials):
            successes = sum(1 for _ in range(n) if rng.random() < true_p)
            lo, hi = s.wilson_interval(successes, n, 0.95)
            if lo <= true_p <= hi:
                covered += 1
        coverage = covered / trials
        # Wilson slightly over-covers; expect comfortably >= 0.93.
        self.assertGreaterEqual(coverage, 0.93)
        self.assertLessEqual(coverage, 0.99)

    def test_bounds_clamped(self):
        lo, hi = s.wilson_interval(20, 20, 0.95)
        self.assertLessEqual(hi, 1.0)
        self.assertGreaterEqual(lo, 0.0)
        lo, hi = s.wilson_interval(0, 20, 0.95)
        self.assertGreaterEqual(lo, 0.0)

    def test_validation(self):
        with self.assertRaises(ValueError):
            s.wilson_interval(5, 0)
        with self.assertRaises(ValueError):
            s.wilson_interval(21, 20)


class TestBootstrapCI(unittest.TestCase):
    def test_nominal_coverage(self):
        # Triage test #2: bootstrap CI coverage on synthetic normal data.
        rng = random.Random(0xC0FFEE)
        true_mu, sigma, n, trials = 3.5, 0.5, 50, 300
        covered = 0
        for i in range(trials):
            sample = [rng.gauss(true_mu, sigma) for _ in range(n)]
            lo, hi = s.bootstrap_ci(sample, 0.95, iterations=1500, seed=i)
            if lo <= true_mu <= hi:
                covered += 1
        coverage = covered / trials
        # Percentile bootstrap at n=50 should land near 0.95; allow slack.
        self.assertGreaterEqual(coverage, 0.90)
        self.assertLessEqual(coverage, 0.99)

    def test_reproducible_with_seed(self):
        sample = [1.0, 2.0, 3.0, 4.0, 5.0, 4.0, 3.0, 2.0]
        self.assertEqual(
            s.bootstrap_ci(sample, seed=42, iterations=1000),
            s.bootstrap_ci(sample, seed=42, iterations=1000),
        )

    def test_validation(self):
        with self.assertRaises(ValueError):
            s.bootstrap_ci([1.0])
        with self.assertRaises(ValueError):
            s.bootstrap_ci([1.0, 2.0], iterations=0)
        for bad in (0.0, 1.0, 1.5):
            with self.assertRaises(ValueError):
                s.bootstrap_ci([1.0, 2.0], confidence=bad)


class TestCompareMeans(unittest.TestCase):
    def test_detects_real_drop(self):
        # A large, clean separation must be called significant.
        rng = random.Random(1)
        baseline = [rng.gauss(4.5, 0.3) for _ in range(40)]
        mutant = [rng.gauss(3.0, 0.3) for _ in range(40)]
        res = s.compare_means(baseline, mutant, seed=7)
        self.assertTrue(res.significant)
        self.assertLess(res.difference, 0.0)  # mutant scored lower -> killed

    def test_ignores_noise(self):
        # Two draws from the same distribution must not be called significant.
        rng = random.Random(2)
        a = [rng.gauss(4.0, 0.5) for _ in range(30)]
        b = [rng.gauss(4.0, 0.5) for _ in range(30)]
        res = s.compare_means(a, b, seed=7)
        self.assertFalse(res.significant)

    def test_validation(self):
        with self.assertRaises(ValueError):
            s.compare_means([1.0], [1.0, 2.0])
        with self.assertRaises(ValueError):
            s.compare_means([1.0, 2.0], [3.0, 4.0], iterations=0)
        with self.assertRaises(ValueError):
            s.compare_means([1.0, 2.0], [3.0, 4.0], confidence=1.5)

    def test_confidence_is_reported(self):
        # The result carries the confidence it was computed at (not hardcoded).
        res = s.compare_means([1.0, 2.0, 3.0], [1.0, 2.0, 3.0], confidence=0.90, seed=1)
        self.assertEqual(res.confidence, 0.90)
        self.assertIn("90% CI", str(res))


class TestMinTrials(unittest.TestCase):
    def test_proportion_known_value(self):
        # Triage test #3: detect a 10-point drop from a 95% baseline.
        self.assertEqual(s.min_trials_for_proportion(0.95, 0.10, 0.05, 0.80), 141)

    def test_proportion_monotonic(self):
        # Smaller effects require more trials.
        big = s.min_trials_for_proportion(0.95, 0.20)
        small = s.min_trials_for_proportion(0.95, 0.05)
        self.assertLess(big, small)

    def test_mean_small_delta_is_expensive(self):
        # The headline finding: a 0.04 delta on a sigma=0.5 scale needs
        # thousands of trials, far more than the 3 typically run.
        self.assertEqual(s.min_trials_for_mean(0.5, 0.04, 0.05, 0.80), 2453)
        self.assertLess(s.min_trials_for_mean(0.5, 0.40), 30)

    def test_validation(self):
        with self.assertRaises(ValueError):
            s.min_trials_for_proportion(0.95, 0.99)  # effect >= baseline
        with self.assertRaises(ValueError):
            s.min_trials_for_mean(0.0, 0.1)


class TestThresholdTest(unittest.TestCase):
    def test_underpowered_fails(self):
        # 19/20 = 95% observed, but not enough evidence for a 90% target.
        res = s.threshold_test(19, 20, 0.90)
        self.assertFalse(res.passed)

    def test_same_rate_more_trials_passes(self):
        # Same 95% rate at 10x the trials clears the same target.
        res = s.threshold_test(190, 200, 0.90)
        self.assertTrue(res.passed)

    def test_label_reflects_confidence(self):
        # The printed CI label must match the confidence used, not hardcode 95%.
        res = s.threshold_test(19, 20, 0.90, confidence=0.80)
        self.assertEqual(res.confidence, 0.80)
        self.assertIn("80% CI", str(res))


class TestThresholdCheckCLI(unittest.TestCase):
    def test_parses_promptfoo_json_manual_match(self):
        # Triage test #4: parse the sample JSON, verify pass/fail matches a
        # manual calculation. Fixture is 19/20; against a 0.90 target the
        # lower Wilson bound (~0.764) is below target -> FAIL (exit 1).
        with open(_FIXTURE, encoding="utf-8") as fh:
            data = json.load(fh)
        successes, total = tc.extract_counts(data)
        self.assertEqual((successes, total), (19, 20))

        expected = s.threshold_test(19, 20, 0.90)
        self.assertFalse(expected.passed)
        self.assertEqual(tc.main([_FIXTURE, "--target", "0.90"]), 1)

    def test_lenient_target_passes(self):
        # Against a 0.70 target, 19/20 clears it -> exit 0.
        self.assertEqual(tc.main([_FIXTURE, "--target", "0.70"]), 0)

    def test_counts_from_results_array_without_stats(self):
        rows = {"results": {"results": [
            {"success": True}, {"success": True}, {"success": False},
        ]}}
        self.assertEqual(tc.extract_counts(rows), (2, 3))

    def test_bad_input_returns_2(self):
        self.assertEqual(tc.main(["does_not_exist.json", "--target", "0.9"]), 2)

    def test_empty_results_raises(self):
        with self.assertRaises(ValueError):
            tc.extract_counts({"results": {"results": []}})

    def test_string_success_rejected(self):
        # "false" is truthy in Python; a CI gate must not count it as a pass.
        with self.assertRaises(ValueError):
            tc.extract_counts({"results": {"results": [{"success": "false"}]}})

    def test_non_int_stats_rejected(self):
        with self.assertRaises(ValueError):
            tc.extract_counts({"results": {"stats": {"successes": "19", "failures": 1}}})


if __name__ == "__main__":
    unittest.main()
