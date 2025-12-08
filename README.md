# Django Gift Wiki

A family-oriented gift wish list management application built with Django.

## Features

- 👨‍👩‍👧‍👦 Family-based organization
- 🎁 Wish list creation and management
- 📝 Item tracking with purchase status
- 🎨 Family crest generation (optional, disabled by default)
- 🔐 User authentication and profiles

## Quick Start

### Feature Flag Admin

**NEW:** Manage feature flags from the admin interface!

1. Visit http://localhost:8000/admin/
2. Login with superuser credentials
3. Look for **"Feature Flags"** in the Gift section
4. Toggle features on/off with checkboxes - no server restart needed!

See `FEATURE_FLAG_ADMIN_README.md` for detailed instructions.

## Quick Start (Standard)

### Prerequisites
- Python 3.10+
- pipenv (install via `pip install pipenv`)

### Setup

1. **Clone the repository**
   ```bash
   cd django-gift-wiki
   ```

2. **Install dependencies**
   ```bash
   pipenv install
   ```

3. **Configure environment**
   ```bash
   cp env.example .env
   # Edit .env with your settings
   ```

4. **Run migrations**
   ```bash
   pipenv run python manage.py migrate
   ```

5. **Create superuser (optional)**
   ```bash
   pipenv run python manage.py createsuperuser
   ```

6. **Start development server**
   ```bash
   pipenv run python manage.py runserver
   ```

7. **Access the application**
   - Home: http://localhost:8000/
   - Admin: http://localhost:8000/admin/

8. **Run tests**
   ```bash
   make test           # Run all tests
   make test-cov      # Run with coverage
   make test-api      # Run API tests only
   ```

## Testing

This project uses **pytest**, **pytest-django**, and **pytest-bdd** for comprehensive testing.

### Test Commands

```bash
make test              # Run all tests
make test-cov         # Run with coverage report
make test-unit        # Run unit tests only
make test-api         # Run API tests only
make test-bdd         # Run BDD tests only
make test-parallel    # Run tests in parallel
```

### Test Structure

- `tests/api/` - API and view tests
- `tests/features/` - BDD feature definitions (.feature files)
- `tests/steps/` - BDD step implementations
- `tests/conftest.py` - Shared test fixtures

### Current Test Status

- ✅ Comprehensive test suite covering:
  - View tests (home, wishlist, item, authentication)
  - Business rules (ownership, purchase behavior, soft delete)
  - Managers functionality (multi-user wishlist management)
  - Scraped page import functionality
- ✅ BDD feature files for acceptance testing
- ✅ Test fixtures for common test data

See `tests/README.md` for detailed testing documentation.

## PyCharm Setup

This project is configured for PyCharm:

1. Open project in PyCharm
2. PyCharm should detect the Pipenv virtual environment automatically
3. Use the "giftwiki" run configuration to start the server
4. Use "python manage.py shell" run configuration for Django shell

## Project Structure

```
django-gift-wiki/
├── gift/                    # Main gift management app
│   ├── models.py            # Database models
│   ├── views.py             # View functions
│   ├── forms.py             # Form classes
│   └── templates/           # HTML templates
├── crest_generator/         # Crest generation app (optional)
├── giftwiki/               # Django project settings
│   ├── settings.py         # Configuration
│   └── urls.py             # URL routing
├── deploy/                 # Kubernetes deployment configs
└── requirements.txt         # Python dependencies
```

## Database Models

- **WikiUser**: Custom user model with family associations
- **Family**: Family groups for organizing users
- **WishList**: Gift lists belonging to users
- **Item**: Individual items on wish lists
- **Suggestion**: Suggested variations for items
- **Crest**: Family crest information (if enabled)

## Feature Flags

Enable optional features via environment variables in `.env`:

```bash
# Enable crest generator (optional)
CREST_GENERATOR_ENABLED=TRUE
OPENAI_API_KEY=your-openai-key

# Enable steward/proxy functionality (optional, confusing UI)
STEWARD_PROXY_ENABLED=TRUE
```

See `FEATURE_FLAGS.md` for detailed documentation on all feature flags.

## Development Notes

- Uses SQLite for local development
- PostgreSQL configured for production deployment
- AWS S3 support for media file storage
- Kubernetes-ready with deployment manifests

## Recent Changes

- Crest generator shelved behind feature flag
- Core gift workflow fixed and tested
- All redirect URLs corrected
- Simplified wishlist creation workflow

## License

MIT

