terraform {
  required_version = ">= 1.0"
  
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 5.0"
    }
  }
  
  backend "gcs" {
    bucket = "wikileet-terraform-state"
    prefix = "terraform/state"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

# Variables
variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP Region"
  type        = string
  default     = "us-east1"
}

variable "service_name" {
  description = "Cloud Run service name"
  type        = string
  default     = "giftwiki-dev"
}

variable "environment" {
  description = "Environment name (dev, prod)"
  type        = string
  default     = "dev"
}

variable "manage_firebase_hosting" {
  description = "Whether Terraform should manage the Firebase Hosting site (set to false if site exists outside Terraform)"
  type        = bool
  default     = true
}

variable "secret_names" {
  description = "List of secret names (non-sensitive - just the names)"
  type        = list(string)
  default     = []
}

variable "secret_values" {
  description = "Map of secret names to values (sensitive)"
  type        = map(string)
  sensitive   = true
  default     = {}
}

variable "env_vars" {
  description = "Map of environment variable names to values (non-sensitive)"
  type        = map(string)
  default     = {}
}

variable "common_labels" {
  description = "Common labels to apply to all resources"
  type        = map(string)
  default     = {}
}

variable "container_image" {
  description = "Container image URL (e.g., gcr.io/PROJECT_ID/SERVICE_NAME:latest). If not set, will use latest from Cloud Build."
  type        = string
  default     = ""
}

variable "custom_domain" {
  description = "Custom domain for Cloud Run domain mapping"
  type        = string
  default     = ""
}

variable "db_host" {
  description = "Database host"
  type        = string
}

variable "db_name" {
  description = "Database name"
  type        = string
}

variable "firebase_api_key_id" {
  description = "Specific ID for the Firebase API key (to match existing resources). If empty, a name will be generated."
  type        = string
  default     = ""
}

variable "db_port" {
  description = "Database port"
  type        = string
  default     = "5432"
}


variable "google_analytics_ids" {
  description = "Map of environment to Google Analytics Measurement ID"
  type        = map(string)
  default     = {
    dev  = "G-2SKXZF1EPF"
    prod = "G-QT62MRCHZ8"
  }
}


# Enable required APIs
resource "google_project_service" "required_apis" {
  for_each = toset([
    "cloudbuild.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "firebase.googleapis.com",
    "identitytoolkit.googleapis.com",  # Firebase Auth API
    "firebasehosting.googleapis.com",   # Firebase Hosting API
    "monitoring.googleapis.com",        # Cloud Monitoring API
    "logging.googleapis.com",           # Cloud Logging API
    "clouderrorreporting.googleapis.com", # Error Reporting API
    "cloudtrace.googleapis.com",        # Cloud Trace API
    "apikeys.googleapis.com",           # API Keys API
    "cloudbilling.googleapis.com",      # Cloud Billing API
  ])

  project = var.project_id
  service = each.value

  disable_on_destroy = false
}

# Get default compute service account
data "google_project" "project" {
  project_id = var.project_id
}

locals {
  compute_service_account = "${data.google_project.project.number}-compute@developer.gserviceaccount.com"
  # Convert secret names list to set for for_each
  secret_names_set = toset(var.secret_names)
  
  # Common labels for all resources
  common_labels = merge(
    {
      environment = var.environment
      managed-by  = "terraform"
      project     = "gift-wiki"
    },
    var.common_labels
  )
  
  # Build environment variables map for Cloud Run
  # Combine env_vars with database config
  cloud_run_env_vars = merge(
    var.env_vars,
    {
      DJANGO_SETTINGS_MODULE = "giftwiki.settings"
      DJANGO_ALLOWED_HOSTS   = lookup(var.env_vars, "DJANGO_ALLOWED_HOSTS", "*")
      DJANGO_ALLOWED_ORIGINS = lookup(var.env_vars, "DJANGO_ALLOWED_ORIGINS", "http://localhost,https://*.run.app")
      DJANGO_DB_HOST         = var.db_host
      DJANGO_DB_NAME         = var.db_name
      DJANGO_DB_PORT         = var.db_port
      DJANGO_DB_CONN_MAX_AGE = "600"
      USE_S3                 = "TRUE"
      AWS_S3_REGION_NAME     = "us-east-1"
      AWS_STORAGE_BUCKET_NAME = "gift-wiki"
      DJANGO_LOG_LEVEL       = "INFO"
      
      # Firebase Configuration (Injected from Terraform)
      FIREBASE_PROJECT_ID          = var.project_id
      FIREBASE_AUTH_DOMAIN         = "${var.project_id}.firebaseapp.com"
      FIREBASE_STORAGE_BUCKET      = "${var.project_id}.appspot.com"
      FIREBASE_APP_ID              = google_firebase_web_app.app.app_id
      FIREBASE_MESSAGING_SENDER_ID = data.google_project.project.number
      
      # Google Analytics
      GOOGLE_ANALYTICS_ID          = lookup(var.google_analytics_ids, var.environment, "")
    }
  )
  
  # Build secrets map for Cloud Run (using prefixed secret names)
  # Maps environment variable name to secret name
  cloud_run_secrets = {
    "DJANGO_SECRET_KEY"      = "${var.environment}-django-secret-key"
    "DJANGO_DB_USER"          = "${var.environment}-django-db-user"
    "DJANGO_DB_PASSWORD"      = "${var.environment}-django-db-password"
    "AWS_ACCESS_KEY_ID"       = "${var.environment}-aws-access-key-id"
    "AWS_SECRET_ACCESS_KEY"   = "${var.environment}-aws-secret-access-key"
    "FIREBASE_API_KEY"        = "${var.environment}-firebase-api-key"
  }
  
  # Determine container image - use provided or construct from service name
  container_image_url = var.container_image != "" ? var.container_image : "gcr.io/${var.project_id}/${var.service_name}:latest"
}

# Create secrets in Secret Manager
# Prefix secret names with environment to avoid conflicts between dev/prod
resource "google_secret_manager_secret" "secrets" {
  for_each = local.secret_names_set

  secret_id = "${var.environment}-${each.key}"

  replication {
    auto {}
  }

  labels = local.common_labels

  depends_on = [google_project_service.required_apis]
}

resource "google_secret_manager_secret_version" "secrets" {
  for_each = local.secret_names_set

  secret      = google_secret_manager_secret.secrets[each.key].id
  secret_data = var.secret_values[each.key]
}

# Grant service account access to secrets
resource "google_secret_manager_secret_iam_member" "secret_access" {
  for_each = local.secret_names_set

  secret_id = google_secret_manager_secret.secrets[each.key].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.compute_service_account}"

  depends_on = [google_secret_manager_secret_version.secrets]
}


# Generate Firebase API Key automatically
resource "google_apikeys_key" "firebase" {
  name         = var.firebase_api_key_id != "" ? var.firebase_api_key_id : "${var.service_name}-key-v2"
  display_name = "${var.service_name} Firebase Key"
  project      = var.project_id

  restrictions {
    api_targets {
      service = "identitytoolkit.googleapis.com" # Firebase Auth
    }
    api_targets {
      service = "firebase.googleapis.com"
    }
    api_targets {
      service = "firebaseinstallations.googleapis.com"
    }
    api_targets {
      service = "securetoken.googleapis.com"
    }
    
    # Restrict to the specific websites if needed (optional for now to ensure it works)
    # browser_key_restrictions {
    #   allowed_referrers = ["https://${var.service_name}.web.app/*", "https://${var.service_name}.firebaseapp.com/*", "http://localhost:*"]
    # }
  }

  depends_on = [google_project_service.required_apis]
}

# Store the generated API key in Secret Manager
resource "google_secret_manager_secret" "firebase_api_key" {
  secret_id = "${var.environment}-firebase-api-key"
  
  replication {
    auto {}
  }
  
  labels = local.common_labels
  
  depends_on = [google_project_service.required_apis]
}

resource "google_secret_manager_secret_version" "firebase_api_key" {
  secret      = google_secret_manager_secret.firebase_api_key.id
  secret_data = google_apikeys_key.firebase.key_string
}

# Grant access to the generated API Key secret
resource "google_secret_manager_secret_iam_member" "firebase_api_key_access" {
  secret_id = google_secret_manager_secret.firebase_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.compute_service_account}"
  
  depends_on = [google_secret_manager_secret_version.firebase_api_key]
}

# Grant Firebase Admin permissions to service account
resource "google_project_iam_member" "firebase_admin" {
  project = var.project_id
  role    = "roles/firebase.admin"
  member  = "serviceAccount:${local.compute_service_account}"

  depends_on = [google_project_service.required_apis]
}


# Outputs
output "compute_service_account" {
  description = "Compute service account email"
  value       = local.compute_service_account
}

output "secret_names" {
  description = "List of created secret names (with environment prefix)"
  value       = [for k in var.secret_names : "${var.environment}-${k}"]
}

output "secret_mapping" {
  description = "Mapping of original secret names to prefixed names for Cloud Build"
  value = {
    for k in var.secret_names : k => "${var.environment}-${k}"
  }
}

output "environment" {
  description = "Environment name"
  value       = var.environment
}

output "cloud_run_service_name" {
  description = "Cloud Run service name"
  value       = var.service_name
}

# Firebase Project (enables Firebase for the GCP project)
resource "google_firebase_project" "default" {
  provider = google-beta
  project  = var.project_id

  depends_on = [
    google_project_service.required_apis["firebase.googleapis.com"],
  ]
}

# Firebase Web App (for web client authentication)
# app_id is auto-generated and read-only
resource "google_firebase_web_app" "app" {
  provider     = google-beta
  project      = var.project_id
  display_name = "${var.service_name} Web App"

  depends_on = [google_firebase_project.default]
}

# Firebase Hosting Site
# Only create if manage_firebase_hosting is true
resource "google_firebase_hosting_site" "app" {
  count    = var.manage_firebase_hosting ? 1 : 0
  provider = google-beta
  project  = var.project_id
  site_id  = var.environment == "prod" ? "${var.service_name}-v2" : var.service_name
  app_id   = google_firebase_web_app.app.app_id

  depends_on = [
    google_firebase_project.default,
    google_firebase_web_app.app,
    google_project_service.required_apis["firebasehosting.googleapis.com"],
  ]
}

# Cloud Run Domain Mapping
# Maps a custom domain directly to the Cloud Run service (no Firebase Hosting needed)
resource "google_cloud_run_domain_mapping" "app" {
  count    = var.custom_domain != "" ? 1 : 0
  location = var.region
  name     = var.custom_domain

  metadata {
    namespace = var.project_id
  }

  spec {
    route_name = var.service_name
  }
}

output "custom_domain_url" {
  description = "Custom domain URL (after DNS is configured)"
  value       = var.custom_domain != "" ? "https://${var.custom_domain}" : ""
}

output "cloud_run_url" {
  description = "Direct Cloud Run service URL"
  value       = "https://${var.service_name}-${data.google_project.project.number}.${var.region}.run.app"
}

output "firebase_app_id" {
  description = "Firebase Web App ID (for firebase-public/index.html config)"
  value       = google_firebase_web_app.app.app_id
}

# Monitoring and Alerting removed to restore original flow

