variable "aws_region" {
  description = "AWS region used by the application stack."
  type        = string
  default     = "ap-southeast-1"
}

variable "project_name" {
  description = "Stable resource-name prefix. Keep the default to match the CI workflow."
  type        = string
  default     = "uet"
}

variable "environment" {
  description = "Deployment environment tag."
  type        = string
  default     = "production"
}

variable "vpc_cidr" {
  description = "CIDR range for the application VPC."
  type        = string
  default     = "10.20.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "Two public subnet CIDRs for the ALB and NAT gateway."
  type        = list(string)
  default     = ["10.20.0.0/24", "10.20.1.0/24"]

  validation {
    condition     = length(var.public_subnet_cidrs) == 2
    error_message = "Exactly two public subnet CIDRs are required."
  }
}

variable "private_subnet_cidrs" {
  description = "Two private subnet CIDRs for ECS and RDS."
  type        = list(string)
  default     = ["10.20.10.0/24", "10.20.11.0/24"]

  validation {
    condition     = length(var.private_subnet_cidrs) == 2
    error_message = "Exactly two private subnet CIDRs are required."
  }
}

variable "image_tag" {
  description = "ECR image tag deployed by all ECS services."
  type        = string
  default     = "latest"
}

variable "service_desired_counts" {
  description = "Desired ECS task count per service. Set all values to 0 for an infrastructure-only bootstrap."
  type        = map(number)
  default = {
    agent        = 1
    identity     = 1
    rag          = 1
    booking      = 1
    conversation = 1
    gateway      = 1
    frontend     = 1
  }
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t3.micro"
}

variable "db_allocated_storage" {
  description = "Initial RDS gp3 storage in GiB."
  type        = number
  default     = 20
}

variable "db_max_allocated_storage" {
  description = "RDS storage autoscaling limit in GiB."
  type        = number
  default     = 100
}

variable "db_deletion_protection" {
  description = "Protect the production database from accidental deletion."
  type        = bool
  default     = true
}

variable "db_skip_final_snapshot" {
  description = "Skip the final RDS snapshot when deletion protection is disabled and the DB is destroyed."
  type        = bool
  default     = false
}

variable "postgres_user" {
  description = "RDS master username."
  type        = string
  default     = "uetadmin"
}

variable "postgres_db" {
  description = "Application database name."
  type        = string
  default     = "uet_ai_db"
}

variable "postgres_password" {
  description = "Optional RDS password. A random password is generated when null."
  type        = string
  sensitive   = true
  default     = null
  nullable    = true
}

variable "jwt_secret_key" {
  description = "Optional JWT signing key. A random value is generated when null."
  type        = string
  sensitive   = true
  default     = null
  nullable    = true
}

variable "gateway_shared_secret" {
  description = "Optional gateway-to-service secret. A random value is generated when null."
  type        = string
  sensitive   = true
  default     = null
  nullable    = true
}

variable "internal_api_token" {
  description = "Optional service-to-service token. A random value is generated when null."
  type        = string
  sensitive   = true
  default     = null
  nullable    = true
}

variable "llm_model" {
  description = "Primary OpenAI-compatible model name."
  type        = string
}

variable "llm_api_key" {
  description = "Primary LLM provider API key."
  type        = string
  sensitive   = true
}

variable "llm_base_url" {
  description = "Primary OpenAI-compatible API base URL."
  type        = string
}

variable "backup_llm_api_key" {
  description = "Optional backup LLM API key."
  type        = string
  sensitive   = true
  default     = ""
}

variable "backup_llm_base_url" {
  description = "Backup OpenAI-compatible API base URL."
  type        = string
  default     = "https://api.openai.com/v1"
}

variable "backup_llm_model" {
  description = "Backup model name."
  type        = string
  default     = "gpt-5-nano"
}

variable "qdrant_url" {
  description = "Qdrant Cloud cluster URL."
  type        = string
}

variable "qdrant_api_key" {
  description = "Qdrant Cloud API key."
  type        = string
  sensitive   = true
}

variable "redis_url" {
  description = "Credential-bearing Redis Cloud URL used by the conversation cache."
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^rediss?://", var.redis_url))
    error_message = "redis_url must start with redis:// or rediss://."
  }
}

variable "tavily_api_key" {
  description = "Tavily API key used by the search agent."
  type        = string
  sensitive   = true
}

variable "langsmith_tracing" {
  description = "Enable LangSmith tracing."
  type        = bool
  default     = false
}

variable "langsmith_api_key" {
  description = "Optional LangSmith API key."
  type        = string
  sensitive   = true
  default     = ""
}

variable "langsmith_project" {
  description = "LangSmith project name."
  type        = string
  default     = "uet-hr-ai"
}

variable "rag_upload_bucket_name" {
  description = "Optional globally unique S3 bucket name. A deterministic account/region name is used when null."
  type        = string
  default     = null
  nullable    = true
}

variable "tags" {
  description = "Additional tags applied to all resources."
  type        = map(string)
  default     = {}
}
