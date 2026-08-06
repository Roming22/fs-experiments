#!/usr/bin/env bash
set -euo pipefail

ORG="appdumpster"
REPO="codeowners-lab"
TEAM="owners"

echo "=== Deleting repo ${ORG}/${REPO} ==="
gh repo delete "${ORG}/${REPO}" --yes 2>/dev/null || echo "  (not found)"

echo "=== Deleting team @${ORG}/${TEAM} ==="
gh api "orgs/${ORG}/teams/${TEAM}" --method DELETE 2>/dev/null || echo "  (not found)"

echo "=== Done ==="
echo "Note: GitHub Apps must be deleted manually from https://github.com/organizations/${ORG}/settings/apps"
