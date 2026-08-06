"""Score traces via mlflow.genai.evaluate() and log operational metrics.

Reads traces from MLflow, resolves scorers from harness config, and runs
evaluation. Results appear as Feedbacks on traces (Quality Dashboard) and
as metrics on the evaluation run (Evaluation Runs page).

Usage:
    python3 run_eval.py --agent explore --days 7 --max-traces 10
    python3 run_eval.py --agent explore --mechanical-only
"""
import argparse
import os
import time

import mlflow
from mlflow import MlflowClient


def connect():
    """Set up MLflow tracking connection."""
    url = os.environ.get("MLFLOW_TRACKING_URI", "")
    token = os.environ.get("MLFLOW_OTLP_TOKEN", "")
    if token:
        os.environ.setdefault("MLFLOW_TRACKING_USERNAME", "admin")
        os.environ.setdefault("MLFLOW_TRACKING_PASSWORD", token)
    if url:
        mlflow.set_tracking_uri(url)


def get_traces(agent=None, days=7, max_results=50):
    """Search for traces, optionally filtered by agent and recency."""
    filters = []
    if agent:
        filters.append(f"tags.`fullsend.agent` = '{agent}'")
    if days:
        import datetime
        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
        filters.append(f"timestamp > {int(cutoff.timestamp() * 1000)}")

    filter_str = " AND ".join(filters) if filters else None
    return mlflow.search_traces(
        locations=["0"],
        filter_string=filter_str,
        max_results=max_results,
    )


def resolve_scorers(agent, mechanical_only=False):
    """Resolve scorer functions for the given agent.

    In production, this reads the harness YAML. Here we import directly.
    """
    from scorer_mechanical import MECHANICAL_SCORERS

    if mechanical_only:
        return MECHANICAL_SCORERS

    if agent == "explore":
        from scorer_llm_judge import EXPLORE_SCORERS
        return MECHANICAL_SCORERS + EXPLORE_SCORERS
    elif agent == "refine":
        from scorer_llm_judge import REFINE_SCORERS
        return MECHANICAL_SCORERS + REFINE_SCORERS
    elif agent == "critique":
        from scorer_llm_judge import CRITIQUE_SCORERS
        return MECHANICAL_SCORERS + CRITIQUE_SCORERS
    else:
        return MECHANICAL_SCORERS


def main():
    parser = argparse.ArgumentParser(description="Score traces via MLflow")
    parser.add_argument("--agent", required=True, help="Agent name (explore, refine, critique)")
    parser.add_argument("--days", type=int, default=7, help="Look-back window in days")
    parser.add_argument("--max-traces", type=int, default=50, help="Max traces to score")
    parser.add_argument("--mechanical-only", action="store_true", help="Skip LLM judges")
    args = parser.parse_args()

    connect()
    mlflow.autolog(disable=True)

    print(f"Fetching traces for {args.agent} (last {args.days} days)...")
    traces_df = get_traces(agent=args.agent, days=args.days, max_results=args.max_traces)
    print(f"  Found {len(traces_df)} traces")

    if traces_df.empty:
        print("  No traces to score.")
        return

    scorers = resolve_scorers(args.agent, args.mechanical_only)
    print(f"  Running {len(scorers)} scorers...")

    start = time.time()
    result = mlflow.genai.evaluate(data=traces_df, scorers=scorers)
    elapsed = time.time() - start

    print(f"  Evaluation complete in {elapsed:.1f}s")
    print(f"  Results: {result.metrics}")

    mlflow.log_param("agent", args.agent)
    mlflow.log_metrics({
        "trace_count": len(traces_df),
        "latency_ms": int(elapsed * 1000),
    })


if __name__ == "__main__":
    main()
