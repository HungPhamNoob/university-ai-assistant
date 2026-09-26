data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  cluster_name = "${var.project_name}-ai-cluster"
  name_prefix  = "${var.project_name}-ai"

  common_tags = merge(
    {
      Project     = "UET HR AI"
      Environment = var.environment
      ManagedBy   = "Terraform"
    },
    var.tags,
  )

  services = {
    agent = {
      port   = 8000
      cpu    = 512
      memory = 1024
      tier   = "backend"
    }
    identity = {
      port   = 8001
      cpu    = 512
      memory = 1024
      tier   = "backend"
    }
    rag = {
      port   = 8002
      cpu    = 1024
      memory = 4096
      tier   = "backend"
    }
    booking = {
      port   = 8003
      cpu    = 512
      memory = 1024
      tier   = "backend"
    }
    conversation = {
      port   = 8004
      cpu    = 512
      memory = 1024
      tier   = "backend"
    }
    gateway = {
      port   = 8000
      cpu    = 512
      memory = 1024
      tier   = "gateway"
    }
    frontend = {
      port   = 3000
      cpu    = 256
      memory = 512
      tier   = "frontend"
    }
  }

  postgres_password      = coalesce(var.postgres_password, random_password.postgres.result)
  jwt_secret_key         = coalesce(var.jwt_secret_key, random_password.jwt.result)
  gateway_shared_secret  = coalesce(var.gateway_shared_secret, random_password.gateway.result)
  internal_api_token     = coalesce(var.internal_api_token, random_password.internal.result)
  rag_upload_bucket_name = coalesce(var.rag_upload_bucket_name, "${var.project_name}-hr-rag-uploads-${data.aws_caller_identity.current.account_id}-${var.aws_region}")

  common_database_environment = {
    POSTGRES_HOST = aws_db_instance.main.address
    POSTGRES_PORT = tostring(aws_db_instance.main.port)
    POSTGRES_USER = var.postgres_user
    POSTGRES_DB   = var.postgres_db
  }

  common_llm_environment = {
    LLM_MODEL = var.llm_model
    BASE_URL  = var.llm_base_url
  }

  service_environment = {
    agent = merge(local.common_llm_environment, {
      API_KEY_2_BASE_URL        = var.backup_llm_base_url
      API_KEY_2_MODEL           = var.backup_llm_model
      AGENT_REQUIRE_GATEWAY     = "true"
      RAG_SERVICE_URL           = "http://rag:8002"
      BOOKING_SERVICE_URL       = "http://booking:8003"
      CONVERSATION_SERVICE_URL  = "http://conversation:8004"
      LANGSMITH_TRACING         = tostring(var.langsmith_tracing)
      LANGSMITH_ENDPOINT        = "https://api.smith.langchain.com"
      LANGSMITH_PROJECT         = var.langsmith_project
      TOKEN_BUDGET_SYSTEM       = "2048"
      TOKEN_BUDGET_HISTORY      = "3000"
      TOKEN_BUDGET_DOCS         = "20000"
      TOKEN_BUDGET_TOOL_OUTPUTS = "5000"
      TOKEN_BUDGET_RESERVE      = "4096"
      CONTEXT_LIMIT             = "32768"
    })
    identity = merge(local.common_database_environment, {
      JWT_ALGORITHM      = "HS256"
      JWT_EXPIRE_MINUTES = "60"
      JWT_ISSUER         = "uet-identity"
    })
    rag = merge(local.common_llm_environment, {
      QDRANT_URL                 = var.qdrant_url
      QDRANT_KB_COLLECTION       = "uet_hr_docs"
      QDRANT_CACHE_COLLECTION    = "uet_hr_cache"
      VECTOR_SIZE                = "384"
      EMBEDDING_MODEL_NAME       = "all-MiniLM-L6-v2"
      RERANKER_MODEL_NAME        = "cross-encoder/ms-marco-MiniLM-L-6-v2"
      CHUNK_SIMILARITY_THRESHOLD = "0.75"
      HYDE_ENABLED               = "true"
      HYDE_SCORE_THRESHOLD       = "0.65"
      HYDE_LLM_MODEL             = "LLM_MODEL"
      CACHE_TTL_SECONDS          = "3600"
      CACHE_SIMILARITY_THRESHOLD = "0.95"
      LANGSMITH_TRACING          = tostring(var.langsmith_tracing)
      LANGSMITH_PROJECT          = var.langsmith_project
    })
    booking = local.common_database_environment
    conversation = merge(local.common_database_environment, local.common_llm_environment, {
      REDIS_ENABLED                  = "true"
      REDIS_TTL_SECONDS              = "300"
      EPISODIC_ENABLED               = "true"
      EPISODIC_MESSAGE_THRESHOLD     = "20"
      EPISODIC_SUMMARIZATION_VERSION = "1"
      EPISODIC_LLM_TIMEOUT_SECONDS   = "30"
      EPISODIC_MAX_PROMPT_CHARS      = "16000"
    })
    gateway = {
      KONG_DATABASE = "off"
    }
    frontend = {
      FRONTEND_API_BASE_URL = ""
    }
  }

  service_secret_keys = {
    agent = [
      "POSTGRES_URI",
      "API_KEY",
      "API_KEY_2",
      "GATEWAY_SHARED_SECRET",
      "INTERNAL_API_TOKEN",
      "TAVILY_API_KEY",
      "LANGSMITH_API_KEY",
    ]
    identity = ["POSTGRES_PASSWORD", "JWT_SECRET_KEY", "GATEWAY_SHARED_SECRET"]
    rag      = ["QDRANT_API_KEY", "API_KEY", "LANGSMITH_API_KEY"]
    booking  = ["POSTGRES_PASSWORD", "INTERNAL_API_TOKEN", "GATEWAY_SHARED_SECRET"]
    conversation = [
      "POSTGRES_PASSWORD",
      "INTERNAL_API_TOKEN",
      "GATEWAY_SHARED_SECRET",
      "API_KEY",
      "REDIS_URL",
    ]
    gateway  = ["JWT_SECRET_KEY", "GATEWAY_SHARED_SECRET"]
    frontend = []
  }
}
