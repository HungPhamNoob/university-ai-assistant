resource "random_password" "postgres" {
  length  = 32
  special = false
}

resource "random_password" "jwt" {
  length  = 64
  special = false
}

resource "random_password" "gateway" {
  length  = 48
  special = false
}

resource "random_password" "internal" {
  length  = 48
  special = false
}

resource "aws_db_subnet_group" "main" {
  name       = "${local.name_prefix}-db"
  subnet_ids = aws_subnet.private[*].id

  tags = { Name = "${local.name_prefix}-db" }
}

resource "aws_db_instance" "main" {
  identifier = "${local.name_prefix}-postgres"

  engine                     = "postgres"
  engine_version             = "16"
  instance_class             = var.db_instance_class
  allocated_storage          = var.db_allocated_storage
  max_allocated_storage      = var.db_max_allocated_storage
  storage_type               = "gp3"
  storage_encrypted          = true
  db_name                    = var.postgres_db
  username                   = var.postgres_user
  password                   = local.postgres_password
  port                       = 5432
  db_subnet_group_name       = aws_db_subnet_group.main.name
  vpc_security_group_ids     = [aws_security_group.rds.id]
  publicly_accessible        = false
  multi_az                   = false
  backup_retention_period    = 7
  backup_window              = "18:00-19:00"
  maintenance_window         = "sun:19:00-sun:20:00"
  auto_minor_version_upgrade = true
  deletion_protection        = var.db_deletion_protection
  skip_final_snapshot        = var.db_skip_final_snapshot
  final_snapshot_identifier  = var.db_skip_final_snapshot ? null : "${local.name_prefix}-postgres-final"
  copy_tags_to_snapshot      = true

  tags = { Name = "${local.name_prefix}-postgres" }
}

resource "aws_secretsmanager_secret" "app" {
  name                    = "${local.name_prefix}/application"
  description             = "Runtime credentials for UET HR AI ECS tasks"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    POSTGRES_PASSWORD     = local.postgres_password
    POSTGRES_URI          = "postgresql+psycopg://${var.postgres_user}:${local.postgres_password}@${aws_db_instance.main.address}:5432/${var.postgres_db}"
    JWT_SECRET_KEY        = local.jwt_secret_key
    GATEWAY_SHARED_SECRET = local.gateway_shared_secret
    INTERNAL_API_TOKEN    = local.internal_api_token
    API_KEY               = var.llm_api_key
    API_KEY_2             = var.backup_llm_api_key
    QDRANT_API_KEY        = var.qdrant_api_key
    REDIS_URL             = var.redis_url
    TAVILY_API_KEY        = var.tavily_api_key
    LANGSMITH_API_KEY     = var.langsmith_api_key
  })
}

resource "aws_s3_bucket" "rag_uploads" {
  bucket = local.rag_upload_bucket_name
}

resource "aws_s3_bucket_public_access_block" "rag_uploads" {
  bucket = aws_s3_bucket.rag_uploads.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "rag_uploads" {
  bucket = aws_s3_bucket.rag_uploads.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "rag_uploads" {
  bucket = aws_s3_bucket.rag_uploads.id

  versioning_configuration {
    status = "Enabled"
  }
}
