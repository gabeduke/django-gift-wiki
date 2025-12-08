# Feature Documentation

All behavior is defined in `.feature` files - these are the single source of truth.

## Feature Files (BDD Specifications)

Location: `tests/features/`

### Core Features
- **application_behavior.feature** - 15 scenarios defining core business rules
- **api_behavior.feature** - 12 scenarios for API contracts  
- **data_integrity.feature** - 10 scenarios for data consistency

### Domain Features
- **item.feature** - Item management flows
- **user.feature** - Authentication and users
- **wishlist.feature** - Wishlist operations

## Running Tests

```bash
# Run all tests
make test

# Run specific feature
pytest tests/features/wishlist.feature

# Run with coverage
pytest --cov

# Run BDD tests only
pytest tests/features/
```

## Writing New Features

1. Create `.feature` file in `tests/features/`
2. Define scenarios in Gherkin
3. Write step definitions in `tests/steps/`
4. Tests execute automatically
5. Feature file IS the documentation

No separate markdown needed - pytest-bdd handles it all!

