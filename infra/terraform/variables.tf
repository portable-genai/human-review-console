variable "project_id" {
  type        = string
  description = "The GCP project to deploy the review console into."
}

variable "container_image" {
  type        = string
  description = "The fully-qualified serving image (Artifact Registry, digest-pinned in prod)."
}

variable "frame_ancestors" {
  type        = string
  description = "CSP frame-ancestors allowlist for the embeddable console (never '*', never empty). Say 'none' to forbid all framing."
  default     = "'self'"

  validation {
    # An empty value would reach the container as REVIEW_FRAME_ANCESTORS="" and emit an empty
    # CSP directive, which browsers discard as a parse error, silently removing the
    # clickjacking control. The service refuses to boot on it; refuse at plan time too.
    condition     = trimspace(var.frame_ancestors) != ""
    error_message = "frame_ancestors must name at least one source. Use \"'self'\" for same-origin only, or \"'none'\" to forbid all framing."
  }
}

variable "iap_audience" {
  type        = string
  description = "Exact IAP protected-resource audience, for example /projects/NUM/global/backendServices/ID."

  validation {
    condition     = startswith(var.iap_audience, "/projects/")
    error_message = "iap_audience must be the exact /projects/... IAP resource audience."
  }
}

variable "iap_entitlements_json" {
  type        = string
  description = "Reviewed Hrz3 export mapping verified IAP subjects to tenant, hosted_domain, and principals."

  validation {
    condition     = can(jsondecode(var.iap_entitlements_json)) && can(tomap(jsondecode(var.iap_entitlements_json)))
    error_message = "iap_entitlements_json must be a JSON object keyed by verified IAP subject."
  }
}

# Where Cloud Tasks deadline timers call back to re-evaluate a case (the adapter appends
# /v1/cases/{id}/evaluate). This is the merged service's own internal LB URL; kept as a variable
# rather than a self-reference to the Cloud Run resource so terraform has no dependency cycle.
# Leave empty until the load balancer fronting the service exists, then set and re-apply.
variable "timer_callback_url" {
  type        = string
  description = "Base URL Cloud Tasks deadline timers POST back to (internal LB in front of this service)."
  default     = ""
}

# Residency is NOT a per-deploy choice: the region is pinned in locals.tf and the app validates
# the same allowlist at settings load. This variable exists only so a plan is rejected if someone
# passes an out-of-country region, mirroring the code-side guard.
variable "region" {
  type        = string
  description = "Deployment region. Must be in the in-country residency allowlist."
  default     = "asia-southeast1"

  validation {
    condition     = contains(["asia-southeast1", "asia-southeast2"], var.region)
    error_message = "region must be in the residency allowlist (asia-southeast1 / asia-southeast2)."
  }
}

# --------------------------------------------------------------------------- #
# VPC Service Controls (dry-run first) and posture alerting.
# --------------------------------------------------------------------------- #

variable "access_policy_id" {
  type        = string
  description = <<-EOT
    Access Context Manager policy id the service perimeter is created under.
    Required when enable_vpc_sc = true. Create once per organization with:
      gcloud access-context-manager policies create --organization=ORG_ID --title="residency"
  EOT
  default     = ""

  validation {
    condition     = !var.enable_vpc_sc || length(var.access_policy_id) > 0
    error_message = "enable_vpc_sc = true requires access_policy_id (or set enable_vpc_sc = false for a project-scoped deploy without an org access policy)."
  }
}

variable "enable_vpc_sc" {
  type        = bool
  description = "Create the VPC Service Controls perimeter around the console's data APIs (P-03)."
  default     = true
}

variable "vpc_sc_enforce" {
  type        = bool
  description = <<-EOT
    Enforce the perimeter (true) or run it in DRY-RUN / audit mode (false, the default).
    Apply with false first, watch the dry-run violation alert, add the operator and CI
    identities to operator_members, then flip to true. Enforcing before the dry-run is
    clean locks the reviewers out of their own console.
  EOT
  default     = false
}

variable "operator_members" {
  type        = list(string)
  description = "Break-glass operator / CI identities allowed to reach the restricted APIs from outside the perimeter (for example user:oncall@example.invalid)."
  default     = []
}

variable "alert_notification_channels" {
  type        = list(string)
  description = "Existing Cloud Monitoring notification channel ids the posture alerts publish to. Empty creates the alert policies with no channel (still visible in the console)."
  default     = []
}
