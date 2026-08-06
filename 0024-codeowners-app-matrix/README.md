---
title: "24. CODEOWNERS + GitHub App approval matrix"
status: Concluded
topics:
  - github-apps
  - security
  - branch-protection
---

# 24. CODEOWNERS + GitHub App approval matrix

Date: 2026-07-13

Related: [Auto-merge ADR PR](https://github.com/fullsend-ai/fullsend/pull/2791),
[CODEOWNERS blank-owner PR](https://github.com/fullsend-ai/fullsend/pull/2790)

## Hypotheses

| ID | Statement | Result |
|----|-----------|--------|
| H1 | A GitHub App with `contents: read` can submit an APPROVE review, but it does NOT count toward the "require approvals" branch protection rule. | Confirmed |
| H2 | A GitHub App with `contents: write` can submit an APPROVE review, and it DOES count toward "require approvals". | Confirmed |
| H3 | A blank-owner CODEOWNERS entry removes the code-owner review requirement for PRs that only touch that file. | Confirmed |
| H4 | A PR touching both a blank-owner file and an owned file still requires code-owner approval for the owned file. | Confirmed |
| H5 | When H2 and H3 are both true, a `contents: write` app is the sole approver on a blank-owner-only PR, and the PR is mergeable. | Confirmed |
| H6 | When a PR touches both blank-owner and owned files, even a `contents: write` app cannot satisfy the code-owner requirement for the owned files. | Confirmed |

## Approach

### Test infrastructure

- **Org:** `appdumpster`
- **Repo:** `appdumpster/codeowners-lab`
- **Team:** `@appdumpster/owners` (with the human operator as a member)
- **Apps:**
  - `appdumpster-read-bot` — `contents: read`, `pull_requests: write`
  - `appdumpster-write-bot` — `contents: write`, `pull_requests: write`

### Repo layout

```
CODEOWNERS:
  * @appdumpster/owners
  go.mod
  go.sum

Files: main.go, go.mod, go.sum
```

### Branch protection on `main`

- Require 1 approval
- Require review from code owners
- No status checks (keep it simple)

### Test matrix

| PR | Branch | Files touched | Approved by | Tests |
|----|--------|--------------|-------------|-------|
| 1 | `test/read-owned` | `main.go` | read-bot | H1 |
| 2 | `test/write-owned` | `main.go` | write-bot | H2, H4 partial |
| 3 | `test/read-blank` | `go.mod` | read-bot | H1, H3 |
| 4 | `test/write-blank` | `go.mod` | write-bot | H2, H3, H5 |
| 5 | `test/read-mixed` | `go.mod` + `main.go` | read-bot | H1, H4 |
| 6 | `test/write-mixed` | `go.mod` + `main.go` | write-bot | H2, H4, H6 |

### Measurement

For each PR, after the bot approves, query:
- `GET /repos/{owner}/{repo}/pulls/{number}/reviews` — confirm the review exists
- `GET /repos/{owner}/{repo}/pulls/{number}/merge` — can it merge? (405 = no, 204 = yes)
- `PUT /repos/{owner}/{repo}/pulls/{number}/merge` — attempt the merge, record status code and error message

## Results

Ran on 2026-07-13 against `appdumpster/codeowners-lab` with two throwaway GitHub Apps.

| PR | Test | `mergeable_state` | Merge attempt | HTTP | Error message |
|----|------|--------------------|---------------|------|---------------|
| #1 | read-bot + owned file | `blocked` | BLOCKED | 403 | Resource not accessible by integration |
| #2 | write-bot + owned file | `blocked` | BLOCKED | 405 | Waiting on code owner review from appdumpster/owners. |
| #3 | read-bot + blank-owner file | `blocked` | BLOCKED | 403 | Resource not accessible by integration |
| #4 | write-bot + blank-owner file | `clean` | **MERGED** | 200 | Pull Request successfully merged |
| #5 | read-bot + mixed files | `unknown` | BLOCKED | 403 | Resource not accessible by integration |
| #6 | write-bot + mixed files | `unknown` | BLOCKED | 405 | Waiting on code owner review from appdumpster/owners. |

### Key observations

1. **`contents: read` vs `contents: write` produces different failure modes.** The read-bot gets 403 "Resource not accessible by integration" — a permission error, not a branch protection error. The write-bot gets 405 with a specific branch protection message. This means the read-bot's approval is invisible to branch protection; it can't even attempt the merge.

2. **Blank-owner CODEOWNERS entries work as documented.** PR #4 (write-bot approving a PR that only touches `go.mod`) had `mergeable_state: clean` and merged successfully. The blank-owner entry removed the code-owner review gate.

3. **Blank-owner doesn't leak to owned files.** PRs #5 and #6 (mixed: `go.mod` + `main.go`) were both blocked. The write-bot's approval satisfied the general approval requirement but not the code-owner requirement for `main.go`.

4. **The only mergeable combination is `contents: write` app + blank-owner-only files.** This is exactly the scenario the [auto-merge ADR](https://github.com/fullsend-ai/fullsend/pull/2791) targets.

## Conclusion

All six hypotheses confirmed. the [auto-merge ADR](https://github.com/fullsend-ai/fullsend/pull/2791)'s design is sound:

- A `contents: write` merge app can approve and merge PRs that only touch blank-owner CODEOWNERS files (like `go.mod`/`go.sum`).
- The same app cannot bypass code-owner review for files with actual owners.
- A `contents: read` review app's approvals are ignored by branch protection entirely.

The combination of blank-owner CODEOWNERS entries + a write-capable merge app is the minimum viable path to bot-driven auto-merge for dependency updates without compromising code-owner review for application code.
