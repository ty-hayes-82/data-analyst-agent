# Terraform Configuration for Data Analyst Agent GCP Infrastructure
# Provisions all required GCP resources for Vertex AI Agent Engine deployment

terraform {
  required_version = ">= 1.5.0"
  
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 5.0"
    }
  }
  
  backend "gcs" {
    bucket = "REPLACE_WITH_YOUR_TERRAFORM_STATE_BUCKET"
    prefix = "data-analyst-agent/state"
  }
}

# ============================================================================
# Variables
# ============================================================================

variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP Region"
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "Environment (dev, staging, prod)"
  type        = string
  default     = "prod"
}

# ============================================================================
# Provider Configuration
# ============================================================================

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

# ============================================================================
# Enable Required APIs
# ============================================================================

resource "google_project_service" "required_apis" {
  for_each = toset([
    "aiplatform.googleapis.com",        # Vertex AI
    "storage.googleapis.com",           # Cloud Storage
    "secretmanager.googleapis.com",     # Secret Manager
    "logging.googleapis.com",           # Cloud Logging
    "monitoring.googleapis.com",        # Cloud Monitoring
    "cloudtrace.googleapis.com",        # Cloud Trace
    "cloudbuild.googleapis.com",        # Cloud Build
    "run.googleapis.com",               # Cloud Run (for web UI)
    "artifactregistry.googleapis.com",  # Artifact Registry
  ])
  
  service            = each.key
  disable_on_destroy = false
}

# ============================================================================
# Cloud Storage Buckets
# ============================================================================

# Datasets bucket (contracts, validation data)
resource "google_storage_bucket" "datasets" {
  name          = "${var.project_id}-data-analyst-datasets"
  location      = var.region
  storage_class = "STANDARD"
  
  uniform_bucket_level_access = true
  
  versioning {
    enabled = true
  }
  
  lifecycle_rule {
    condition {
      num_newer_versions = 3
    }
    action {
      type = "Delete"
    }
  }
  
  labels = {
    environment = var.environment
    component   = "datasets"
  }
}

# Outputs bucket (analysis results, PDFs)
resource "google_storage_bucket" "outputs" {
  name          = "${var.project_id}-data-analyst-outputs"
  location      = var.region
  storage_class = "STANDARD"
  
  uniform_bucket_level_access = true
  
  lifecycle_rule {
    condition {
      age = 90  # Delete outputs older than 90 days
    }
    action {
      type = "Delete"
    }
  }
  
  labels = {
    environment = var.environment
    component   = "outputs"
  }
}

# ============================================================================
# Service Account for Agent
# ============================================================================

resource "google_service_account" "data_analyst_agent" {
  account_id   = "data-analyst-agent"
  display_name = "Data Analyst Agent Service Account"
  description  = "Service account for Vertex AI Agent Engine deployment"
}

# IAM Roles for Service Account
resource "google_project_iam_member" "agent_roles" {
  for_each = toset([
    "roles/aiplatform.user",           # Vertex AI access
    "roles/storage.objectAdmin",       # Cloud Storage read/write
    "roles/secretmanager.secretAccessor", # Secret Manager access
    "roles/logging.logWriter",         # Cloud Logging
    "roles/monitoring.metricWriter",   # Cloud Monitoring
    "roles/cloudtrace.agent",          # Cloud Trace
  ])
  
  project = var.project_id
  role    = each.key
  member  = "serviceAccount:${google_service_account.data_analyst_agent.email}"
}

# Grant bucket access
resource "google_storage_bucket_iam_member" "datasets_reader" {
  bucket = google_storage_bucket.datasets.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.data_analyst_agent.email}"
}

resource "google_storage_bucket_iam_member" "outputs_admin" {
  bucket = google_storage_bucket.outputs.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.data_analyst_agent.email}"
}

# ============================================================================
# Secret Manager Secrets
# ============================================================================

# Google API Key
resource "google_secret_manager_secret" "google_api_key" {
  secret_id = "google-api-key"
  
  replication {
    auto {}
  }
  
  labels = {
    environment = var.environment
    component   = "credentials"
  }
}

resource "google_secret_manager_secret_iam_member" "api_key_accessor" {
  secret_id = google_secret_manager_secret.google_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.data_analyst_agent.email}"
}

# Service Account JSON (for external APIs if needed)
resource "google_secret_manager_secret" "service_account_json" {
  secret_id = "service-account-json"
  
  replication {
    auto {}
  }
  
  labels = {
    environment = var.environment
    component   = "credentials"
  }
}

resource "google_secret_manager_secret_iam_member" "sa_json_accessor" {
  secret_id = google_secret_manager_secret.service_account_json.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.data_analyst_agent.email}"
}

# ============================================================================
# Artifact Registry for Container Images
# ============================================================================

resource "google_artifact_registry_repository" "containers" {
  location      = var.region
  repository_id = "data-analyst-agent"
  description   = "Container images for Data Analyst Agent"
  format        = "DOCKER"
  
  labels = {
    environment = var.environment
  }
}

# ============================================================================
# Cloud Run Service (Web UI)
# ============================================================================

resource "google_cloud_run_service" "web_ui" {
  name     = "data-analyst-ui"
  location = var.region
  
  template {
    spec {
      service_account_name = google_service_account.data_analyst_agent.email
      
      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/data-analyst-agent/web-ui:latest"
        
        ports {
          container_port = 8080
        }
        
        resources {
          limits = {
            cpu    = "2"
            memory = "4Gi"
          }
        }
        
        env {
          name  = "GOOGLE_CLOUD_PROJECT"
          value = var.project_id
        }
        
        env {
          name  = "GOOGLE_CLOUD_LOCATION"
          value = var.region
        }
        
        env {
          name = "GOOGLE_API_KEY"
          value_from {
            secret_key_ref {
              name = google_secret_manager_secret.google_api_key.secret_id
              key  = "latest"
            }
          }
        }
      }
    }
    
    metadata {
      annotations = {
        "autoscaling.knative.dev/maxScale" = "10"
        "autoscaling.knative.dev/minScale" = "0"
      }
    }
  }
  
  traffic {
    percent         = 100
    latest_revision = true
  }
}

# Allow public access to web UI
resource "google_cloud_run_service_iam_member" "web_ui_public" {
  service  = google_cloud_run_service.web_ui.name
  location = google_cloud_run_service.web_ui.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ============================================================================
# Cloud Monitoring — Alert Policies
# ============================================================================

resource "google_monitoring_notification_channel" "email" {
  display_name = "Email Notifications"
  type         = "email"
  
  labels = {
    email_address = "ty-hayes-82@example.com"  # REPLACE
  }
}

resource "google_monitoring_alert_policy" "high_error_rate" {
  display_name = "Data Analyst Agent - High Error Rate"
  combiner     = "OR"
  
  conditions {
    display_name = "Error rate > 10%"
    
    condition_threshold {
      filter          = "resource.type=\"cloud_run_revision\" AND metric.type=\"run.googleapis.com/request_count\" AND metric.label.response_code_class=\"5xx\""
      duration        = "300s"
      comparison      = "COMPARISON_GT"
      threshold_value = 0.1
      
      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_RATE"
      }
    }
  }
  
  notification_channels = [google_monitoring_notification_channel.email.id]
  
  documentation {
    content = "Data Analyst Agent error rate exceeded 10%. Check Cloud Logging for details."
  }
}

# ============================================================================
# Outputs
# ============================================================================

output "datasets_bucket" {
  description = "GCS bucket for datasets"
  value       = google_storage_bucket.datasets.name
}

output "outputs_bucket" {
  description = "GCS bucket for analysis outputs"
  value       = google_storage_bucket.outputs.name
}

output "service_account_email" {
  description = "Service account email for agent"
  value       = google_service_account.data_analyst_agent.email
}

output "web_ui_url" {
  description = "Cloud Run URL for web UI"
  value       = google_cloud_run_service.web_ui.status[0].url
}

output "artifact_registry" {
  description = "Artifact Registry repository"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.containers.repository_id}"
}
