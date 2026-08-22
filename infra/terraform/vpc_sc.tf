# VPC Service Controls perimeter around the console's data plane.
#
# Principle map:
#   P-03 (residency + exfiltration control): the perimeter is what stops a sign-off trail or a
#         case record being READ across the boundary into an out-of-jurisdiction project. Org
#         Policy pins where data may be CREATED; VPC-SC pins where it may be reached from.
#   P-09 (zero trust): only the APIs this service actually uses are inside the boundary.
#
# Two toggles, dry-run first:
#   var.enable_vpc_sc  - create the perimeter at all (needs var.access_policy_id).
#   var.vpc_sc_enforce - enforce (true) or DRY-RUN / audit (false, the default). Apply with
#                        false, watch the dry-run violations surfaced by the vpc_sc_violation
#                        alert in monitoring.tf, add the operators to var.operator_members, then
#                        flip to true. Implemented with use_explicit_dry_run_spec: in dry-run the
#                        restricted services live in `spec` (audited only) and `status` stays open.
#
# Honest limit: enforcement can only be PROVEN on a real project (an apply, a violation, an alert
# that fires). This file is the posture as code; the live proof belongs to the deployment record.

locals {
  perimeter_name = "hrz_human_review_console"
  # The console's own data APIs. No AI/ML service appears here: this repo has no model.
  perimeter_restricted_services = [
    "firestore.googleapis.com",
    "cloudtasks.googleapis.com",
    "pubsub.googleapis.com",
    "cloudkms.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "storage.googleapis.com",
    "secretmanager.googleapis.com",
  ]

  access_level_name = "hrz_review_console_operators"
  # An access level is created only when operators are named AND the perimeter exists.
  make_access_level = var.enable_vpc_sc && length(var.operator_members) > 0
  access_level_names = local.make_access_level ? [
    "accessPolicies/${var.access_policy_id}/accessLevels/${local.access_level_name}"
  ] : []
}

# Named operator / CI identities that may reach the restricted APIs from outside the perimeter.
resource "google_access_context_manager_access_level" "operators" {
  count = local.make_access_level ? 1 : 0

  parent = "accessPolicies/${var.access_policy_id}"
  name   = "accessPolicies/${var.access_policy_id}/accessLevels/${local.access_level_name}"
  title  = local.access_level_name

  basic {
    conditions {
      members = var.operator_members
    }
  }
}

resource "google_access_context_manager_service_perimeter" "review" {
  count = var.enable_vpc_sc ? 1 : 0

  parent = "accessPolicies/${var.access_policy_id}"
  name   = "accessPolicies/${var.access_policy_id}/servicePerimeters/${local.perimeter_name}"
  title  = local.perimeter_name

  perimeter_type = "PERIMETER_TYPE_REGULAR"

  # Dry-run (audit) until var.vpc_sc_enforce flips to true.
  use_explicit_dry_run_spec = !var.vpc_sc_enforce

  # Enforced configuration. In dry-run this stays open (nothing restricted).
  status {
    resources           = ["projects/${data.google_project.this.number}"]
    restricted_services = var.vpc_sc_enforce ? local.perimeter_restricted_services : []
    access_levels       = var.vpc_sc_enforce ? local.access_level_names : []

    dynamic "vpc_accessible_services" {
      for_each = var.vpc_sc_enforce ? [1] : []
      content {
        enable_restriction = true
        allowed_services   = local.perimeter_restricted_services
      }
    }
  }

  # Dry-run spec: audited, not enforced. Present only while not enforcing.
  dynamic "spec" {
    for_each = var.vpc_sc_enforce ? [] : [1]
    content {
      resources           = ["projects/${data.google_project.this.number}"]
      restricted_services = local.perimeter_restricted_services
      access_levels       = local.access_level_names

      vpc_accessible_services {
        enable_restriction = true
        allowed_services   = local.perimeter_restricted_services
      }
    }
  }

  depends_on = [google_project_service.required]
}
