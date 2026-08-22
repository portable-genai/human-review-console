# Residency allowlist: resources may only be created in the in-country locations. A deploy that
# tries to place data elsewhere fails at plan/apply, so residency is enforced, not documented.
resource "google_project_organization_policy" "resource_locations" {
  project    = var.project_id
  constraint = "gcp.resourceLocations"

  list_policy {
    allow {
      values = local.allowed_locations
    }
  }
}

# No service-account keys: use Workload Identity instead (keys are exfiltratable long-lived creds).
resource "google_project_organization_policy" "no_sa_keys" {
  project    = var.project_id
  constraint = "iam.disableServiceAccountKeyCreation"

  boolean_policy {
    enforced = true
  }
}
