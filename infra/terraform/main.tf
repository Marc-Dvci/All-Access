/**
 * All-Access — application plane on Google Cloud.
 *
 * What this provisions: an Artifact Registry repository, a Cloud Run service
 * running the container from Dockerfile, a dedicated service account with the
 * narrowest role set the application actually uses, and Secret Manager entries
 * for the Confluent and Vertex credentials.
 *
 * What it deliberately does not provision: the Confluent Cloud cluster, the
 * Schema Registry and the Agent Engine deployment. Those are created by their
 * own tooling (`tools/deploy_agent_engine.py` for the last one) and referenced
 * here by identifier. Terraform that claims to own a resource it cannot
 * reconcile produces a state file that lies.
 *
 * The service runs with **no secrets bound by default**. `var.enable_confluent`
 * and `var.enable_gemini` are false, and with both off the deployed service is
 * the fully offline plane: the in-process bus, the offline reasoning plane, and
 * the same closed loop the benchmark measured. That is the demonstrable
 * default, and turning either on is an explicit decision recorded in a plan
 * diff.
 */

terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

locals {
  service_name = "allaccess"

  # Enabled only for what is used at runtime. Artifact Registry and Cloud Run
  # are always needed; the other two follow the feature flags.
  required_services = toset(concat(
    [
      "run.googleapis.com",
      "artifactregistry.googleapis.com",
      "secretmanager.googleapis.com",
    ],
    var.enable_gemini ? ["aiplatform.googleapis.com"] : [],
  ))

  image = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}/${local.service_name}:${var.image_tag}"
}

resource "google_project_service" "required" {
  for_each = local.required_services

  service = each.value

  # Leave the APIs enabled on destroy. Disabling a project-level API because one
  # service was torn down is how an unrelated workload goes down with it.
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "images" {
  location      = var.region
  repository_id = "${local.service_name}-images"
  description   = "Container images for the All-Access application plane"
  format        = "DOCKER"

  depends_on = [google_project_service.required]
}

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

resource "google_service_account" "app" {
  account_id   = "${local.service_name}-app"
  display_name = "All-Access application plane"
  description  = "Runs the Cloud Run service. Reads its own secrets; nothing else."
}

# Vertex AI, only when the Gemini reasoning plane is switched on. `aiplatform.user`
# is the narrowest role that permits `generateContent`; the service never trains,
# tunes or deploys a model, so nothing broader is granted.
resource "google_project_iam_member" "vertex_user" {
  count = var.enable_gemini ? 1 : 0

  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.app.email}"
}

# Secret access is granted per secret, not at project level, so the service
# account cannot read a secret that is added later for something else.
resource "google_secret_manager_secret_iam_member" "app_access" {
  for_each = google_secret_manager_secret.runtime

  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app.email}"
}

# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------
#
# Terraform creates the secret containers and never the versions. Writing a
# credential into a variable puts it in the state file and in the plan output,
# and both get shared. Populate with:
#
#   printf %s "$KEY" | gcloud secrets versions add allaccess-confluent-api-key --data-file=-

resource "google_secret_manager_secret" "runtime" {
  for_each = toset(var.enable_confluent ? [
    "confluent-bootstrap",
    "confluent-api-key",
    "confluent-api-secret",
    "schema-registry-url",
    "schema-registry-key",
    "schema-registry-secret",
  ] : [])

  secret_id = "${local.service_name}-${each.value}"

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

# ---------------------------------------------------------------------------
# The service
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "app" {
  name     = local.service_name
  location = var.region

  # The demo is public and read-mostly; disruption intake is a POST but changes
  # only in-process demonstration state. If this is ever pointed at a real
  # production, put it behind IAP and set this to INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER.
  ingress = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.app.email

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = local.image

      resources {
        limits = {
          # The solver is CPU-bound and single-threaded per request; the
          # benchmark's p95 end-to-end is under a second at one core.
          cpu    = "1"
          memory = "1Gi"
        }
        cpu_idle = var.min_instances == 0
      }

      env {
        name  = "AA_REASONING_MODE"
        value = var.enable_gemini ? "gemini" : "offline"
      }

      env {
        name  = "AA_EVENT_BACKBONE"
        value = var.enable_confluent ? "confluent" : "local"
      }

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }

      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = var.region
      }

      dynamic "env" {
        for_each = google_secret_manager_secret.runtime

        content {
          # confluent-api-key -> AA_CONFLUENT_API_KEY
          name = "AA_${upper(replace(env.key, "-", "_"))}"

          value_source {
            secret_key_ref {
              secret  = env.value.secret_id
              version = "latest"
            }
          }
        }
      }

      startup_probe {
        http_get {
          path = "/healthz"
        }
        initial_delay_seconds = 5
        period_seconds        = 5
        failure_threshold     = 12
      }

      liveness_probe {
        http_get {
          path = "/healthz"
        }
        period_seconds = 30
      }
    }
  }

  depends_on = [
    google_project_service.required,
    google_secret_manager_secret_iam_member.app_access,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  count = var.allow_unauthenticated ? 1 : 0

  location = google_cloud_run_v2_service.app.location
  name     = google_cloud_run_v2_service.app.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
