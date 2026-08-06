#!/usr/bin/env bash
set -euo pipefail

OWNER="appdumpster"
REPO="codeowners-lab"
BASE="main"

MAIN_GO_CONTENT=$(printf 'package main\n\nfunc main() {\n\t// modified\n}\n' | base64 -w0)
GO_MOD_CONTENT=$(printf 'module github.com/appdumpster/codeowners-lab\n\ngo 1.23\n' | base64 -w0)

PR_BODY="Automated test PR for CODEOWNERS experiment."

echo "=== Fetching SHA of main branch"
MAIN_SHA=$(gh api "repos/${OWNER}/${REPO}/git/ref/heads/${BASE}" --jq '.object.sha')
echo "=== main SHA: ${MAIN_SHA}"

create_pr() {
    local branch="$1"
    local title="$2"
    local file1="$3"
    local content1="$4"
    local file2="${5:-}"
    local content2="${6:-}"

    echo "=== Creating PR: ${title}"

    # Check if branch already exists
    if gh api "repos/${OWNER}/${REPO}/git/ref/heads/${branch}" > /dev/null 2>&1; then
        echo "=== Branch ${branch} already exists, skipping"
        return
    fi

    # Create branch ref
    echo "=== Creating branch ${branch}"
    gh api --method POST "repos/${OWNER}/${REPO}/git/refs" \
        --field "ref=refs/heads/${branch}" \
        --field "sha=${MAIN_SHA}" > /dev/null

    # Get current file SHA and commit change for file1
    echo "=== Modifying ${file1}"
    local file1_sha
    file1_sha=$(gh api "repos/${OWNER}/${REPO}/contents/${file1}?ref=${branch}" --jq '.sha')
    gh api --method PUT "repos/${OWNER}/${REPO}/contents/${file1}" \
        --field "message=test: modify ${file1}" \
        --field "content=${content1}" \
        --field "sha=${file1_sha}" \
        --field "branch=${branch}" > /dev/null

    # If a second file is specified, do the same
    if [[ -n "${file2}" ]]; then
        echo "=== Modifying ${file2}"
        local file2_sha
        file2_sha=$(gh api "repos/${OWNER}/${REPO}/contents/${file2}?ref=${branch}" --jq '.sha')
        gh api --method PUT "repos/${OWNER}/${REPO}/contents/${file2}" \
            --field "message=test: modify ${file2}" \
            --field "content=${content2}" \
            --field "sha=${file2_sha}" \
            --field "branch=${branch}" > /dev/null
    fi

    # Create PR
    echo "=== Opening PR"
    gh api --method POST "repos/${OWNER}/${REPO}/pulls" \
        --field "title=${title}" \
        --field "body=${PR_BODY}" \
        --field "head=${branch}" \
        --field "base=${BASE}" > /dev/null

    echo "=== Done: ${title}"
}

create_pr "test/read-owned" \
    "H1: read-bot approves owned file (main.go)" \
    "main.go" "${MAIN_GO_CONTENT}"

create_pr "test/write-owned" \
    "H2: write-bot approves owned file (main.go)" \
    "main.go" "${MAIN_GO_CONTENT}"

create_pr "test/read-blank" \
    "H1+H3: read-bot approves blank-owner file (go.mod)" \
    "go.mod" "${GO_MOD_CONTENT}"

create_pr "test/write-blank" \
    "H2+H3+H5: write-bot approves blank-owner file (go.mod)" \
    "go.mod" "${GO_MOD_CONTENT}"

create_pr "test/read-mixed" \
    "H1+H4: read-bot approves mixed files (go.mod + main.go)" \
    "go.mod" "${GO_MOD_CONTENT}" \
    "main.go" "${MAIN_GO_CONTENT}"

create_pr "test/write-mixed" \
    "H2+H4+H6: write-bot approves mixed files (go.mod + main.go)" \
    "go.mod" "${GO_MOD_CONTENT}" \
    "main.go" "${MAIN_GO_CONTENT}"

echo ""
echo "=== Open PRs:"
gh api "repos/${OWNER}/${REPO}/pulls?state=open" --jq '.[] | "#\(.number) \(.title)"'
