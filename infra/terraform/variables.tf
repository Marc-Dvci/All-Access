variable "project_id" {
  description = "Google Cloud project that hosts the application plane."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run and Artifact Registry."
  type        = string
  default     = "us-central1"
}

variable "gemini_location" {
  description = <<-EOT
    Vertex AI location for Gemini calls. Gemini 3.x models on Vertex AI
    require the global endpoint; regional endpoints resolve to 404.
  EOT
  type        = string
  default     = "global"
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


variable "auth_mode" {
  description = <<-EOT
    How the web application establishes who is signing.

      demo    the production directory, with per-person access codes published
              on the sign-in screen. The public demonstration runs this: the
              codes are not the control, the server-side role binding is.
      closed  the same directory, with codes supplied in AA_ACCESS_CODES and
              published nowhere.
      iap     no code sign-in at all. The subject comes from the Identity-Aware
              Proxy assertion and the authority comes from the directory, which
              is what a real production deployment runs.
  EOT

  type    = string
  default = "demo"

  validation {
    condition     = contains(["demo", "closed", "iap"], var.auth_mode)
    error_message = "auth_mode must be demo, closed or iap."
  }
}
