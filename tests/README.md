# Test Suite Documentation

## Overview

This test suite uses **pytest**, **pytest-django**, and **pytest-bdd** for comprehensive testing of the gift wiki application.

## Test Structure

```
tests/
├── __init__.py
├── conftest.py           # Shared fixtures
├── features/             # BDD feature files (.feature)
│   ├── wishlist.feature
│   ├── item.feature
│   └── user.feature
├── steps/                # BDD step definitions
│   └── test_wishlist_steps.py
├── api/                  # API/View tests
│   └── test_views.py
└── ui/                   # UI/integration tests (future)
```

## Running Tests

### All Tests
```bash
make test
```

### With Coverage Report
```bash
make test-cov
# View HTML report: open htmlcov/index.html
```

### Specific Test Types
```bash
make test-unit        # Unit tests only
make test-api         # API tests only
make test-bdd         # BDD tests only
```

### Individual Test Files
```bash
pytest tests/api/test_views.py::TestHomeView
pytest tests/features/ -k wishlist
```

### Verbose Output
```bash
pytest -v -s
```

## Writing Tests

### Unit Tests (API/Views)

```python
@pytest.mark.unit
class TestMyFeature:
    def test_something(self, authenticated_user, wishlist):
        response = authenticated_user.get(f'/wishlist/{wishlist.id}/')
        assert response.status_code == 200
```

### BDD Tests

1. Write feature file in `tests/features/`:
```gherkin
Feature: My Feature
  Scenario: Do something
    Given I am logged in
    When I do something
    Then I should see results
```

2. Implement steps in `tests/steps/`:
```python
@given("I am logged in")
def logged_in(authenticated_user):
    return authenticated_user

@when("I do something")
def do_something(authenticated_user):
    response = authenticated_user.post('/endpoint/', data)
    return response
```

## Fixtures

All fixtures are defined in `conftest.py`:

- `api_client` - Django REST framework APIClient
- `user` - Standard test user (testuser)
- `other_user` - Another test user (otheruser)
- `family` - Test family
- `wishlist` - Test wishlist (owned by `user`)
- `item` - Test item (on `wishlist`)
- `authenticated_user` - Logged-in client for `user`
- `authenticated_other_user` - Logged-in client for `other_user`

## Markers

Tests are marked for organization:

- `@pytest.mark.unit` - Unit tests
- `@pytest.mark.integration` - Integration tests
- `@pytest.mark.api` - API tests
- `@pytest.mark.ui` - UI tests
- `@pytest.mark.bdd` - BDD tests
- `@pytest.mark.slow` - Slow tests

## Best Practices

1. **Write tests first** (TDD approach)
2. **Use fixtures** for test data
3. **Keep tests isolated** and independent
4. **Mock external services** (OpenAI, S3)
5. **Use descriptive test names**
6. **Follow AAA pattern**: Arrange, Act, Assert

## CI/CD Integration

Tests run automatically in CI/CD pipeline. Coverage reports are generated and tracked.

## Debugging Tests

```bash
# Run with pdb on failure
pytest --pdb

# Run specific test with output
pytest -v -s tests/api/test_views.py::TestHomeView::test_home_page_renders

# Print all print statements
pytest -s
```

## Coverage Goals

- Target: 80% coverage for gift app
- Critical paths: 100% coverage
- BDD tests: Cover all user flows

## Troubleshooting

### Import Errors
- Ensure `pytest.ini` has correct `DJANGO_SETTINGS_MODULE`
- Check that `conftest.py` is in the right location

### Database Issues
- Tests use separate test database
- Database is reset between test runs
- Use fixtures instead of direct database access

### Assertion Failures
- Check response status codes
- Verify content is present with proper encoding
- Use `response.content.decode()` for string matching

