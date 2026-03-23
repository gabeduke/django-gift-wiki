# CLAUDE.md — Django Gift Wiki

## Project Overview
Family gift exchange tracker built with Django 5.1 and Firebase Authentication. Users create wishlists within family groups, add items, and other family members can mark items as purchased (hidden from the list owner). Migrated from an old PBworks wiki — scraped wiki import is a core onboarding flow.

## Quick Start
```bash
pipenv install
python manage.py migrate
python manage.py createsuperusers  # Creates default admin users
python manage.py runserver
```

## Architecture

- **Django 5.1** with custom user model (`WikiUser` extends `AbstractUser`)
- **Firebase Auth** — session cookie–based authentication via `FirebaseAuthMiddleware`; no Django username/password login in production
- **Database** — PostgreSQL (Neon) in prod, SQLite locally (auto-detected via `DJANGO_DB_HOST`)
- **Static files** — WhiteNoise (not S3)
- **Media/uploads** — S3 when `USE_S3=TRUE`, local filesystem otherwise
- **Feature flags** — DB-first via `FeatureFlag` model (admin-togglable), env var fallback
- **Monitoring** — Prometheus metrics middleware
- **Deployment** — Cloud Run (primary), Kubernetes manifests in `deploy/`, Terraform in `terraform/`

## Key Directories
```
gift/                    # Main Django app (models, views, forms, templates, middleware)
giftwiki/                # Project settings, feature flags, URL config
tests/                   # pytest suite (api/, e2e/, steps/)
deploy/                  # Kubernetes manifests
terraform/               # Infrastructure as code
firebase-functions/      # Cloud Functions (Node.js) for session cookie creation
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
pytest                            # All tests
pytest -m unit                    # Unit tests only
pytest -m api                     # API/view tests
pytest -m "not slow"              # Skip slow tests
pytest --cov=gift                 # With coverage
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

## Lint / Format
No linter or formatter is currently configured. Consider adding ruff or black.

## Known Gotchas
- `debug_toolbar` URLs are always included in `giftwiki/urls.py` even when `DEBUG=False` — will 404 but still registers the URL pattern
- The `Item.description` field is `TextField()` without `blank=True`, so it's required at the DB level even though forms mark it optional
- Feature flag cache is invalidated on every call to `get_steward_proxy_enabled()` / `get_profile_picture_enabled()`, causing a DB query per flag check per request
- `item_add_ajax` has no ownership check — any authenticated user can add items to any wishlist
- `wishlist_delete` and `item_delete` accept GET requests (no `require_POST`)
