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

# Run E2E tests
# Usage: make test-e2e URL=https://giftwiki-dev.leetserve.com
URL ?= https://giftwiki-dev.leetserve.com
test-e2e:
	@echo "Running E2E tests against $(URL)..."
	pipenv run pytest tests/e2e/ --base-url=$(URL) --headless

# Run E2E tests in visible mode (for local debugging/watching)
test-e2e-watch:
	@echo "Running E2E tests (visible mode) against $(URL)..."
	pipenv run pytest tests/e2e/ --base-url=$(URL)

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

# Cloud Run Configuration
CLOUD_RUN_SERVICE = giftwiki-dev
CLOUD_RUN_REGION = us-east1
GCLOUD = /Users/gabeduke/google-cloud-sdk/bin/gcloud

# Firebase Configuration
FIREBASE = firebase
# Note: giftwiki-dev name was reserved, using giftwiki-dev-42be6 instead
FIREBASE_SITE_DEV = giftwiki-dev-42be6
FIREBASE_SITE_PROD = giftwiki-prod

# Cloud Run Infrastructure Setup (idempotent)
# These targets ensure infrastructure is set up correctly before deployment

# Export Quota Project for Terraform (fixes ADC errors)
export GOOGLE_CLOUD_QUOTA_PROJECT ?= $(shell $(GCLOUD) config get-value project)

# Enable required GCP APIs (idempotent)
cloud-run-enable-apis:
	@echo "Enabling required GCP APIs..."
	@$(GCLOUD) services enable cloudbuild.googleapis.com --quiet || true
	@$(GCLOUD) services enable run.googleapis.com --quiet || true
	@$(GCLOUD) services enable secretmanager.googleapis.com --quiet || true
	@echo "✅ APIs enabled"

# Grant Firebase Admin permissions to Cloud Run service account
cloud-run-grant-firebase-permissions:
	@echo "Granting Firebase Admin permissions to Cloud Run service account..."
	@PROJECT_NUMBER=$$($(GCLOUD) projects describe $$($(GCLOUD) config get-value project) --format='value(projectNumber)') && \
	SERVICE_ACCOUNT="$${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" && \
	echo "Service Account: $$SERVICE_ACCOUNT" && \
	$(GCLOUD) projects add-iam-policy-binding $$($(GCLOUD) config get-value project) \
		--member="serviceAccount:$$SERVICE_ACCOUNT" \
		--role="roles/firebase.admin" 2>/dev/null || echo "  (May already have permissions)" && \
	echo "✅ Firebase permissions granted"

# Set up Cloud Secret Manager secrets (idempotent)
cloud-run-setup-secrets: cloud-run-enable-apis
	@echo "Setting up Cloud Secret Manager secrets..."
	@./scripts/setup-cloud-run-secrets.sh
	@echo "✅ Secrets set up"

# Grant Cloud Run service account access to secrets (idempotent)
cloud-run-grant-secrets-access: cloud-run-setup-secrets
	@echo "Granting Cloud Run service account access to secrets..."
	@PROJECT_NUMBER=$$($(GCLOUD) projects describe $$($(GCLOUD) config get-value project) --format='value(projectNumber)') && \
	SERVICE_ACCOUNT="$${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" && \
	echo "Service Account: $$SERVICE_ACCOUNT" && \
	for secret in django-secret-key django-db-user django-db-password aws-access-key-id aws-secret-access-key; do \
		echo "Granting access to $$secret..."; \
		$(GCLOUD) secrets add-iam-policy-binding $$secret \
			--member="serviceAccount:$$SERVICE_ACCOUNT" \
			--role="roles/secretmanager.secretAccessor" 2>/dev/null || echo "  (Already has access)"; \
	done
	@echo "✅ Secrets access granted"

# Note: With Firebase Auth, we don't need IAM bindings for individual users
# The allowlist is enforced in the Django middleware instead

# Note: With Firebase Auth, Cloud Run service allows unauthenticated access
# Authentication is handled by Firebase client-side and verified in Django middleware

# Ensure Cloud Run infrastructure is set up (idempotent)
# Option 1: Use Terraform (recommended)
cloud-run-ensure-infra-terraform:
	@echo "Setting up infrastructure with Terraform for $(ENV) environment..."
	@$(MAKE) terraform-ensure-infra ENV=$(ENV)
	@echo "✅ Cloud Run infrastructure ready (managed by Terraform)"

# Option 2: Use scripts (legacy)
cloud-run-ensure-infra: cloud-run-grant-secrets-access cloud-run-grant-firebase-permissions
	@echo "✅ Cloud Run infrastructure ready"

# Build and deploy application to Cloud Run
cloud-run-deploy-app:
	@echo "Building and deploying application to Cloud Run..."
	@$(GCLOUD) builds submit \
		--config=cloudbuild.yaml \
		--substitutions=_SERVICE_NAME=$(CLOUD_RUN_SERVICE),_REGION=$(CLOUD_RUN_REGION)
	@echo "✅ Application deployed"

# Manually run database migrations (Cloud Run Job)
cloud-run-migrate-dev:
	@echo "Executing migration job for dev environment..."
	@$(GCLOUD) run jobs execute giftwiki-dev-migrate --region $(CLOUD_RUN_REGION) --wait
	@echo "✅ Migration completed"

cloud-run-migrate-prod:
	@echo "Executing migration job for prod environment..."
	@$(GCLOUD) run jobs execute giftwiki-prod-migrate --region $(CLOUD_RUN_REGION) --wait
	@echo "✅ Migration completed"

# Firebase Deployment
# Ensure Firebase CLI is logged in (idempotent)
firebase-ensure-logged-in:
	@echo "Checking Firebase login status..."
	@$(FIREBASE) login:list > /dev/null 2>&1 || $(FIREBASE) login --no-localhost
	@echo "✅ Firebase logged in"

# Deploy Firebase Hosting for dev environment
firebase-deploy-dev: firebase-ensure-logged-in
	@echo "Deploying Firebase Functions and Hosting for dev environment..."
	@$(FIREBASE) use wikileet
	@# Apply dev target mapping
	@$(FIREBASE) target:apply hosting dev $(FIREBASE_SITE_DEV)
	@echo "Deploying Firebase Functions..."
	@$(FIREBASE) deploy --only functions
	@echo "Deploying Firebase Hosting (dev)..."
	@$(FIREBASE) deploy --only hosting:dev
	@echo "✅ Firebase Functions and Hosting deployed (dev)"
	@echo "Note: If using custom domain, update it in Firebase Console to point to $(FIREBASE_SITE_DEV)"

# Deploy Firebase Hosting for prod environment
firebase-deploy-prod: firebase-ensure-logged-in
	@echo "Deploying Firebase Functions and Hosting for prod environment..."
	@$(FIREBASE) use wikileet
	@# Apply prod target mapping
	@$(FIREBASE) target:apply hosting prod $(FIREBASE_SITE_PROD)
	@echo "Deploying Firebase Functions..."
	@$(FIREBASE) deploy --only functions
	@echo "Deploying Firebase Hosting (prod)..."
	@$(FIREBASE) deploy --only hosting:prod
	@echo "✅ Firebase Functions and Hosting deployed (prod)"

# Deploy to Kubernetes and Cloud Run (Dev) - Full deployment with infrastructure setup
# Uses cloudbuild.yaml with Secret Manager (more secure)
dev: ENV=dev
dev:
	@echo "Step 1: Ensure infrastructure (secrets, IAM, Firebase) with Terraform..."
	@$(MAKE) terraform-init ENV=dev
	@cd terraform && terraform workspace select dev
	@cd terraform && terraform apply -auto-approve -var-file="dev.tfvars" -target=google_project_service.required_apis -target=google_firebase_project.default -target=google_firebase_web_app.app -target=google_secret_manager_secret.secrets -target=google_secret_manager_secret_version.secrets -target=google_secret_manager_secret_iam_member.secret_access -target=google_project_iam_member.firebase_admin -target=google_apikeys_key.firebase -target=google_secret_manager_secret.firebase_api_key -target=google_secret_manager_secret_version.firebase_api_key -target=google_secret_manager_secret_iam_member.firebase_api_key_access || true
	@echo "Step 2: Skip Firebase Hosting site creation (managed outside Terraform for dev)..."
	@echo "Step 3: Deploy Cloud Run application (creates image)..."
	@$(MAKE) cloud-run-deploy-app
	@echo "Step 4: Create Cloud Run service with Terraform (now that image exists)..."
	@cd terraform && terraform apply -auto-approve -var-file="dev.tfvars" -target=google_cloud_run_v2_service.app -target=google_cloud_run_service_iam_member.public_access
	@echo "Step 5: Deploy Firebase Hosting..."
	@$(MAKE) firebase-deploy-dev
	@echo "Step 6: Ensure full infrastructure state (Monitoring, Alerts, etc)..."
	@cd terraform && terraform apply -auto-approve -var-file="dev.tfvars"
	@echo ""
	@echo "Getting Cloud Run service URL..."
	@SERVICE_URL=$$($(GCLOUD) run services describe $(CLOUD_RUN_SERVICE) \
		--region $(CLOUD_RUN_REGION) \
		--format 'value(status.url)' 2>/dev/null) && \
	if [ -n "$$SERVICE_URL" ]; then \
		echo "✅ Service URL: $$SERVICE_URL"; \
	fi
	@echo ""
	@echo "Firebase Hosting URL: https://$(FIREBASE_SITE_DEV).web.app"

# Verify Cloud Run secrets are set up correctly
cloud-run-verify-secrets:
	@./scripts/verify-cloud-run-secrets.sh

# Verify Firebase setup
cloud-run-verify-firebase:
	@echo "Verifying Firebase setup..."
	@PROJECT_NUMBER=$$($(GCLOUD) projects describe $$($(GCLOUD) config get-value project) --format='value(projectNumber)') && \
	SERVICE_ACCOUNT="$${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" && \
	echo "Checking Firebase Admin permissions for: $$SERVICE_ACCOUNT" && \
	IAM_POLICY=$$($(GCLOUD) projects get-iam-policy $$($(GCLOUD) config get-value project) --format=json) && \
	if echo "$$IAM_POLICY" | grep -q "roles/firebase.admin"; then \
		echo "✅ Firebase Admin role found"; \
	else \
		echo "⚠️  Firebase Admin role not found. Run: make cloud-run-grant-firebase-permissions"; \
	fi
	@echo ""
	@echo "Next steps:"
	@echo "1. Set up Firebase Authentication in Firebase Console"
	@echo "2. Add Firebase Auth to your frontend"
	@echo "3. See docs/FIREBASE_AUTH_SETUP.md for details"

# Terraform Infrastructure as Code
# Usage: make terraform-init ENV=dev
#        make terraform-plan ENV=dev
#        make terraform-apply ENV=dev

ENV ?= dev

terraform-init:
	@echo "Initializing Terraform for $(ENV) environment..."
	@cd terraform && terraform init
	@cd terraform && terraform workspace select $(ENV) 2>/dev/null || terraform workspace new $(ENV)

terraform-plan:
	@echo "Planning Terraform changes for $(ENV) environment..."
	@cd terraform && terraform workspace select $(ENV)
	@cd terraform && terraform plan -var-file="$(ENV).tfvars"

terraform-apply:
	@echo "Applying Terraform changes for $(ENV) environment..."
	@cd terraform && terraform workspace select $(ENV)
	@cd terraform && terraform apply -var-file="$(ENV).tfvars"

terraform-apply-auto:
	@echo "Applying Terraform changes for $(ENV) environment (auto-approve)..."
	@cd terraform && terraform workspace select $(ENV)
	@cd terraform && terraform apply -auto-approve -var-file="$(ENV).tfvars"

terraform-destroy:
	@echo "⚠️  Destroying Terraform infrastructure for $(ENV) environment..."
	@cd terraform && terraform workspace select $(ENV)
	@cd terraform && terraform destroy -var-file="$(ENV).tfvars"

terraform-show:
	@echo "Showing Terraform state for $(ENV) environment..."
	@cd terraform && terraform workspace select $(ENV)
	@cd terraform && terraform show

terraform-output:
	@echo "Terraform outputs for $(ENV) environment:"
	@cd terraform && terraform workspace select $(ENV)
	@cd terraform && terraform output

# List existing secrets (created by scripts, not Terraform)
terraform-list-old-secrets:
	@echo "Listing existing secrets (created by scripts)..."
	@$(GCLOUD) secrets list --filter="name:django-secret-key OR name:django-db-user OR name:django-db-password OR name:aws-access-key-id OR name:aws-secret-access-key" --format="table(name,createTime,labels)"

# List Terraform-managed secrets
terraform-list-managed-secrets:
	@echo "Listing Terraform-managed secrets for $(ENV) environment..."
	@$(GCLOUD) secrets list --filter="labels.managed-by=terraform AND labels.environment=$(ENV)" --format="table(name,createTime,labels)"

# Ensure infrastructure with Terraform (alternative to script-based setup)
terraform-ensure-infra: terraform-init
	@echo "Applying Terraform infrastructure for $(ENV) environment..."
	@cd terraform && terraform workspace select $(ENV)
	@cd terraform && terraform apply -auto-approve -var-file="$(ENV).tfvars"
	@echo "✅ Infrastructure managed by Terraform"

# Deploy to Kubernetes and Cloud Run (Prod)
prod: ENV=prod
prod:
	@echo "Step 1: Ensure infrastructure (secrets, IAM, Firebase) with Terraform..."
	@$(MAKE) terraform-init ENV=prod
	@cd terraform && terraform workspace select prod
	@cd terraform && terraform apply -auto-approve -var-file="prod.tfvars" -target=google_project_service.required_apis -target=google_firebase_project.default -target=google_firebase_web_app.app -target=google_firebase_hosting_site.app -target=google_secret_manager_secret.secrets -target=google_secret_manager_secret_version.secrets -target=google_secret_manager_secret_iam_member.secret_access -target=google_project_iam_member.firebase_admin -target=google_apikeys_key.firebase -target=google_secret_manager_secret.firebase_api_key -target=google_secret_manager_secret_version.firebase_api_key -target=google_secret_manager_secret_iam_member.firebase_api_key_access || true
	@echo "Step 2: Deploy Cloud Run application (creates image)..."
	@$(GCLOUD) builds submit \
		--config=cloudbuild.yaml \
		--substitutions=_SERVICE_NAME=giftwiki-prod,_REGION=us-east1
	@echo "Step 3: Create Cloud Run service with Terraform (now that image exists)..."
	@cd terraform && terraform apply -auto-approve -var-file="prod.tfvars" -target=google_cloud_run_v2_service.app -target=google_cloud_run_service_iam_member.public_access
	@echo "Step 4: Deploy Firebase Hosting..."
	@$(MAKE) firebase-deploy-prod
	@echo "Step 5: Ensure full infrastructure state (Monitoring, Alerts, etc)..."
	@cd terraform && terraform apply -auto-approve -var-file="prod.tfvars"
	@echo ""
	@echo "Firebase Hosting URL: https://$(FIREBASE_SITE_PROD).web.app"
