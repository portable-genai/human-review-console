# Posture alerting: log-based metrics plus alert policies.
#
# Principle map:
#   P-07 (auditable by design): the WORM bucket RECORDS, it does not DETECT. These metrics turn
#         the recorded signal into a notification, which is what makes the dry-run-first VPC-SC
#         rollout workable: the violation alert is how an operator sees who would have been
#         blocked before var.vpc_sc_enforce flips to true.
#   P-09 (zero trust): a service-account key creation or a CMEK change is alerted, not just
#         forbidden, because an org-policy exception is exactly the event worth waking up for.
#
# Alert policies are always created; var.alert_notification_channels attaches channels (an empty
# list still creates the policy, just with nowhere to notify - wire a channel before production).

locals {
  metric_prefix = "hrz_review_console"

  security_metrics = {
    vpc_sc_violation = {
      description = "VPC Service Controls violation (dry-run or enforced)"
      filter      = "protoPayload.metadata.@type=\"type.googleapis.com/google.cloud.audit.VpcServiceControlAuditMetadata\""
    }
    sa_key_creation = {
      description = "Service-account key created (org policy should forbid this)"
      filter      = "protoPayload.methodName=\"google.iam.admin.v1.CreateServiceAccountKey\""
    }
    cmek_change = {
      description = "CMEK key destroy or update operation"
      filter      = "protoPayload.serviceName=\"cloudkms.googleapis.com\" AND (protoPayload.methodName:\"DestroyCryptoKeyVersion\" OR protoPayload.methodName:\"UpdateCryptoKey\")"
    }
    residency_violation = {
      description = "Resource creation refused by the gcp.resourceLocations residency policy"
      filter      = "protoPayload.status.message:\"constraints/gcp.resourceLocations\""
    }
    signoff_denied = {
      description = "A disposition was refused by the fail-closed eligibility rules"
      filter      = "logName=\"projects/${var.project_id}/logs/review-console-signoff\" AND jsonPayload.decision=\"denied\""
    }
  }
}

resource "google_logging_metric" "security" {
  for_each = local.security_metrics

  project     = var.project_id
  name        = "${local.metric_prefix}_${each.key}"
  description = each.value.description
  filter      = each.value.filter

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }

  depends_on = [google_project_service.required]
}

resource "google_monitoring_alert_policy" "security" {
  for_each = local.security_metrics

  project      = var.project_id
  display_name = "human-review-console security: ${each.key}"
  combiner     = "OR"

  conditions {
    display_name = each.value.description

    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.security[each.key].name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_DELTA"
        cross_series_reducer = "REDUCE_SUM"
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = var.alert_notification_channels

  documentation {
    content   = "Security signal '${each.key}' fired for the Hrz7 human-review console. Investigate the matching entries in Cloud Logging and the locked sign-off bucket."
    mime_type = "text/markdown"
  }

  depends_on = [google_project_service.required]
}
