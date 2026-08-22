# A dedicated least-privilege runtime service account (Workload Identity, no exported keys).
resource "google_service_account" "runtime" {
  project      = var.project_id
  account_id   = "review-console-run"
  display_name = "Hrz7 Human-Review Console runtime"
}

# Scoped to exactly what the console needs: read/write its Firestore data, enqueue Cloud Tasks for
# case deadline timers, publish case-lifecycle Pub/Sub events, write audit logs, and mint ID tokens
# for outbound S2S calls to sibling Hrz services.
resource "google_project_iam_member" "datastore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "tasks_enqueuer" {
  project = var.project_id
  role    = "roles/cloudtasks.enqueuer"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "pubsub_publisher" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "token_creator" {
  project = var.project_id
  role    = "roles/iam.serviceAccountTokenCreator"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

# Cloud Tasks OIDC identity: deadline timers call back POST /v1/cases/{id}/evaluate on this same
# internal-only service. Cloud Tasks mints an OIDC token as this dedicated invoker SA, which is the
# only identity granted run.invoker on the service. The runtime SA is granted actAs on it so it can
# stamp this identity onto the tasks it enqueues (REVIEW_TASKS_INVOKER_SA).
resource "google_service_account" "tasks_invoker" {
  project      = var.project_id
  account_id   = "review-tasks-invoker"
  display_name = "Hrz7 console Cloud Tasks deadline-callback invoker"
}

resource "google_cloud_run_v2_service_iam_member" "tasks_invoker" {
  project  = var.project_id
  location = local.region
  name     = google_cloud_run_v2_service.review.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.tasks_invoker.email}"
}

resource "google_service_account_iam_member" "runtime_acts_as_invoker" {
  service_account_id = google_service_account.tasks_invoker.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.runtime.email}"
}
