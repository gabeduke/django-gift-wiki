#############################################
# Monitoring: database connectivity alerting
#############################################
#
# Goal: know that the database is down before family does, so the outage can be
# explained rather than discovered.
#
# DO NOT solve this with a Cloud Monitoring uptime check against /health/db/.
# An uptime check polls on a fixed interval, /health/db/ runs a real query, and
# Neon suspends its compute after 5 minutes idle — so a 1- or 5-minute uptime
# check would hold the compute awake permanently. That is precisely the bug that
# put this project on a paid plan (see PR #93). On the free plan it would burn
# the 100 CU-hour monthly allowance and suspend the database outright.
#
# This is passive instead: it counts database errors the application already
# logs, so it costs nothing and cannot keep the database awake.

variable "alert_email" {
  description = "Email address for monitoring alerts. Empty disables alerting."
  type        = string
  default     = ""
}

locals {
  alerting_enabled = var.alert_email != "" ? 1 : 0

  # Failure modes actually observed on this service:
  #   OperationalError                      Django cannot reach Postgres at all
  #   could not connect to server           Neon endpoint unreachable
  #   SSL connection has been closed        Neon mid-request SSL drop (issue #12)
  #   server closed the connection          compute suspended under an open conn
  #   Database check failed                 /health/db/ readiness probe failing
  db_error_pattern = join("|", [
    "OperationalError",
    "could not connect to server",
    "SSL connection has been closed",
    "server closed the connection",
    "Database check failed",
  ])
}

# Log-based counter. Created unconditionally: log metrics only count from the
# moment they exist, so having it in place before alerting is switched on means
# there is history to look at.
resource "google_logging_metric" "db_connection_errors" {
  name        = "${var.service_name}-db-connection-errors"
  description = "Database connectivity errors logged by ${var.service_name}"
  project     = var.project_id

  filter = <<-EOT
    resource.type="cloud_run_revision"
    resource.labels.service_name="${var.service_name}"
    severity>=ERROR
    (textPayload=~"${local.db_error_pattern}" OR jsonPayload.message=~"${local.db_error_pattern}")
  EOT

  metric_descriptor {
    metric_kind  = "DELTA"
    value_type   = "INT64"
    unit         = "1"
    display_name = "DB connection errors"
  }
}

resource "google_monitoring_notification_channel" "alert_email" {
  count = local.alerting_enabled

  project      = var.project_id
  display_name = "${var.service_name} alerts"
  type         = "email"

  labels = {
    email_address = var.alert_email
  }
}

resource "google_monitoring_alert_policy" "db_connection_errors" {
  count = local.alerting_enabled

  project      = var.project_id
  display_name = "${var.service_name}: database unreachable"
  combiner     = "OR"
  severity     = "ERROR"

  notification_channels = [google_monitoring_notification_channel.alert_email[0].id]

  conditions {
    display_name = "Database connection errors in the last 5 minutes"

    condition_threshold {
      filter = join(" AND ", [
        "metric.type=\"logging.googleapis.com/user/${google_logging_metric.db_connection_errors.name}\"",
        "resource.type=\"cloud_run_revision\"",
      ])

      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "60s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }

      trigger {
        count = 1
      }
    }
  }

  alert_strategy {
    # Close on its own once errors stop, so a recovered blip does not sit open.
    auto_close = "1800s"
  }

  documentation {
    mime_type = "text/markdown"
    content   = <<-EOT
      **${var.service_name} cannot reach its database.**

      Most likely causes, in the order worth checking:

      1. **Free-tier compute suspended.** Exceeding 100 CU-hours in a billing
         period suspends the Neon compute until the period resets. Check the
         `Neon quota watch` GitHub Actions workflow and the Neon console.
      2. **Neon endpoint down or waking.** A cold start after 5 minutes idle is
         normal and brief; sustained errors are not.
      3. **Credential or network change.** Check the Cloud Run service's
         database secrets.

      This alert is driven by application error logs, not by polling the
      database. Do not "improve" it with an uptime check against `/health/db/`
      — that would keep the Neon compute awake permanently and can itself cause
      the outage this alert is meant to report.
    EOT
  }
}

output "db_alerting_enabled" {
  description = "Whether database connectivity alerting is configured"
  value       = local.alerting_enabled == 1 ? "enabled (${var.alert_email})" : "disabled (set alert_email)"
}
