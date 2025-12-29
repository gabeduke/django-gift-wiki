# Terraform Infrastructure as Code

This directory contains Terraform configuration for managing GCP infrastructure for both dev and prod environments.

## What It Manages

- ✅ Required GCP APIs (Cloud Build, Cloud Run, Secret Manager)
- ✅ Secret Manager secrets (environment-prefixed to avoid conflicts)
- ✅ IAM bindings (service account access to secrets)
- ✅ Firebase Admin permissions

## Environment Profiles

Two environment profiles are configured:
- **dev** - Development environment (`dev.tfvars`)
- **prod** - Production environment (`prod.tfvars`)

Each profile has:
- Environment-specific secrets (from `deploy/{env}/secrets.env`)
- Environment-specific config (from `deploy/{env}/config.env`)
- Separate Cloud Run service names
- Separate database connections

## Setup

1. **Install Terraform**:
   ```bash
   # macOS
   brew install terraform
   
   # Or download from https://www.terraform.io/downloads
   ```

2. **Set Project ID in tfvars files**:
   ```bash
   # Edit terraform/dev.tfvars and terraform/prod.tfvars
   # Set the project_id variable
   ```

3. **Initialize Terraform**:
   ```bash
   make terraform-init ENV=dev
   # or
   make terraform-init ENV=prod
   ```

4. **Review changes**:
   ```bash
   make terraform-plan ENV=dev
   ```

5. **Apply infrastructure**:
   ```bash
   make terraform-apply ENV=dev
   ```

## Usage

### Dev Environment

```bash
# Initialize
make terraform-init ENV=dev

# Plan changes
make terraform-plan ENV=dev

# Apply changes
make terraform-apply ENV=dev

# Or auto-approve
make terraform-apply-auto ENV=dev
```

### Prod Environment

```bash
# Initialize
make terraform-init ENV=prod

# Plan changes
make terraform-plan ENV=prod

# Apply changes (requires confirmation)
make terraform-apply ENV=prod
```

### Quick Commands

```bash
# Show current state
make terraform-show ENV=dev

# Show outputs
make terraform-output ENV=dev

# Destroy infrastructure (⚠️ careful!)
make terraform-destroy ENV=dev
```

## Secret Naming

Secrets are automatically prefixed with the environment name to avoid conflicts:
- Dev: `dev-django-secret-key`, `dev-django-db-user`, etc.
- Prod: `prod-django-secret-key`, `prod-django-db-user`, etc.

This allows both environments to coexist in the same GCP project.

## Integration with Deployment

The `make dev` and `make prod` commands automatically:
1. Set up infrastructure with Terraform
2. Deploy the application

```bash
make dev   # Sets up dev infrastructure and deploys
make prod  # Sets up prod infrastructure and deploys
```

## Updating Secrets

To update secrets:

1. **Edit the tfvars file**:
   ```bash
   # Edit terraform/dev.tfvars
   # Update the secrets map
   ```

2. **Apply changes**:
   ```bash
   make terraform-apply ENV=dev
   ```

Terraform will update the secret versions in Secret Manager.

## State Management

For production, consider using a GCS backend for state:

1. Create a GCS bucket for state
2. Uncomment the `backend "gcs"` block in `main.tf`
3. Update the bucket name
4. Use different state prefixes for dev/prod:
   ```hcl
   backend "gcs" {
     bucket = "your-terraform-state-bucket"
     prefix = "gift-wiki/${var.environment}"
   }
   ```

This enables:
- Team collaboration (shared state)
- State locking (prevents concurrent modifications)
- State history
- Separate state files for dev/prod

## Migration from Scripts

The tfvars files are generated from your existing `deploy/{env}/secrets.env` and `deploy/{env}/config.env` files.

To migrate existing infrastructure:

1. **Import existing secrets** (if they already exist without prefix):
   ```bash
   terraform import google_secret_manager_secret.django-secret-key projects/PROJECT_ID/secrets/django-secret-key
   ```

2. **Or just apply** - Terraform will create new prefixed secrets, then you can:
   - Update Cloud Build to use prefixed names
   - Remove old secrets manually

## Benefits Over Scripts

- ✅ **Declarative**: Describe what you want, not how to get it
- ✅ **State management**: Knows what's deployed
- ✅ **Idempotent**: Safe to run multiple times
- ✅ **Version controlled**: Infrastructure changes are tracked
- ✅ **Dependency management**: Automatically handles dependencies
- ✅ **Plan before apply**: See changes before applying
- ✅ **Environment separation**: Clean separation between dev/prod

## Files

- `main.tf` - Main Terraform configuration
- `dev.tfvars` - Dev environment variables (contains secrets - in .gitignore)
- `prod.tfvars` - Prod environment variables (contains secrets - in .gitignore)
- `terraform.tfvars.example` - Example template (safe to commit)
