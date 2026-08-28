output "service_url" {
  description = "Public URL of the All-Access application plane."
  value       = google_cloud_run_v2_service.app.uri
}

output "service_account_email" {
  description = "Identity the service runs as."
  value       = google_service_account.app.email
}

output "image_repository" {
  description = "Artifact Registry path to push the image to."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "runtime_plane" {
  description = "Which planes this deployment is wired to, as deployed."
  value = {
    reasoning       = var.enable_gemini ? "gemini (Vertex AI)" : "offline"
    event_backbone  = var.enable_confluent ? "confluent cloud" : "in-process bus"
    public          = var.allow_unauthenticated
  }
}

output "secrets_to_populate" {
  description = <<-EOT
    Secrets created empty by Terraform. Add a version to each before the service
    will start with enable_confluent = true.
  EOT
  value       = [for s in google_secret_manager_secret.runtime : s.secret_id]
}
