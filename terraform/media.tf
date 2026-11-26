#############################################
# Media uploads (profile, cover and gift photos)
#############################################
#
# Replaces the AWS S3 bucket. Cloud Run signs in to this bucket as its own
# service account, so there is no storage key to leak, rotate or let die: an
# S3 access key that quietly stopped existing is what made every photo upload
# 500 in Nov 2026.
#
# Django reads the bucket name from GS_BUCKET_NAME (set in cloudbuild.yaml,
# which is what actually deploys the service). Settings: giftwiki/settings.py.

resource "google_storage_bucket" "media" {
  # Per-environment: prod and dev are separate Terraform workspaces sharing one
  # project, so an unsuffixed name would collide on the second apply. The
  # names are also hard-coded in cloudbuild.yaml (dev default) and deploy.yml
  # (prod); tests/test_deploy_config.py checks they stay in step.
  name     = "${var.project_id}-media-${var.environment}"
  project  = var.project_id
  location = upper(var.region)

  uniform_bucket_level_access = true
  # Photos are served straight from the bucket, so public reads must be allowed.
  public_access_prevention = "inherited"

  # Deliberately false, and guarded below: these are people's photos.
  force_destroy = false

  lifecycle {
    prevent_destroy = true
  }

  labels = local.common_labels
}

# The app reads, writes and deletes objects. No bucket-level admin.
resource "google_storage_bucket_iam_member" "media_app" {
  bucket = google_storage_bucket.media.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${local.compute_service_account}"
}

# Anyone can fetch a photo whose name they already have (the URLs on the page),
# but nobody can list the bucket. roles/storage.objectViewer would also grant
# storage.objects.list, letting anyone enumerate every photo and undoing the
# random uuid names. Private files (exchange letter photos) are never linked
# directly; they are streamed through an access-checked view.
resource "google_storage_bucket_iam_member" "media_public_read" {
  bucket = google_storage_bucket.media.name
  role   = "roles/storage.legacyObjectReader"
  member = "allUsers"
}

output "media_bucket" {
  description = "GCS bucket holding user uploads"
  value       = google_storage_bucket.media.name
}
