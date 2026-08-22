locals {
  # Residency: pinned in-country. Do not change without a residency review; the app validates the
  # same allowlist at settings load, so code and infra share one source of truth.
  region = var.region

  service_name = "human-review-console"
  kms_key_name = "review-console-cmek"

  # The in-country locations Org Policy will allow resources to be created in.
  allowed_locations = ["in:asia-southeast1-locations", "in:asia-southeast2-locations"]
}
