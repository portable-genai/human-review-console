# One regional CMEK key. Encryption is bound per service via explicit IAM bindings (no
# project-wide grant): Firestore, the WORM log bucket, and the Cloud Run revision all use it.
resource "google_kms_key_ring" "review" {
  count    = var.cmek_enabled ? 1 : 0
  name     = "review-console-keyring"
  location = local.region
  project  = var.project_id
}

resource "google_kms_crypto_key" "review" {
  count           = var.cmek_enabled ? 1 : 0
  name            = local.kms_key_name
  key_ring        = one(google_kms_key_ring.review[*].id)
  rotation_period = "7776000s" # 90 days
  purpose         = "ENCRYPT_DECRYPT"

  lifecycle {
    prevent_destroy = true
  }
}

# Grant the per-service agents encrypt/decrypt on this key only.
resource "google_kms_crypto_key_iam_member" "firestore" {
  count         = var.cmek_enabled ? 1 : 0
  crypto_key_id = one(google_kms_crypto_key.review[*].id)
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-firestore.iam.gserviceaccount.com"
}

resource "google_kms_crypto_key_iam_member" "run" {
  count         = var.cmek_enabled ? 1 : 0
  crypto_key_id = one(google_kms_crypto_key.review[*].id)
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:service-${data.google_project.this.number}@serverless-robot-prod.iam.gserviceaccount.com"
}

data "google_project" "this" {
  project_id = var.project_id
}
