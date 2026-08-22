# Deadline timers (Cloud Tasks) and case-lifecycle events (Pub/Sub), both in-region. These serve
# the case side of the merged console: the queue fires deadline timers back at this same service to
# re-evaluate a case, and the topic carries content-free lifecycle events for downstream verticals.

# A Cloud Tasks queue that fires deadline timers back at the service to re-evaluate a case.
resource "google_cloud_tasks_queue" "deadlines" {
  project  = var.project_id
  name     = "case-engine-deadlines"
  location = local.region

  rate_limits {
    max_dispatches_per_second = 100
    max_concurrent_dispatches = 50
  }
  retry_config {
    max_attempts = 5
  }
}

# The case-lifecycle event topic (open / transition / escalation). Escalation is now in-process in
# the merged console; the topic remains for downstream verticals that react to lifecycle events.
resource "google_pubsub_topic" "lifecycle" {
  project = var.project_id
  name    = "case-engine-lifecycle"

  message_storage_policy {
    allowed_persistence_regions = [local.region]
  }
}
