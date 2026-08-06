#!/usr/bin/env bash
set -euo pipefail

ORG="appdumpster"
REPO="codeowners-lab"
TEAM="owners"
FULL_REPO="${ORG}/${REPO}"

# --- 1. Create team ---
echo "=== Creating team @${ORG}/${TEAM} (if not exists)"
if gh api "orgs/${ORG}/teams/${TEAM}" --silent 2>/dev/null; then
  echo "    Team already exists, skipping."
else
  gh api "orgs/${ORG}/teams" \
    -f name="${TEAM}" \
    -f privacy="closed" \
    --silent
  echo "    Team created."
fi

# --- 2. Create repo ---
echo "=== Creating repo ${FULL_REPO} (if not exists)"
if gh repo view "${FULL_REPO}" --json name --jq .name &>/dev/null; then
  echo "    Repo already exists, skipping."
else
  gh repo create "${FULL_REPO}" --public
  echo "    Repo created."
fi

# --- 3. Grant team write access ---
echo "=== Granting team @${ORG}/${TEAM} write access to ${FULL_REPO}"
gh api "orgs/${ORG}/teams/${TEAM}/repos/${FULL_REPO}" \
  -X PUT \
  -f permission="push" \
  --silent
echo "    Done."

# --- 4. Seed files on main branch ---
echo "=== Seeding files on main branch (if main doesn't exist yet)"
if gh api "repos/${FULL_REPO}/branches/main" --silent 2>/dev/null; then
  echo "    Main branch already exists, skipping seed."
else
  seed_file() {
    local path="$1"
    local content="$2"
    local encoded
    encoded=$(printf '%s' "${content}" | base64 -w0)
    gh api "repos/${FULL_REPO}/contents/${path}" \
      -X PUT \
      -f message="seed: add ${path}" \
      -f content="${encoded}" \
      --silent
    echo "    Seeded ${path}"
  }

  seed_file "main.go" "package main

func main() {}
"

  seed_file "go.mod" "module github.com/appdumpster/codeowners-lab

go 1.22
"

  seed_file "go.sum" "// empty
"

  seed_file "CODEOWNERS" "* @appdumpster/owners

go.mod
go.sum
"
fi

# --- 5. Configure branch protection on main ---
echo "=== Configuring branch protection on main"
gh api "repos/${FULL_REPO}/branches/main/protection" \
  -X PUT \
  --input - <<'JSON'
{
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "require_code_owner_reviews": true,
    "dismiss_stale_reviews": false,
    "require_last_push_approval": false
  },
  "enforce_admins": false,
  "required_status_checks": null,
  "restrictions": null
}
JSON
echo "    Branch protection configured."

# --- Summary ---
echo ""
echo "=== Setup complete"
echo "    Repo URL: https://github.com/${FULL_REPO}"
echo "    Branch protection on main:"
echo "      - Required approving reviews: 1"
echo "      - Require code owner reviews: true"
echo "      - Dismiss stale reviews: false"
echo "      - Require last push approval: false"
echo "      - Enforce admins: false"
echo "      - Required status checks: null"
echo "      - Restrictions: null"
