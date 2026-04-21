# /bug-bash — Automated Issue Resolver

Runs one issue per cycle using a label-based state machine. Checks labels in priority order and stops after processing the first matching issue.

**Scheduled trigger ID:** `trig_01NqR7gQEZXotEbWYP8Lozr3` — runs daily at 9am ET.
Manage at: https://claude.ai/code/scheduled/trig_01NqR7gQEZXotEbWYP8Lozr3

---

## Label Reference

**You control:**
| Label | Meaning |
|-------|---------|
| `auto` | Ready for bot to analyze |
| `bot/approved` | Proposal reviewed — go implement |

**Bot controls (never set these manually):**
| Label | Meaning |
|-------|---------|
| `bot/proposed` | Plan posted, awaiting your review |
| `bot/blocked` | Blocker found — comment left, needs input |
| `bot/safe-to-close` | Already resolved |

---

## Step 1 — Find the active issue

```bash
# Priority 1: approved — ready to implement
gh issue list --repo gabeduke/django-gift-wiki --label "bot/approved" --state open --limit 1 --json number,title,labels,body

# Priority 2: auto — ready to analyze (skip if bot/proposed or bot/approved already present)
gh issue list --repo gabeduke/django-gift-wiki --label "auto" --state open --limit 10 --json number,title,labels,body
```

For Priority 2, filter out any issue that already has `bot/proposed` or `bot/approved`. Take the first remaining result. If nothing matches either priority, exit cleanly with no changes.

---

## Step 2a — ANALYZE (issue has `auto`, no `bot/proposed`)

1. Read the issue body and any linked code using the file tools.
2. Check for related open issues or PRs:
   ```bash
   gh issue list --repo gabeduke/django-gift-wiki --state open --json number,title,labels | head -30
   gh pr list --repo gabeduke/django-gift-wiki --state open --json number,title,headRefName
   ```
3. Explore the relevant code paths in the repo.
4. Build a proposal using the template below.
5. Post the comment:
   ```bash
   gh issue comment <number> --repo gabeduke/django-gift-wiki --body "<proposal>"
   ```
6. Update labels — remove `auto`, add `bot/proposed`:
   ```bash
   gh issue edit <number> --repo gabeduke/django-gift-wiki --remove-label "auto" --add-label "bot/proposed"
   ```

If a blocker is found at any point, add `bot/blocked` instead of `bot/proposed` and describe the blocker in the comment.

If the issue appears already resolved (code already merged, behavior already present), add `bot/safe-to-close` and explain in a comment.

---

## Step 2b — IMPLEMENT (issue has `bot/approved`)

1. Re-read the proposal comment you previously posted on this issue.
2. Create a feature branch:
   ```bash
   git checkout main && git pull
   git checkout -b bot/issue-<number>-<short-slug>
   ```
3. Implement the solution exactly as proposed. If something has changed that invalidates the proposal, stop, comment on the issue, and re-add `bot/proposed` (remove `bot/approved`).
4. Run tests and linting:
   ```bash
   pipenv run pytest
   pipenv run ruff check . && pipenv run ruff format .
   ```
5. Commit and push:
   ```bash
   git add <specific files>
   git commit -m "fix: <summary> (closes #<number>)"
   git push -u origin bot/issue-<number>-<short-slug>
   ```
6. Open a PR:
   ```bash
   gh pr create --repo gabeduke/django-gift-wiki \
     --title "<title>" \
     --base main \
     --body "Closes #<number>\n\n<summary of changes>"
   ```
7. Remove label `bot/approved` from the issue:
   ```bash
   gh issue edit <number> --repo gabeduke/django-gift-wiki --remove-label "bot/approved"
   ```

---

## Proposal Comment Template

```
## Bot Proposal

**Approach:** <one sentence>

**Files to change:**
- `<path>`: <what changes>

**QA plan:**
- [ ] <test or verification step>

**Risks / open questions:**
- <edge cases, schema changes, related issues>

**Blockers:** none

---
_To approve: add label `bot/approved`. To redirect: comment and remove `auto`._
```
