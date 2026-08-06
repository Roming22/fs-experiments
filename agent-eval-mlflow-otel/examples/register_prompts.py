"""Register agent prompts in MLflow Prompts Registry.

Reads agent prompt markdown files and registers them as versioned prompts
with @staging or @production aliases. Uses content-hash dedup to skip
unchanged prompts while still updating the alias.

Usage:
    python3 register_prompts.py --alias staging
    python3 register_prompts.py --alias production
    python3 register_prompts.py --alias staging --agents explore refine

Env:
    GIT_COMMIT  — Current git commit hash (for metadata)
    GIT_BRANCH  — Current git branch name
"""
import argparse
import hashlib
import os
from pathlib import Path

import mlflow
from mlflow import MlflowClient

AGENTS_DIR = Path(".fullsend/customized/agents")
PROMPT_PREFIX = "fullsend"


def connect():
    url = os.environ.get("MLFLOW_TRACKING_URI", "")
    token = os.environ.get("MLFLOW_OTLP_TOKEN", "")
    if token:
        os.environ.setdefault("MLFLOW_TRACKING_USERNAME", "admin")
        os.environ.setdefault("MLFLOW_TRACKING_PASSWORD", token)
    if url:
        mlflow.set_tracking_uri(url)


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def register_prompt(agent: str, alias: str, client: MlflowClient):
    """Register a single agent's prompt in MLflow."""
    prompt_path = AGENTS_DIR / f"{agent}.md"
    if not prompt_path.exists():
        print(f"  SKIP {agent} — {prompt_path} not found")
        return

    content = prompt_path.read_text()
    chash = content_hash(content)
    prompt_name = f"{PROMPT_PREFIX}-{agent}"

    git_commit = os.environ.get("GIT_COMMIT", "unknown")
    git_branch = os.environ.get("GIT_BRANCH", "unknown")

    tags = {
        "git.commit": git_commit,
        "git.branch": git_branch,
        "content.hash": chash,
        "agent": agent,
        "source": str(prompt_path),
    }

    existing = client.search_prompt_versions(name=prompt_name, max_results=1)
    if existing:
        latest = existing[0]
        latest_hash = (latest.tags or {}).get("content.hash", "")
        if latest_hash == chash:
            print(f"  {prompt_name}: content unchanged (hash={chash}), updating alias only")
            mlflow.genai.set_prompt_alias(prompt_name, alias, latest.version)
            return

    version = mlflow.genai.register_prompt(
        name=prompt_name,
        template=content,
        commit_message=f"{alias}: {agent} prompt ({chash})",
        tags=tags,
    )
    print(f"  {prompt_name}: registered v{version.version} (hash={chash})")

    mlflow.genai.set_prompt_alias(prompt_name, alias, version.version)
    print(f"  {prompt_name}: alias @{alias} -> v{version.version}")


def main():
    parser = argparse.ArgumentParser(description="Register prompts in MLflow")
    parser.add_argument("--alias", required=True, choices=["staging", "production"])
    parser.add_argument("--agents", nargs="+", default=["explore", "refine", "critique"])
    args = parser.parse_args()

    connect()
    client = MlflowClient()

    for agent in args.agents:
        register_prompt(agent, args.alias, client)


if __name__ == "__main__":
    main()
