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
  
  # Optional: Use GCS backend for state (recommended for team collaboration)
  # backend "gcs" {
  #   bucket = "your-terraform-state-bucket"
  #   prefix = "gift-wiki"
  # }
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

variable "db_host" {
  description = "Database host"
  type        = string
}

variable "db_name" {
  description = "Database name"
  type        = string
}

variable "db_port" {
  description = "Database port"
  type        = string
  default     = "5432"
}

variable "alert_email" {
  description = "Email address for alerts"
  type        = string
  default     = "gabeduke@gmail.com"
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
      DJANGO_ALLOWED_HOSTS   = "*"
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

# Output environment variables for use in Cloud Build
resource "local_file" "env_vars_output" {
  count    = length(var.env_vars) > 0 ? 1 : 0
  filename = "${path.module}/.env_vars_${var.environment}.txt"
  content  = join("\n", [for k, v in var.env_vars : "${k}=${v}"])

  lifecycle {
    ignore_changes = [content]
  }
}

# Generate Firebase API Key automatically
resource "google_apikeys_key" "firebase" {
  name         = "${var.service_name}-key"
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

# Cloud Run Service
resource "google_cloud_run_v2_service" "app" {
  name     = var.service_name
  location = var.region
  project  = var.project_id

  template {
    labels = local.common_labels
    
    containers {
      image = local.container_image_url
      
      # Environment variables
      dynamic "env" {
        for_each = local.cloud_run_env_vars
        content {
          name  = env.key
          value = env.value
        }
      }
      
      # Secrets from Secret Manager
      dynamic "env" {
        for_each = local.cloud_run_secrets
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
      }
      
      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
    
    service_account = local.compute_service_account
  }

  traffic {
    percent = 100
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
  }

  # Allow unauthenticated access (Firebase Auth handles authentication)
  ingress = "INGRESS_TRAFFIC_ALL"

  depends_on = [
    google_project_service.required_apis,
    google_secret_manager_secret_version.secrets,
    google_secret_manager_secret_iam_member.secret_access,
    google_secret_manager_secret_iam_member.firebase_api_key_access,
  ]
}

# Allow unauthenticated access to Cloud Run service
resource "google_cloud_run_service_iam_member" "public_access" {
  service  = google_cloud_run_v2_service.app.name
  location = google_cloud_run_v2_service.app.location
  project  = var.project_id
  role     = "roles/run.invoker"
  member   = "allUsers"

  depends_on = [google_cloud_run_v2_service.app]
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

output "cloud_run_service_url" {
  description = "Cloud Run service URL"
  value       = google_cloud_run_v2_service.app.uri
}

output "cloud_run_service_name" {
  description = "Cloud Run service name"
  value       = google_cloud_run_v2_service.app.name
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
# Only create if manage_firebase_hosting is true (allows skipping for dev if site exists outside Terraform)
resource "google_firebase_hosting_site" "app" {
  count    = var.manage_firebase_hosting ? 1 : 0
  provider = google-beta
  project  = var.project_id
  site_id  = var.service_name
  app_id   = google_firebase_web_app.app.app_id

  depends_on = [
    google_firebase_project.default,
    google_firebase_web_app.app,
    google_project_service.required_apis["firebasehosting.googleapis.com"],
  ]
}

# Output Firebase Hosting URL
output "firebase_hosting_url" {
  description = "Firebase Hosting URL (use this instead of Cloud Run URL directly)"
  value       = var.manage_firebase_hosting ? (google_firebase_hosting_site.app[0].default_url != "" ? google_firebase_hosting_site.app[0].default_url : "https://${google_firebase_hosting_site.app[0].site_id}.web.app") : "https://${var.service_name}.web.app"
}

output "firebase_hosting_alternate_url" {
  description = "Firebase Hosting alternate URL"
  value       = var.manage_firebase_hosting ? "https://${google_firebase_hosting_site.app[0].site_id}.firebaseapp.com" : "https://${var.service_name}.firebaseapp.com"
}

output "firebase_app_id" {
  description = "Firebase Web App ID (for firebase-public/index.html config)"
  value       = google_firebase_web_app.app.app_id
}

# Monitoring and Alerting

# Notification Channel (Email)
resource "google_monitoring_notification_channel" "email" {
  display_name = "Email Notification (${var.environment})"
  type         = "email"
  labels = {
    email_address = var.alert_email
  }
  project = var.project_id
  
  depends_on = [google_project_service.required_apis]
}

# 1. Log-based Alert Policy (Severity >= ERROR)
resource "google_monitoring_alert_policy" "log_error" {
  display_name = "${var.service_name} - Log Error Alert"
  combiner     = "OR"
  project      = var.project_id
  
  conditions {
    display_name = "Log Error"
    condition_matched_log {
      filter = "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"${var.service_name}\" AND severity >= ERROR"
    }
  }

  alert_strategy {
    notification_rate_limit {
      period = "300s" # 5 minutes
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.name]
  
  documentation {
    content = "The ${var.service_name} service logged an error with severity >= ERROR."
  }
  
  depends_on = [google_project_service.required_apis]
}

# 2. Metric Alert Policy (High Latency > 2s p99)
resource "google_monitoring_alert_policy" "high_latency" {
  display_name = "${var.service_name} - High Latency Alert"
  combiner     = "OR"
  project      = var.project_id
  
  conditions {
    display_name = "p99 Latency > 2s"
    condition_threshold {
      filter     = "resource.type = \"cloud_run_revision\" AND resource.labels.service_name = \"${var.service_name}\" AND metric.type = \"run.googleapis.com/request_latencies\""
      duration   = "60s"
      comparison = "COMPARISON_GT"
      
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_PERCENTILE_99"
        cross_series_reducer = "REDUCE_MAX"
      }
      
      threshold_value = 2000 # 2000ms = 2s
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.name]
  
  documentation {
    content = "The ${var.service_name} service is experiencing high latency (p99 > 2s)."
  }

  depends_on = [google_project_service.required_apis]
}

# 3. Metric Alert Policy (High Error Rate - 5xx Errors)
resource "google_monitoring_alert_policy" "error_rate" {
  display_name = "${var.service_name} - High Error Rate Alert"
  combiner     = "OR"
  project      = var.project_id
  
  conditions {
    display_name = "5xx Errors > 0"
    condition_threshold {
      filter     = "resource.type = \"cloud_run_revision\" AND resource.labels.service_name = \"${var.service_name}\" AND metric.type = \"run.googleapis.com/request_count\" AND metric.label.response_code_class = \"5xx\""
      duration   = "60s"
      comparison = "COMPARISON_GT"
      
      aggregations {
        alignment_period     = "60s"
        per_series_aligner   = "ALIGN_RATE"
        cross_series_reducer = "REDUCE_SUM"
      }
      
      threshold_value = 0 # Any 5xx error rate > 0
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.name]
  
  documentation {
    content = "The ${var.service_name} service is returning 5xx errors."
  }

  depends_on = [google_project_service.required_apis]
}

# Service Level Objectives (SLOs)

# Define a custom service for monitoring to ensure stable ID
resource "google_monitoring_custom_service" "app" {
  service_id   = "${var.service_name}-monitoring"
  display_name = "${var.service_name} Monitoring"
  
  telemetry {
    resource_name = "//run.googleapis.com/projects/${var.project_id}/locations/${var.region}/services/${var.service_name}"
  }
}

# 1. Availability SLO (99.9%)
resource "google_monitoring_slo" "availability" {
  service      = google_monitoring_custom_service.app.service_id
  slo_id       = "availability-slo"
  display_name = "Availability SLO (99.9%)"
  project      = var.project_id
  
  goal                = 0.999
  rolling_period_days = 28
  
  request_based_sli {
    good_total_ratio {
      good_service_filter = join(" AND ", [
        "resource.type=\"cloud_run_revision\"",
        "resource.labels.service_name=\"${var.service_name}\"",
        "metric.type=\"run.googleapis.com/request_count\"",
        "metric.label.response_code_class!=\"5xx\""
      ])
      total_service_filter = join(" AND ", [
        "resource.type=\"cloud_run_revision\"",
        "resource.labels.service_name=\"${var.service_name}\"",
        "metric.type=\"run.googleapis.com/request_count\""
      ])
    }
  }
}

# 2. Latency SLO (99% < 1000ms)
resource "google_monitoring_slo" "latency" {
  service      = google_monitoring_custom_service.app.service_id
  slo_id       = "latency-slo"
  display_name = "Latency SLO (99% < 1s)"
  project      = var.project_id
  
  goal                = 0.99
  rolling_period_days = 28
  
  request_based_sli {
    distribution_cut {
      distribution_filter = join(" AND ", [
        "resource.type=\"cloud_run_revision\"",
        "resource.labels.service_name=\"${var.service_name}\"",
        "metric.type=\"run.googleapis.com/request_latencies\""
      ])
      range {
        max = 1000
      }
    }
  }
}

# Burn Rate Alerts (Alert if we burn 2% of budget in 1 hour)
# This detects fast burns (major outages)
# Note: For SLO burn rate, we use a specific filter format
resource "google_monitoring_alert_policy" "burn_rate" {
  display_name = "${var.service_name} - SLO Burn Rate Alert"
  combiner     = "OR"
  project      = var.project_id
  
  conditions {
    display_name = "High Burn Rate (Availability)"
    condition_threshold {
      filter     = "select_slo_burn_rate(\"${google_monitoring_slo.availability.name}\", \"3600s\")"
      duration   = "0s"
      comparison = "COMPARISON_GT"
      threshold_value = 2
    }
  }

  conditions {
    display_name = "High Burn Rate (Latency)"
    condition_threshold {
      filter     = "select_slo_burn_rate(\"${google_monitoring_slo.latency.name}\", \"3600s\")"
      duration   = "0s"
      comparison = "COMPARISON_GT"
      threshold_value = 2
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.name]
  
  documentation {
    content = "The ${var.service_name} service is consuming its error budget too quickly (Burn Rate > 2)."
  }
  
  depends_on = [google_project_service.required_apis]
}

