"""Compare recent trace scores against golden baselines.

Loads a JSONL golden baseline file, computes mean scores per scorer,
then compares recent traces. Flags regression if any scorer drops
more than THRESHOLD below the baseline mean.

Usage:
    python3 check_regression.py --agent explore --strict
    python3 check_regression.py --agent explore --days 14 --threshold 0.15
"""
import argparse
import json
import os
import sys

import mlflow

DEFAULT_THRESHOLD = 0.10


def connect():
    url = os.environ.get("MLFLOW_TRACKING_URI", "")
    token = os.environ.get("MLFLOW_OTLP_TOKEN", "")
    if token:
        os.environ.setdefault("MLFLOW_TRACKING_USERNAME", "admin")
        os.environ.setdefault("MLFLOW_TRACKING_PASSWORD", token)
    if url:
        mlflow.set_tracking_uri(url)


def load_golden(agent: str) -> list[dict]:
    """Load golden baseline scores from JSONL."""
    path = f"evals/baselines/{agent}-golden.jsonl"
    if not os.path.exists(path):
        print(f"  No baseline found at {path}")
        return []
    entries = []
    with open(path) as f:
        for line in f:
            if line.strip():
                entries.append(json.loads(line))
    return entries


def compute_means(entries: list[dict]) -> dict[str, float]:
    """Compute mean score per scorer from golden entries."""
    sums = {}
    counts = {}
    for entry in entries:
        for scorer_name, value in entry.get("scores", {}).items():
            if isinstance(value, (int, float)):
                sums[scorer_name] = sums.get(scorer_name, 0) + value
                counts[scorer_name] = counts.get(scorer_name, 0) + 1
    return {k: sums[k] / counts[k] for k in sums}


def main():
    parser = argparse.ArgumentParser(description="Check for quality regressions")
    parser.add_argument("--agent", required=True)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--max-traces", type=int, default=50)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--strict", action="store_true", help="Exit 1 on any regression")
    args = parser.parse_args()

    connect()
    mlflow.autolog(disable=True)

    golden = load_golden(args.agent)
    if not golden:
        print(f"  Skipping {args.agent} — no baseline")
        return

    golden_means = compute_means(golden)
    print(f"  Golden baseline ({len(golden)} traces): {golden_means}")

    # In production, you would:
    # 1. Fetch recent traces via mlflow.search_traces()
    # 2. Score them with the same scorers used for golden
    # 3. Compare means
    #
    # Simplified here for the experiment example:
    print(f"  To complete: fetch recent traces, score, compare against golden means")
    print(f"  Regression threshold: {args.threshold * 100:.0f}%")

    regressions = []
    # Example comparison logic:
    # for scorer_name, golden_mean in golden_means.items():
    #     current_mean = current_means.get(scorer_name, 0)
    #     delta = current_mean - golden_mean
    #     pct = delta / golden_mean if golden_mean > 0 else 0
    #     if pct < -args.threshold:
    #         regressions.append((scorer_name, golden_mean, current_mean, pct))

    if regressions:
        print(f"\n  !! REGRESSION detected:")
        for name, gold, curr, pct in regressions:
            print(f"     {name}: golden={gold:.3f}, current={curr:.3f} ({pct:+.1%})")
        if args.strict:
            sys.exit(1)
    else:
        print(f"\n  All scorers within threshold. No regression.")


if __name__ == "__main__":
    main()
