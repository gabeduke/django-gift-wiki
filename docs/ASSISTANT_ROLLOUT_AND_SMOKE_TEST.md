# In-App Assistant: Smoke Test and Staged Rollout

## Status: not yet executed

This document was written by Task 12 (credentials, infrastructure, and the
rollout) of the in-app assistant plan, in an environment with **no Google
Cloud credentials and no network access to Vertex AI**. Every command below
is a checklist, not a report — nobody has run any of it yet. The two sections
match Steps 6 and 9 of the task brief
(`.superpowers/sdd/2026-09-23-in-app-assistant-chat/task-12-brief.md`), which
explicitly could not be executed in that environment and were turned into
this runbook instead.

## Before you start: two unconfirmed judgment calls

- **Region.** `VERTEX_LOCATION=us-central1` is what's wired into
  `env.example` and `cloudbuild.yaml`, per the plan brief's suggested
  default. Cloud Run itself runs in `us-east1` (`cloudbuild.yaml`'s
  `_REGION`) — the two don't need to match, but Vertex model availability is
  regional, and this has **not** been confirmed against current Vertex docs.
  Check that the Gemini Flash model actually serves from `us-central1`
  before relying on it. If it doesn't, the location needs changing in three
  places that must stay in sync: `env.example`, all three
  `--set-env-vars` sites in `cloudbuild.yaml`, and whatever you set locally
  in Part 1 below.
- **Model id.** `assistant/models.py`'s `AssistantSettings.model_name`
  defaults to `gemini-2.5-flash`. Part 1, step 6 below is the first real
  test of whether Vertex actually accepts that id.

## Part 1: Smoke test against the real model

This is the only way to verify what `assistant/llm.py` cannot be tested
offline: the Google Gen AI SDK's call shape, the model id, the safety
settings, and — critically — the field names the token counts actually live
under in the response.

### Setup

```bash
gcloud auth application-default login
GOOGLE_CLOUD_PROJECT=<project> VERTEX_LOCATION=us-central1 make run
```

- **Look for:** `make run` starts cleanly; the app loads in the browser as
  normal.
- **A failure here** is almost always ADC, not the app: a
  `DefaultCredentialsError` (or similar) means the `gcloud auth
  application-default login` step didn't complete or the token expired —
  rerun it. A Django startup failure unrelated to credentials is a separate
  problem; don't chase it as if it's the assistant.

Sign in as yourself, then turn `ASSISTANT_ENABLED` on for real at
`/admin/gift/featureflag/` — this affects everyone with access to prod, so
only do this against a `dev` deployment or with people warned, not
casually against `prod`.

### 1. Ask "what lists are there?"

- **Expect:** a real answer naming actual lists from the family roster —
  not "I don't know" and not something generic.
- **A wrong/empty answer** means the roster isn't reaching the model; check
  what `roster_for()` / `system_instructions()` actually produced for this
  request.
- **A 503 with "I couldn't reach my brain just then"** means
  `ModelUnavailable` was raised. `assistant/llm.py` deliberately never logs
  the exception text (only `error_type` — see the comment there on why:
  Vertex validation errors can echo request content, which is conversation
  text, back into the message), so check Cloud Run / Cloud Logging for the
  logged `error_type` and cross-reference. Likely causes, roughly in order:
  wrong project or location, `aiplatform.googleapis.com` not enabled yet, or
  the `roles/aiplatform.user` IAM binding (`google_project_iam_member.vertex_user`
  in `terraform/main.tf`) hasn't propagated yet — that can take a minute or
  two after `terraform apply`.

### 2. Ask "what's on `<someone>`'s list?"

- **Expect:** a tool call happens and the reply names real items from that
  person's list.
- **A hallucinated or generic answer** (no real item names) means the tool
  call either didn't happen or its result isn't making it back to the model
  — check that the second `client.generate()` call's `contents` actually
  includes a `function_response` part with real data in it.

### 3. Ask it to add something to your own list

- **Expect:** an ordinary item appears on your list. The reply does not use
  "surprise" language.
- **Item doesn't appear** but the model says it did: check whether
  `add_item` actually ran and whether it raised something that got
  swallowed.

### 4. Ask it to add something to someone else's list

- **Expect:** the reply says it was added as a surprise. Check the new
  `Item` in the database (or admin) — it must have `is_sneaky=True`.
- **If `is_sneaky` is not `True`:** stop. This is not a smoke-test footnote
  — it's the read-and-add permission boundary itself
  (`gift/rules.py::create_item_for`) not doing what the whole feature exists
  to guarantee. Treat as a real bug, not something to note and move past.

### 5. Open your own list in the browser

- **Expect:** the surprise item added in step 4 does not appear on your own
  list view.
- **If it does appear:** same class of bug as step 4 — check the
  `is_sneaky` filtering wherever visible items are queried for the list
  owner (`visible_items_for` and friends in `gift/rules.py`).

### 6. Check `/admin/assistant/assistantusage/`

- **Expect:** one row for you, this month. `message_count` matches the
  number of user turns you actually sent (steps 1–4 — one user message is
  one message regardless of how many tool-call iterations it took). Both
  `input_tokens` and `output_tokens` are **non-zero**.
- **If either token count is zero, this is the most important failure mode
  in this whole document.** It means `VertexModelClient._to_turn()` in
  `assistant/llm.py` is reading the wrong field names off the real SDK
  response's `usage_metadata` (it currently reads `prompt_token_count` and
  `candidates_token_count`). **Fix `assistant/llm.py`, not the test** — the
  fakes in `assistant/testing.py` return whatever token numbers a test
  scripts them to, so no offline test can ever catch this; only a real
  response object can. If it happens, temporarily log or print
  `response.usage_metadata` during a manual run to see its real attribute
  names, correct `_to_turn()` to match, and repeat step 6 before going any
  further.

### If the model id is rejected

Set the working id at `/admin/assistant/assistantsettings/` (the
`model_name` field) to keep the app running, **and** update the default in
`assistant/models.py` (`AssistantSettings.model_name`'s
`default='gemini-2.5-flash'`) to match — otherwise a fresh install or a
`AssistantSettings` row reset repeats the same failure.

### Also worth checking while you're here: the 80% budget alert

`terraform/monitoring.tf`'s `assistant_budget_warnings` log-based metric
matches the warning `assistant/views.py` logs
(`'Assistant global budget at 80%'`). The payload question that an earlier
version of this document flagged as open is now settled in code:
`giftwiki/settings.py`'s "Configure Cloud Logging" block wires an
`assistant` logger to the same `['cloud', 'console']` handlers as `gift`
(both `propagate: False`, level `INFO`), so in the normal case this record
reaches Cloud Logging structured, through the `CloudLoggingHandler`, the
same confirmed-working path `gift`'s own alert-worthy logs use — the metric
matches it via `jsonPayload.message`. The filter also matches `textPayload`,
not because the payload shape is still in doubt, but because that handler
setup lives inside a `try/except` (`settings.py`'s Cloud Logging block) that
falls back silently if the Cloud Logging client fails to initialize —
in that case the record still reaches Cloud Logging as plain stderr text via
the `console` handler, and `textPayload` is what catches that path.

Still worth a live check, because nothing above was run against a real
Cloud Run deployment. **This check needs an actual deployed Cloud Run
revision — local `make run` cannot exercise it**, even with real Vertex
credentials: `settings.py`'s Cloud Logging block, the `cloud_run_revision`
log resource, and the log-based metric all only exist once the app is
running as a Cloud Run service, not as a local process. Run it against a
`dev` deployment: temporarily set `global_monthly_messages` very low
(e.g. `1`) at `/admin/assistant/assistantsettings/`, send one message, and
confirm a `cloud_run_revision` log entry containing `Assistant global
budget at 80%` shows up in Cloud Logging with `severity: WARNING` (or
higher) and the log-based metric (`giftwiki-dev-assistant-budget-warnings`
or the prod equivalent) actually increments.

## Part 2: Full verification

This one *was* run, in the sandboxed environment, without live Vertex
access — see the Task 12 report for the actual command output and numbers.
Re-run after any further change here:

```bash
make test && make lint
```

Expect green, including `tests/test_deploy_config.py` and
`tests/test_dependency_lock.py`.

**Before any deploy, also check `requirements.txt` by hand, not just the test.**
`Dockerfile.cloudrun` installs from `requirements.txt`, not from the Pipfile —
`tests/test_dependency_lock.py::test_every_shipped_package_is_in_requirements_txt`
now guards this in CI, but that guard only runs if `make test` runs. Before a
deploy specifically:

```bash
grep -q '^google-genai==' requirements.txt && echo "google-genai: present" || echo "MISSING — deploy will ImportError"
```

This is the exact class of bug that shipped invisibly for this feature:
`google-genai` was declared in `Pipfile`/`Pipfile.lock` and every offline test
passed (CI installs with pipenv), but the deployed image installs from
`requirements.txt` alone and had no SDK — the first real assistant turn would
have raised `ImportError`. The Part 1 smoke test below would have caught it
too, but only *after* a deploy; this check catches it before one.

## Part 3: Staged rollout

Cost is the unknown here, not correctness — this is deliberate and slow.
Do not compress it into a single sitting.

1. **Merge with `ASSISTANT_ENABLED` off.** Confirm prod renders no bubble.
2. **Confirm gunicorn's timeout and worker settings deployed.**
   `entrypoint.sh`'s `exec gunicorn` line must carry `--timeout 120
   --workers 2 --threads 4 --worker-class gthread`. Gunicorn's own default
   timeout is 30 seconds with a single sync worker — below
   `assistant/views.py`'s 60-second turn budget, which itself allows up to 5
   calls each capped at `assistant/llm.py`'s 30-second
   `MODEL_TIMEOUT_SECONDS`. Without the explicit flags, a turn running past
   30s gets its gunicorn worker SIGKILLed mid-call: no `except` runs, so
   `refund_message()` never fires and the reservation leaks — a fourth way
   into the same leak that three earlier rounds closed from inside Python,
   this time from outside the process. Check the value actually running,
   not just the file in the repo — confirm the deployed container's start
   command (Cloud Run revision detail, or the container startup log line
   `Starting Gunicorn on 0.0.0.0:<port>...`) reflects it, since a stale
   image or a manual override could still be serving the old default.
3. **Set deliberately low caps.** At `/admin/assistant/assistantsettings/`:
   `per_user_monthly_messages = 30`, `global_monthly_messages = 50`,
   `enabled_until` set a week out.
4. **Turn `ASSISTANT_ENABLED` on.** You are the only one who knows it's
   there yet — this is not the announcement.
5. **Use it for a week.** Read the token totals at
   `/admin/assistant/assistantusage/` as you go, not just at the end.
6. **Set real caps.** Work out the real cost per message from that week's
   token totals and **current** Vertex pricing — look it up fresh, don't
   reuse a number from this document, which will be stale by the time
   you're reading it. Set `per_user_monthly_messages` and
   `global_monthly_messages` to whatever matches a budget you're actually
   happy with, and clear `enabled_until`.
7. **Announce it.** Add a `ChangelogEntry` — the "What's new" card is how
   this app tells the family about a feature. Say there are seven secrets
   hidden in the assistant and that the profile page keeps score; the hunt
   only works if the kids know it's there to look for. Then open it up for
   everyone.

## What this document is not

A report. Every step above is something to do and check, not something
that has been done. Task 12 was implemented and self-reviewed without
Google Cloud credentials or network access to Vertex AI — that's a hard
constraint of the environment it ran in, not a shortcut taken. The owner is
the one who runs Parts 1 and 3.
