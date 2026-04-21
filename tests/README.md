# Test Suite

## Overview

Test suite uses **pytest** + **pytest-django**.

## Layout

```
tests/
├── __init__.py
├── api/              # API / view tests (plain pytest)
│   ├── test_business_rules.py
│   └── test_views.py
├── features/         # Gherkin .feature files (BDD specs)
│   ├── allowlist.feature
│   ├── feature_flags.feature
│   ├── ownership.feature
│   └── purchase.feature
└── steps/            # Step definitions (pytest-bdd)
    ├── test_allowlist.py
    ├── test_feature_flags.py
    ├── test_ownership.py
    └── test_purchase.py
```

Shared fixtures live in the project-root `conftest.py` (not `tests/conftest.py`).

## Running Tests

```bash
make test              # all tests
make test-unit         # -m unit only
make test-api          # tests/api/ only
make test-bdd          # tests/steps/ (BDD scenarios) only
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

## BDD tests

Business rules are specified as Gherkin scenarios in `tests/features/*.feature`
and wired to step definitions in `tests/steps/test_*.py`. Pytest-bdd discovers
scenarios via the step modules (which call `scenarios(...)`), not by scanning
`.feature` files directly — so every feature file needs a matching
`test_<name>.py` that loads it.

Keep step defs **scoped to their own module**. Pytest-bdd only reads step
functions from the module that registers the scenarios, so two features can
share a phrase like `Given an item on that wishlist` without colliding.

Example — `tests/features/ownership.feature`:

```gherkin
Feature: Wishlist ownership rules

  Scenario: Owner can edit items on their wishlist
    Given a wishlist owned by the current user
    And an item on that wishlist
    When the owner edits the item name to "Edited by owner"
    Then the item name is "Edited by owner"
```

And `tests/steps/test_ownership.py`:

```python
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

pytestmark = pytest.mark.bdd
scenarios(str(Path(__file__).parent.parent / 'features' / 'ownership.feature'))


@given('a wishlist owned by the current user', target_fixture='owned_wishlist')
def owned_wishlist(wishlist):
    return wishlist


@when(parsers.parse('the owner edits the item name to "{new_name}"'))
def owner_edits_item(authenticated_user, owned_item, new_name):
    authenticated_user.post(
        f'/item/edit/{owned_item.id}/',
        {'name': new_name, 'description': owned_item.description or ''},
    )


@then(parsers.parse('the item name is "{expected_name}"'))
def item_name_is(owned_item, expected_name):
    owned_item.refresh_from_db()
    assert owned_item.name == expected_name
```

Run `make test-bdd` (or `pipenv run pytest -m bdd`) to exercise just the BDD
scenarios.

## CI

The `.github/workflows/test.yml` workflow runs `make lint` and `make test` on
every pull request and on pushes to `main`. No repo secrets are required —
`conftest.py` defaults `DJANGO_ALLOWED_USERS` so the suite is self-bootstrapping.

## Debugging

```bash
pipenv run pytest --pdb                         # drop into pdb on failure
pipenv run pytest -v -s tests/api/test_views.py  # verbose + stdout
```

## Troubleshooting

- **Import errors**: confirm `DJANGO_SETTINGS_MODULE=giftwiki.settings` in `pytest.ini`.
- **Allowlist 403s in tests**: root `conftest.py` sets `DJANGO_ALLOWED_USERS` — don't override it in a test without restoring.
- **Assertion failures on response content**: decode with `response.content.decode()` before string matching.
