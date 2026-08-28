variable "project_id" {
  description = "Google Cloud project that hosts the application plane."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run, Artifact Registry and Vertex AI."
  type        = string
  default     = "us-central1"
}

variable "image_tag" {
  description = "Tag of the All-Access image in Artifact Registry."
  type        = string
  default     = "latest"
}

variable "enable_gemini" {
  description = <<-EOT
    Route narration through Gemini on Vertex AI instead of the offline plane.

    Off by default. The offline plane is what every committed benchmark figure
    was produced with, so leaving this false gives a deployment whose behaviour
    matches the published evidence. Turning it on grants the service account
    roles/aiplatform.user and enables the Vertex API.
  EOT
  type        = bool
  default     = false
}

variable "enable_confluent" {
  description = <<-EOT
    Publish through Confluent Cloud instead of the in-process bus.

    Off by default. When true, the six credential secrets are created empty and
    bound to the service; add their versions with `gcloud secrets versions add`
    rather than through Terraform, so no credential enters the state file.
  EOT
  type        = bool
  default     = false
}

variable "allow_unauthenticated" {
  description = <<-EOT
    Grant roles/run.invoker to allUsers.

    True for the hackathon submission, because a judge has to be able to open
    the URL. This is the one setting to change first if the service is ever
    pointed at a real production: the demonstration data is authored and
    fictional, and nothing here is a permission to publish real crew data.
  EOT
  type        = bool
  default     = true
}

variable "min_instances" {
  description = <<-EOT
    Minimum Cloud Run instances.

    1 keeps a warm instance so a judge opening the URL does not meet a cold
    start on the first solve; 0 is cheaper and is the right default outside a
    judging window.
  EOT
  type        = number
  default     = 1
}

variable "max_instances" {
  description = "Maximum Cloud Run instances."
  type        = number
  default     = 4
}
