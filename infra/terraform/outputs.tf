output "service_url" {
  description = "The Cloud Run URL of the review console."
  value       = google_cloud_run_v2_service.review.uri
}

output "runtime_service_account" {
  description = "The least-privilege runtime service account email."
  value       = google_service_account.runtime.email
}

output "cmek_key" {
  description = "The regional CMEK key protecting the store, logs, and revision."
  value       = google_kms_crypto_key.review.id
}

output "signoff_log_bucket" {
  description = "The WORM bucket holding the sign-off trail (locked when worm_locked = true)."
  value       = google_logging_project_bucket_config.signoff.bucket_id
}

output "worm_locked" {
  description = "Whether the sign-off bucket is irreversibly locked for the retention window. true is the compliant production posture."
  value       = var.worm_locked
}

output "deadlines_queue" {
  description = "The Cloud Tasks queue firing case deadline timers."
  value       = google_cloud_tasks_queue.deadlines.id
}

output "lifecycle_topic" {
  description = "The Pub/Sub topic carrying case-lifecycle events."
  value       = google_pubsub_topic.lifecycle.id
}

output "tasks_invoker_service_account" {
  description = "The SA Cloud Tasks uses (OIDC) to call back the deadline-evaluate endpoint."
  value       = google_service_account.tasks_invoker.email
}
