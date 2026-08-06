#!/usr/bin/env python3
"""Test harness for CODEOWNERS + GitHub App permission matrix.

Authenticates as two GitHub Apps (read-bot and write-bot), submits APPROVE
reviews on test PRs, and checks whether each PR becomes mergeable.
"""

import json
import os
import sys
import time
from pathlib import Path

import jwt
import requests

ORG = "appdumpster"
REPO = "codeowners-lab"
API = "https://api.github.com"
HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

TESTS = [
    {
        "branch": "test/read-owned",
        "bot": "read",
        "description": "H1: read-bot approves owned file",
        "hypotheses": ["H1"],
    },
    {
        "branch": "test/write-owned",
        "bot": "write",
        "description": "H2: write-bot approves owned file",
        "hypotheses": ["H2"],
    },
    {
        "branch": "test/read-blank",
        "bot": "read",
        "description": "H1+H3: read-bot approves blank-owner file",
        "hypotheses": ["H1", "H3"],
    },
    {
        "branch": "test/write-blank",
        "bot": "write",
        "description": "H2+H3+H5: write-bot approves blank-owner file",
        "hypotheses": ["H2", "H3", "H5"],
    },
    {
        "branch": "test/read-mixed",
        "bot": "read",
        "description": "H1+H4: read-bot approves mixed files",
        "hypotheses": ["H1", "H4"],
    },
    {
        "branch": "test/write-mixed",
        "bot": "write",
        "description": "H2+H4+H6: write-bot approves mixed files",
        "hypotheses": ["H2", "H4", "H6"],
    },
]


def make_jwt(app_id: str, pem_path: str) -> str:
    """Create a JWT for a GitHub App using PyJWT."""
    with open(pem_path, "rb") as f:
        private_key = f.read()
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + 600,
        "iss": app_id,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


def get_installation_token(app_jwt: str) -> str:
    """Get an installation access token for the target org."""
    resp = requests.get(
        f"{API}/app/installations",
        headers={**HEADERS, "Authorization": f"Bearer {app_jwt}"},
        timeout=60,
    )
    resp.raise_for_status()

    for inst in resp.json():
        if inst.get("account", {}).get("login") == ORG:
            token_resp = requests.post(
                f"{API}/app/installations/{inst['id']}/access_tokens",
                headers={**HEADERS, "Authorization": f"Bearer {app_jwt}"},
                timeout=60,
            )
            token_resp.raise_for_status()
            return token_resp.json()["token"]

    raise RuntimeError(f"No installation found for org '{ORG}'")


def approve_pr(token: str, pr_number: int, bot_name: str) -> dict:
    """Submit an APPROVE review on a PR."""
    resp = requests.post(
        f"{API}/repos/{ORG}/{REPO}/pulls/{pr_number}/reviews",
        headers={**HEADERS, "Authorization": f"Bearer {token}"},
        json={
            "event": "APPROVE",
            "body": f"Approved by {bot_name} (experiment)",
        },
        timeout=60,
    )
    return {"status": resp.status_code, "body": resp.json()}


def check_merge_status(token: str, pr_number: int) -> dict:
    """Check PR mergeability and attempt a squash merge."""
    pr_resp = requests.get(
        f"{API}/repos/{ORG}/{REPO}/pulls/{pr_number}",
        headers={**HEADERS, "Authorization": f"Bearer {token}"},
        timeout=60,
    )
    pr_data = pr_resp.json()

    reviews_resp = requests.get(
        f"{API}/repos/{ORG}/{REPO}/pulls/{pr_number}/reviews",
        headers={**HEADERS, "Authorization": f"Bearer {token}"},
        timeout=60,
    )
    reviews = [
        {"user": r["user"]["login"], "state": r["state"]} for r in reviews_resp.json()
    ]

    merge_resp = requests.put(
        f"{API}/repos/{ORG}/{REPO}/pulls/{pr_number}/merge",
        headers={**HEADERS, "Authorization": f"Bearer {token}"},
        json={"merge_method": "squash"},
        timeout=60,
    )

    return {
        "mergeable": pr_data.get("mergeable"),
        "mergeable_state": pr_data.get("mergeable_state"),
        "reviews": reviews,
        "merge_status": merge_resp.status_code,
        "merge_body": merge_resp.json(),
    }


def main():
    read_app_id = os.environ.get("READ_BOT_APP_ID")
    read_pem = os.environ.get("READ_BOT_PEM")
    write_app_id = os.environ.get("WRITE_BOT_APP_ID")
    write_pem = os.environ.get("WRITE_BOT_PEM")

    missing = [
        name
        for name, val in [
            ("READ_BOT_APP_ID", read_app_id),
            ("READ_BOT_PEM", read_pem),
            ("WRITE_BOT_APP_ID", write_app_id),
            ("WRITE_BOT_PEM", write_pem),
        ]
        if not val
    ]
    if missing:
        print(
            f"ERROR: required env vars not set: {', '.join(missing)}", file=sys.stderr
        )
        sys.exit(1)

    # Authenticate both apps
    print("Authenticating read-bot...")
    read_jwt = make_jwt(read_app_id, read_pem)
    read_token = get_installation_token(read_jwt)
    print("  read-bot authenticated")

    print("Authenticating write-bot...")
    write_jwt = make_jwt(write_app_id, write_pem)
    write_token = get_installation_token(write_jwt)
    print("  write-bot authenticated")

    tokens = {"read": read_token, "write": write_token}

    # List open PRs to build branch -> PR number mapping
    list_token = (
        os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or write_token
    )
    resp = requests.get(
        f"{API}/repos/{ORG}/{REPO}/pulls",
        headers={**HEADERS, "Authorization": f"Bearer {list_token}"},
        params={"state": "open", "per_page": 100},
        timeout=60,
    )
    resp.raise_for_status()
    branch_to_pr = {pr["head"]["ref"]: pr["number"] for pr in resp.json()}
    print(f"\nOpen PRs: {json.dumps(branch_to_pr, indent=2)}\n")

    # Run test matrix
    results = []
    for test in TESTS:
        branch = test["branch"]
        pr_number = branch_to_pr.get(branch)
        if not pr_number:
            print(f"SKIP: no open PR found for branch '{branch}'")
            results.append({**test, "pr": None, "skipped": True})
            continue

        print("=" * 60)
        print(f"TEST: {test['description']}")
        print(f"  Branch: {branch}  PR: #{pr_number}  Bot: {test['bot']}")
        print("=" * 60)

        token = tokens[test["bot"]]
        bot_name = f"{test['bot']}-bot"

        # Approve
        approval = approve_pr(token, pr_number, bot_name)
        print(f"  Approval: {approval['status']}")
        if approval["status"] != 200:
            print(f"  Approval body: {json.dumps(approval['body'], indent=2)}")

        # Wait for GitHub to process
        time.sleep(3)

        # Check merge status
        status = check_merge_status(token, pr_number)
        print(f"  Mergeable: {status['mergeable']}")
        print(f"  Mergeable state: {status['mergeable_state']}")
        print(f"  Reviews: {json.dumps(status['reviews'], indent=2)}")
        print(f"  Merge attempt: {status['merge_status']}")
        print(f"  Merge body: {json.dumps(status['merge_body'], indent=2)}")

        results.append(
            {
                **test,
                "pr": pr_number,
                "skipped": False,
                "approval": approval,
                "merge_status": status["merge_status"],
                "mergeable": status["mergeable"],
                "mergeable_state": status["mergeable_state"],
                "reviews": status["reviews"],
                "merge_body": status["merge_body"],
            }
        )

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for r in results:
        if r.get("skipped"):
            print(f"  SKIP  {r['description']}")
            continue
        merged = r["merge_status"] == 200
        label = "MERGED" if merged else "BLOCKED"
        msg = r["merge_body"].get("message", "")
        print(f"  {label}  PR#{r['pr']}  {r['description']}  -- {msg}")

    # Write results
    results_path = Path(__file__).resolve().parent / "results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults written to {results_path}")


if __name__ == "__main__":
    main()
