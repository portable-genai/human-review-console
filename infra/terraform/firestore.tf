# The single Native-mode Firestore (default) database for the merged console. One tenant-partitioned
# store under tenants/{tenant} holds BOTH the review queue + sign-off records (reviews) and the case
# state + transition history (cases) as subcollections. In-region, CMEK-encrypted, with delete
# protection so neither the queue nor case history can be dropped by accident.
resource "google_firestore_database" "review" {
  project     = var.project_id
  name        = "(default)"
  location_id = local.region
  type        = "FIRESTORE_NATIVE"

  cmek_config {
    kms_key_name = google_kms_crypto_key.review.id
  }

  delete_protection_state = "DELETE_PROTECTION_ENABLED"

  depends_on = [
    google_project_service.required,
    google_kms_crypto_key_iam_member.firestore,
  ]
}
