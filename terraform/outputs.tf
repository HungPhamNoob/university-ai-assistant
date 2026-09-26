output "alb_url" {
  description = "Public application URL."
  value       = "http://${aws_lb.main.dns_name}"
}

output "ecr_registry" {
  description = "ECR registry used by the CI workflow."
  value       = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
}

output "ecr_repository_urls" {
  description = "Repository URL for each service image."
  value       = { for name, repository in aws_ecr_repository.service : name => repository.repository_url }
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "rds_endpoint" {
  value = aws_db_instance.main.address
}

output "application_secret_arn" {
  description = "Secrets Manager ARN consumed by ECS task definitions."
  value       = aws_secretsmanager_secret.app.arn
}

output "rag_upload_bucket" {
  value = aws_s3_bucket.rag_uploads.id
}

