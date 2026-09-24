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

#############################################
# Monitoring: assistant budget alerting
#############################################
#
# Goal: know when the family is approaching the assistant's monthly message
# ceiling before the cap actually closes the door on someone.
#
# Same passive shape as the database alert above, for the same reason: the
# turn loop already logs a warning the moment a turn pushes global usage to
# 80% of AssistantSettings.global_monthly_messages (assistant/views.py, just
# before record_tokens()). This counts that log line. Nothing here calls the
# app on a schedule — the alert only exists because a real user turn already
# ran and logged it.

locals {
  # The exact string assistant/views.py logs — keep these in sync if either
  # changes. giftwiki/settings.py wires the `assistant` logger to the same
  # CloudLoggingHandler as `gift` (both go through ['cloud', 'console']), so
  # in the normal case this arrives structured and the match is on
  # jsonPayload.message. The filter also matches textPayload, same as
  # db_error_pattern above: that handler setup lives inside a try/except
  # (settings.py's "Configure Cloud Logging" block) that falls back silently
  # if the Cloud Logging client fails to initialize, in which case the
  # record still reaches stderr as plain text via the `console` handler —
  # this is what the textPayload half of the filter is for, not uncertainty
  # about the structured path.
  assistant_budget_pattern = "Assistant global budget at 80%"
}

resource "google_logging_metric" "assistant_budget_warnings" {
  name        = "${var.service_name}-assistant-budget-warnings"
  description = "Assistant global budget crossed 80% of its monthly ceiling, logged by ${var.service_name}"
  project     = var.project_id

  filter = <<-EOT
    resource.type="cloud_run_revision"
    resource.labels.service_name="${var.service_name}"
    severity>=WARNING
    (textPayload=~"${local.assistant_budget_pattern}" OR jsonPayload.message=~"${local.assistant_budget_pattern}")
  EOT

  metric_descriptor {
    metric_kind  = "DELTA"
    value_type   = "INT64"
    unit         = "1"
    display_name = "Assistant budget warnings"
  }
}

resource "google_monitoring_alert_policy" "assistant_budget_warning" {
  count = local.alerting_enabled

  project      = var.project_id
  display_name = "${var.service_name}: assistant budget at 80%"
  combiner     = "OR"
  severity     = "WARNING"

  notification_channels = [google_monitoring_notification_channel.alert_email[0].id]

  conditions {
    display_name = "Assistant global budget warning logged"

    condition_threshold {
      filter = join(" AND ", [
        "metric.type=\"logging.googleapis.com/user/${google_logging_metric.assistant_budget_warnings.name}\"",
        "resource.type=\"cloud_run_revision\"",
      ])

      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "60s"

      aggregations {
        # A day, not five minutes: this is a budget getting close, not an
        # outage, and the same 80% line will keep logging on every turn for
        # the rest of the month once crossed. One notification a day is
        # plenty; nobody needs to be paged again for the tenth message after
        # the cap was already close.
        alignment_period   = "86400s"
        per_series_aligner = "ALIGN_SUM"
      }

      trigger {
        count = 1
      }
    }
  }

  alert_strategy {
    auto_close = "86400s"
  }

  documentation {
    mime_type = "text/markdown"
    content   = <<-EOT
      **${var.service_name}'s in-app assistant is at 80% of its global monthly
      message ceiling.**

      This is informational, not an outage — the assistant still works. It
      means the family is on track to hit `AssistantSettings.global_monthly_messages`
      before the month resets, and the *next* person to reach the cap will be
      told no.

      What to do:

      1. Check `/admin/assistant/assistantusage/` for the current month's
         message and token totals per user.
      2. Decide whether to raise `global_monthly_messages` at
         `/admin/assistant/assistantsettings/`, or let the cap hold.
      3. If this fires repeatedly early in the month, the caps set during the
         staged rollout may need revisiting against real Vertex pricing — see
         the assistant runbook in `local-docs/`.

      This alert is driven by an application log line (`assistant/views.py`,
      logged just before token usage is recorded on any turn that crosses the
      threshold), not by polling anything — consistent with the standing rule
      against scheduled hits on DB-backed endpoints (see the database alert
      above). It reuses that alert's notification channel.
    EOT
  }
}

output "assistant_budget_alerting_enabled" {
  description = "Whether assistant budget alerting is configured"
  value       = local.alerting_enabled == 1 ? "enabled (${var.alert_email})" : "disabled (set alert_email)"
}
