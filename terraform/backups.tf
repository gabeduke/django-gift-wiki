#############################################
# Database backups
#############################################
#
# Why this exists: the Neon free plan caps the instant-restore history window at
# 6 hours, and that is a plan ceiling rather than a setting we can raise. Six
# hours is not a backup strategy for data that has been accumulated over years
# and imported from a decade-old PBworks wiki. There has already been one
# recovery incident (2026-07-16).
#
# Dumps land here nightly from .github/workflows/db-backup.yml.

variable "backup_retention_days" {
  description = "Days to keep nightly database dumps before deletion."
  type        = number
  default     = 90
}

variable "backup_writer_sa" {
  description = <<-EOT
    Optional service account email granted object-write on the backup bucket
    (the CI identity that runs the backup workflow). Leave empty if that
    identity already has project-level storage permissions.
  EOT
  type        = string
  default     = ""
}

resource "google_storage_bucket" "db_backups" {
  # Per-environment: prod and dev are separate Terraform workspaces sharing one
  # project, so an unsuffixed name would collide on the second apply.
  name     = "${var.project_id}-db-backups-${var.environment}"
  project  = var.project_id
  location = "US"

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  # Deliberately false. `terraform destroy` must not be able to take the
  # backups with it — that is precisely the situation they exist for.
  force_destroy = false

  lifecycle_rule {
    condition {
      age = var.backup_retention_days
    }
    action {
      type = "Delete"
    }
  }

  # Guard against the bucket being replaced (and emptied) by an innocuous-
  # looking change to a field that forces recreation.
  lifecycle {
    prevent_destroy = true
  }

  labels = var.common_labels
}

resource "google_storage_bucket_iam_member" "backup_writer" {
  count = var.backup_writer_sa != "" ? 1 : 0

  bucket = google_storage_bucket.db_backups.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.backup_writer_sa}"
}

output "db_backup_bucket" {
  description = "GCS bucket holding nightly database dumps"
  value       = google_storage_bucket.db_backups.name
}
