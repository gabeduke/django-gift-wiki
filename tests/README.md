# Test Suite

## Overview

Test suite uses **pytest** + **pytest-django**.

## Layout

```
tests/
├── __init__.py
└── api/              # API / view tests
    ├── test_business_rules.py
    └── test_views.py
```

Shared fixtures live in the project-root `conftest.py` (not `tests/conftest.py`).

## Running Tests

```bash
make test              # all tests
make test-unit         # -m unit only
make test-api          # tests/api/ only
make test-cov          # with coverage + HTML report (open htmlcov/index.html)
make test-parallel     # -n auto
```

Individual file or test:

```bash
pipenv run pytest tests/api/test_views.py::TestHomeView
pipenv run pytest tests/api/test_views.py::TestHomeView::test_home_page_renders -v -s
```

## Fixtures (from root `conftest.py`)

| Fixture | Description |
|---|---|
| `api_client` | Django REST framework `APIClient` |
| `user` | Standard test user (`testuser` / `test@example.com`) |
| `other_user` | Second test user (`otheruser` / `other@example.com`) |
| `family` | Test family |
| `wishlist` | Test wishlist owned by `user` |
| `item` | Test item on `wishlist` |
| `authenticated_user` | Logged-in `client` for `user` |
| `authenticated_other_user` | Logged-in `client` for `other_user` |

The root `conftest.py` also seeds `DJANGO_ALLOWED_USERS` with the two test emails so the Firebase middleware accepts them.

## Markers

Declared in `pytest.ini`:

- `unit` / `integration` / `api` / `ui` / `bdd` / `slow`

Use the markers to scope test runs (e.g. `pipenv run pytest -m unit`).

## Writing Tests

```python
@pytest.mark.unit
class TestMyFeature:
    def test_something(self, authenticated_user, wishlist):
        response = authenticated_user.get(f'/wishlist/{wishlist.id}/')
        assert response.status_code == 200
```

## Debugging

```bash
pipenv run pytest --pdb                         # drop into pdb on failure
pipenv run pytest -v -s tests/api/test_views.py  # verbose + stdout
```

## Troubleshooting

- **Import errors**: confirm `DJANGO_SETTINGS_MODULE=giftwiki.settings` in `pytest.ini`.
- **Allowlist 403s in tests**: root `conftest.py` sets `DJANGO_ALLOWED_USERS` — don't override it in a test without restoring.
- **Assertion failures on response content**: decode with `response.content.decode()` before string matching.
