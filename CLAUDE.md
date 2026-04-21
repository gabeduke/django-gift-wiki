# CLAUDE.md — Django Gift Wiki

## Project Overview
Family gift exchange tracker built with Django 5.1 and Firebase Authentication. Users create wishlists within family groups, add items, and other family members can mark items as purchased (hidden from the list owner). Migrated from an old PBworks wiki — scraped wiki import is a core onboarding flow.

## Quick Start
```bash
make setup   # install deps + migrate + collectstatic
make run     # start dev server
```

## Preferred Commands
**Always use `make` targets instead of raw `pipenv run` or `python manage.py` commands.** This ensures consistent behavior, respects the virtualenv, and works in automated contexts (scheduled agents, CI).

| Task | Command |
|------|---------|
| Install deps | `make install` |
| Run dev server | `make run` |
| Run all tests | `make test` |
| Run unit tests | `make test-unit` |
| Run API tests | `make test-api` |
| Lint | `make lint` |
| Format | `make format` |
| Lint + auto-fix | `make lint-fix` |
| Run migrations | `make migrate` |
| Django shell | `make shell` |

## Architecture

- **Django 5.1** with custom user model (`WikiUser` extends `AbstractUser`)
- **Firebase Auth** — session cookie–based authentication via `FirebaseAuthMiddleware`; `sessionLogin` endpoint is a Django view (not a Firebase Function); no Django username/password login in production
- **Database** — PostgreSQL (Neon) in prod, SQLite locally (auto-detected via `DJANGO_DB_HOST`)
- **Static files** — WhiteNoise (not S3)
- **Media/uploads** — S3 when `USE_S3=TRUE`, local filesystem otherwise
- **Feature flags** — DB-first via `FeatureFlag` model (admin-togglable), env var fallback
- **Monitoring** — Prometheus metrics middleware
- **Deployment** — Cloud Run (primary) via Terraform + GitHub Actions; Kubernetes manifests in `deploy/` are k3s reference/backup only
- **Terraform state** — Remote backend in GCS bucket `wikileet-terraform-state`
- **CI/CD** — GitHub Actions: `deploy.yml` (prod, triggers on push to `main`), `deploy-dev.yml` (dev, triggers on PRs)

## Key Directories
```
gift/                    # Main Django app (models, views, forms, templates, middleware)
giftwiki/                # Project settings, feature flags, URL config
tests/                   # pytest suite (api/)
deploy/base/             # k3s Kubernetes base manifests (reference/backup only)
deploy/dev/              # k3s dev overlay (reference/backup — gitignored config.env)
deploy/prod/             # k3s prod overlay (reference/backup — gitignored config.env)
deploy/cloudrun/         # Active: external-dns DNSEndpoint for Cloud Run domain mapping
terraform/               # Infrastructure as code (remote state: GCS wikileet-terraform-state)
.github/workflows/       # CI/CD: deploy.yml (prod), deploy-dev.yml (dev/PR)
firebase-functions/      # Legacy Cloud Functions (sessionLogin moved to Django)
local-docs/              # Extensive internal documentation
scripts/                 # Helper/utility scripts
```

## Models (gift/models.py)
- `WikiUser` — Custom user with family membership, profile picture, color palette
- `Family` — Grouping unit; wishlists belong to families
- `WishList` — Owned by a user, optional dependent (steward proxy), M2M managers
- `Item` — Belongs to wishlist; soft-delete via `is_deleted`; tracks `purchased_by` and `updated_by`
- `Suggestion` — Attached to items (soft-deletable)
- `Category` — Family-scoped, M2M to items, unique per `(family, name)`
- `ItemGroup` — M2M grouping of items within a wishlist
- `FeatureFlag` — Runtime feature toggles
- `ScrapedWikiPage` / `ScrapedWikiItem` — Legacy wiki import data

## Business Rules
- **Ownership**: Only wishlist owner or managers can add/edit/delete items
- **Purchase**: Only non-owners/non-managers can mark items purchased (prevents spoilers)
- **Purchase toggle**: A user can un-purchase an item they previously marked
- **Steward proxy**: Feature-flagged — allows a "dependent" user to also manage a list
- **Soft delete**: Items use `is_deleted=True`; wishlists use hard delete (CASCADE)
- **Allowlist**: Firebase middleware enforces an email allowlist (env or hardcoded default)

## Feature Flags
Checked at runtime via `get_steward_proxy_enabled()` / `get_profile_picture_enabled()`:
- `STEWARD_PROXY_ENABLED` — Shows dependent/steward fields on wishlists
- `PROFILE_PICTURE_ENABLED` — Enables profile picture upload/display

## Testing
```bash
make test                         # All tests
make test-unit                    # Unit tests only
make test-api                     # API/view tests
make test-bdd                     # BDD scenarios (tests/steps/)
make test-cov                     # With coverage report
make test-parallel                # Parallel (faster)
```
Fixtures are in `tests/conftest.py`. Key fixtures: `user`, `other_user`, `admin_user`, `family`, `wishlist`, `item`, `authenticated_user`, `authenticated_other_user`.

## Common Patterns
- **Category creation**: `__CREATE_NEW__` sentinel value in form dropdowns triggers inline category/family creation
- **Feature flag checks**: Always use `get_steward_proxy_enabled()` (function), not the module-level `STEWARD_PROXY_ENABLED` constant (stale at import time)
- **Item.save()**: Accepts `current_user` kwarg to set `updated_by` before delegating to `super().save()`
- **Profile picture processing**: Handled in `WikiUser.save()` with feature-gate; creates thumbnail + web variants

## Environment Variables
See `env.example` for full list. Critical ones:
- `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`
- `DJANGO_DB_HOST/NAME/USER/PASSWORD` — triggers PostgreSQL mode
- `FIREBASE_API_KEY`, `GOOGLE_APPLICATION_CREDENTIALS`
- `USE_S3`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_STORAGE_BUCKET_NAME`
- `DJANGO_ALLOWED_USERS` — comma-separated email allowlist override
- `STEWARD_PROXY_ENABLED`, `PROFILE_PICTURE_ENABLED` — feature flag env overrides

> **Note:** `deploy/dev/config.env` and `deploy/prod/config.env` are gitignored. `FIREBASE_API_KEY` must be set via `.env` or GH Actions secret — it is not committed.

## Lint / Format
Configured with Ruff. Settings in `pyproject.toml`.
```bash
make lint       # check only
make format     # format in place
make lint-fix   # check + auto-fix
```

## Project Tracking & TODOs
All future features, bugs, and TODOs should be tracked using the [Django Gift Wiki Tracker](https://github.com/users/gabeduke/projects/1) GitHub Project. This helps ensure prioritization and visibility of upcoming work. 
- Use `gh issue create` to add new tasks.
- Reference issue numbers in commit messages and PRs.
- Link all new issues to the GitHub Project board.

## Known Gotchas
- `deploy/dev/` and `deploy/prod/` are k3s overlays kept for reference — the app is **not** deployed to k3s. Active deployment is Cloud Run via `make prod` / `make dev` (Terraform).
- `deploy/cloudrun/` contains the external-dns `DNSEndpoint` — apply with `kubectl apply -k deploy/cloudrun` to sync DNS on the homelab cluster.
- `firebase-functions/index.js` still contains a `sessionLogin` function but it is superseded by the Django view. The Firebase Functions deployment may be stale.
- Terraform state is remote (GCS). Run `terraform init` before local `terraform` commands if the `.terraform/` dir is missing.
