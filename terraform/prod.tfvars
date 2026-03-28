# Terraform variables for prod environment

project_id   = "wikileet"
region       = "us-east1"
service_name = "giftwiki-prod"
environment  = "prod"

# Database configuration
db_host = "ep-falling-morning-ae2u6rxv-pooler.c-2.us-east-2.aws.neon.tech"
db_name = "neondb"
db_port = "5432"

# Container image (leave empty to use latest from gcr.io/PROJECT_ID/SERVICE_NAME)
container_image = ""

# Common labels applied to all resources
common_labels = {
  namespace   = "wikileet"
  environment = "prod"
}

# Secret names (non-sensitive - just the names)
secret_names = [
  "django-secret-key",
  "django-db-user",
  "django-db-password",
  "aws-access-key-id",
  "aws-secret-access-key"
]

# Secret values are passed via TF_VAR_secret_values env var (not stored in VCS)
# For local dev, create a terraform/secrets.auto.tfvars file with:
#   secret_values = { "django-secret-key" = "...", ... }

# Environment variables (non-sensitive)
env_vars = {
  BASE_DIR               = "/app"
  DJANGO_ALLOWED_HOSTS   = "giftwiki.leetserve.com"
  DJANGO_ALLOWED_ORIGINS = "https://giftwiki.leetserve.com,http://localhost:3000"
  DJANGO_ENVIRONMENT     = "prod"
}

alert_email = "gabeduke@gmail.com"

custom_domain = "giftwiki.leetserve.com"
