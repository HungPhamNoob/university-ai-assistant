# Terraform deployment

This stack provisions the AWS architecture described in `docs/aws-deployment.md`:

- dedicated VPC with public ALB subnets and private ECS/RDS subnets;
- one NAT gateway for ECR, Qdrant Cloud, Redis Cloud, LLM, and Tavily access;
- seven ECR repositories and seven ECS Fargate services;
- ECS Service Connect names matching the Docker Compose hostnames;
- PostgreSQL 16 on RDS, Secrets Manager, S3, IAM, and CloudWatch logs;
- managed Redis Cloud for the conversation exact-match cache, injected as the
  secret `REDIS_URL`; no Redis ECS service, container, or image is provisioned;
- an internet-facing ALB that sends `/api/*`, `/auth/*`, and
  `/conversations*` to Kong and all other paths to the frontend.

The default names intentionally match the CI pipelines — `.gitlab-ci.yml` at
the repository root (the pipeline that actually runs; origin is GitLab) and
`.github/workflows/ci-cd.yml` (GitHub Actions equivalent, kept for a GitHub
mirror): `uet-ai-cluster` and
`uet-{agent,identity,rag,booking,conversation,gateway,frontend}`.

## Prerequisites

- Terraform 1.6 or newer and AWS CLI credentials for account `005097885316`.
- Qdrant Cloud, Redis Cloud, LLM provider, and Tavily credentials.
- Permission to create VPC, NAT, ECR, ECS, RDS, ALB, IAM, S3, CloudWatch,
  Cloud Map, and Secrets Manager resources in `ap-southeast-1`.

## First deployment

The ECS services cannot start until their ECR repositories contain images.
Bootstrap the infrastructure with task counts set to zero, push images, then
scale the services to their normal counts:

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Fill in the non-AWS provider credentials in terraform.tfvars.
# On a clean account, uncomment the zero-count service_desired_counts map.
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

Push to `main` after the repositories exist so CI can publish the seven
`latest` images. Then remove the zero-count override and run:

```bash
terraform plan -out=tfplan
terraform apply tfplan
```

The public URL is printed as the `alb_url` output.

## Notes

- `terraform.tfvars`, state files, and plans are ignored. State still contains
  sensitive values, so use an encrypted remote backend before team use.
- RDS deletion protection is enabled by default. Set
  `db_deletion_protection = false` deliberately before destroying the stack.
- The NAT gateway is the main fixed networking cost. It is required because
  ECS tasks are private and call external APIs.
- The S3 bucket and task role are ready for document storage, although the
  current RAG implementation still reads documents directly into Qdrant.
