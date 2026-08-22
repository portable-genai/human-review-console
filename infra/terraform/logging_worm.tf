# WORM audit sink: sign-off events flow to a bucket with retention + a lock, so the sign-off
# trail is immutable. The application already redacts before it logs; this makes the record
# tamper-evident and un-deletable for the retention window. This is the infra half of rule R2.
resource "google_logging_project_bucket_config" "signoff" {
  project        = var.project_id
  location       = local.region
  bucket_id      = "review-console-signoff"
  retention_days = 2555 # 7 years
  locked         = true
}

resource "google_logging_project_sink" "signoff" {
  project     = var.project_id
  name        = "review-console-signoff-sink"
  destination = "logging.googleapis.com/projects/${var.project_id}/locations/${local.region}/buckets/${google_logging_project_bucket_config.signoff.bucket_id}"

  # Only this service's sign-off log stream.
  filter = "logName=\"projects/${var.project_id}/logs/review-console-signoff\""

  unique_writer_identity = true
}
