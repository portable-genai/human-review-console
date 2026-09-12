# WORM audit sink: sign-off events flow to a bucket with retention and, in a production
# deployment, a lock, so the sign-off trail is immutable. The application already redacts before
# it logs; the lock makes the record tamper-evident and un-deletable for the retention window.
# This is the infra half of rule R2.
#
# ############################################################################ #
# # WARNING: LOCKING IS IRREVERSIBLE.                                         # #
# # worm_locked = true permanently prevents reducing retention or deleting    # #
# # this bucket for the full retention window. You CANNOT undo it, not even   # #
# # with project-owner rights, and `terraform destroy` will NOT remove it.    # #
# # The variable has NO DEFAULT: every plan names it. Confirm retention_days  # #
# # before the first apply. A reference or evaluation stack sets              # #
# # worm_locked = false and says why (NOT the compliant production posture).  # #
# ############################################################################ #
#
# This was the literals `retention_days = 2555` and `locked = true`, so the first apply of this
# stack anywhere took a seven-year irreversible decision whether or not the deployment had made
# one. An unset value may take a reviewed default; it may never take an irreversible one, so
# the lock is a variable with no default and the ~7-year floor binds only when it is on.
resource "google_logging_project_bucket_config" "signoff" {
  project        = var.project_id
  location       = local.region
  bucket_id      = "review-console-signoff"
  retention_days = var.retention_days # 2557 (~7 years) by default; the floor is conditional on the lock

  # IRREVERSIBLE when true: see the banner above. The variable has no default, so no plan can
  # lock this bucket without the deployment saying so.
  locked = var.worm_locked
}

resource "google_logging_project_sink" "signoff" {
  project     = var.project_id
  name        = "review-console-signoff-sink"
  destination = "logging.googleapis.com/projects/${var.project_id}/locations/${local.region}/buckets/${google_logging_project_bucket_config.signoff.bucket_id}"

  # Only this service's sign-off log stream.
  filter = "logName=\"projects/${var.project_id}/logs/review-console-signoff\""

  unique_writer_identity = true
}
