# The console service. Internal + load-balancer ingress only (no open internet), CMEK-encrypted
# revision, runs as the least-privilege runtime SA, and opts IN to the gcp profile explicitly.
resource "google_cloud_run_v2_service" "review" {
  provider = google-beta
  project  = var.project_id
  name     = local.service_name
  location = local.region
  ingress  = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  template {
    service_account                  = google_service_account.runtime.email
    encryption_key                   = google_kms_crypto_key.review.id
    max_instance_request_concurrency = 40

    scaling {
      min_instance_count = 1
      max_instance_count = 4
    }

    containers {
      image = var.container_image
      ports {
        container_port = 8087
      }

      env {
        name  = "REVIEW_PROFILE"
        value = "gcp"
      }
      env {
        name  = "REVIEW_FRAME_ANCESTORS"
        value = var.frame_ancestors
      }
      env {
        name  = "REVIEW_IAP_AUDIENCE"
        value = var.iap_audience
      }
      env {
        name  = "REVIEW_IAP_ENTITLEMENTS_JSON"
        value = var.iap_entitlements_json
      }
      env {
        name  = "PORT"
        value = "8087"
      }

      # Case side: Cloud Tasks deadline timers + Pub/Sub lifecycle events. The queue/topic are the
      # short resource names (the adapters build the full path from project + region); the callback
      # URL is where deadline tasks POST /v1/cases/{id}/evaluate, authenticated as the invoker SA.
      env {
        name  = "REVIEW_GCP_PROJECT"
        value = var.project_id
      }
      env {
        name  = "REVIEW_TASKS_QUEUE"
        value = google_cloud_tasks_queue.deadlines.name
      }
      env {
        name  = "REVIEW_EVENTS_TOPIC"
        value = google_pubsub_topic.lifecycle.name
      }
      env {
        name  = "REVIEW_TIMER_CALLBACK_URL"
        value = var.timer_callback_url
      }
      env {
        name  = "REVIEW_TASKS_INVOKER_SA"
        value = google_service_account.tasks_invoker.email
      }

      startup_probe {
        http_get {
          path = "/healthz"
        }
      }
      liveness_probe {
        http_get {
          path = "/healthz"
        }
      }
    }
  }

  depends_on = [
    google_project_service.required,
    google_kms_crypto_key_iam_member.run,
  ]
}
