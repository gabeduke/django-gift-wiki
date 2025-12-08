# Development Commands
.PHONY: install setup build run migrate shell createsuperuser test clean
.PHONY: test-cov test-unit test-api test-bdd test-parallel check
.PHONY: docker-build docker-build-no-load docker-build-local docker-push
.PHONY: k8s-deploy k8s-clean

# Variables
PYTHON = pipenv run python
PYTEST = pipenv run pytest
MANAGE = $(PYTHON) manage.py

# Install dependencies
install:
	pipenv install --dev

# Run migrations
migrate:
	$(MANAGE) migrate

# Collect static files
collectstatic:
	$(MANAGE) collectstatic --noinput

# Build the project (migrations + collect static)
build: migrate collectstatic
	@echo "✅ Build complete."

# Set up the project (install + build)
setup: install build
	@echo "✅ Setup complete. Run 'make run' to start the server."

# Run all tests
test:
	$(PYTEST)

# Run tests with coverage
test-cov:
	$(PYTEST) --cov=gift --cov-report=html --cov-report=term-missing

# Run only unit tests
test-unit:
	$(PYTEST) -m unit

# Run only API tests
test-api:
	$(PYTEST) tests/api/

# Run BDD tests
test-bdd:
	$(PYTEST) tests/features/

# Run tests in parallel (faster)
test-parallel:
	$(PYTEST) -n auto

# Run development server (depends on build, but not tests for faster iteration)
run: build
	$(MANAGE) runserver

# Fast dev server - skips collectstatic for faster iteration (CSS/JS changes work without it)
local:
	@echo "🚀 Starting dev server (fast mode - no collectstatic)..."
	$(MANAGE) migrate --check || $(MANAGE) migrate
	$(MANAGE) runserver

# Django shell
shell:
	$(MANAGE) shell

# Create superuser
createsuperuser:
	$(MANAGE) createsuperuser

# Check for issues (depends on build)
check: build
	$(MANAGE) check

# Clean up
clean:
	find . -type d -name "__pycache__" -exec rm -r {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache/ htmlcov/ .coverage

# Docker/Kubernetes Commands
IMAGE_NAME = dukeman/gift-wiki
TAG = latest
PLATFORMS = linux/amd64,linux/arm64

# Build Docker image (depends on tests, uses BuildKit for cache)
docker-build: test
	DOCKER_BUILDKIT=1 docker buildx build --platform $(PLATFORMS) -t $(IMAGE_NAME):$(TAG) --load .

# Build Docker image without loading (faster for CI)
docker-build-no-load: test
	DOCKER_BUILDKIT=1 docker buildx build --platform $(PLATFORMS) -t $(IMAGE_NAME):$(TAG) .

# Push Docker image (depends on docker-build-no-load)
docker-push: docker-build-no-load
	DOCKER_BUILDKIT=1 docker buildx build --platform $(PLATFORMS) -t $(IMAGE_NAME):$(TAG) --push .

# Build for local development (single platform, faster, depends on test)
docker-build-local: test
	DOCKER_BUILDKIT=1 docker build -t $(IMAGE_NAME):$(TAG) .

# Deploy to Kubernetes
dev:
	skaffold run --profile dev

# Clean Kubernetes deployment
prod:
	skaffold run --profile prod
