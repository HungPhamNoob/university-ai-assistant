resource "aws_cloudwatch_log_group" "service" {
  for_each = local.services

  name              = "/ecs/${var.project_name}-${each.key}"
  retention_in_days = 30
}

resource "aws_ecs_cluster" "main" {
  name = local.cluster_name

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  service_connect_defaults {
    namespace = aws_service_discovery_private_dns_namespace.main.arn
  }
}

resource "aws_ecs_task_definition" "service" {
  for_each = local.services

  family                   = "${var.project_name}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(each.value.cpu)
  memory                   = tostring(each.value.memory)
  execution_role_arn       = aws_iam_role.ecs_execution.arn
  task_role_arn            = each.key == "rag" ? aws_iam_role.rag_task.arn : aws_iam_role.ecs_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = each.key
      image     = "${aws_ecr_repository.service[each.key].repository_url}:${var.image_tag}"
      essential = true

      portMappings = [
        {
          name          = each.key
          containerPort = each.value.port
          hostPort      = each.value.port
          protocol      = "tcp"
          appProtocol   = "http"
        }
      ]

      environment = [
        for name, value in local.service_environment[each.key] : {
          name  = name
          value = value
        }
      ]

      secrets = [
        for name in local.service_secret_keys[each.key] : {
          name      = name
          valueFrom = "${aws_secretsmanager_secret.app.arn}:${name}::"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.service[each.key].name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = each.key
        }
      }

      healthCheck = each.key == "gateway" ? {
        command     = ["CMD-SHELL", "kong health || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 30
        } : each.key == "frontend" ? {
        command     = ["CMD-SHELL", "wget -q -O /dev/null http://127.0.0.1:3000/ || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 15
        } : {
        command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:${each.value.port}/health').read()\" || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = each.key == "rag" ? 120 : 30
      }
    }
  ])

  depends_on = [
    aws_iam_role_policy_attachment.ecs_execution,
    aws_iam_role_policy.ecs_execution_secrets,
    aws_secretsmanager_secret_version.app,
  ]
}

resource "aws_ecs_service" "service" {
  for_each = local.services

  name            = "${var.project_name}-${each.key}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.service[each.key].arn
  desired_count   = lookup(var.service_desired_counts, each.key, 1)
  launch_type     = "FARGATE"

  enable_execute_command            = true
  health_check_grace_period_seconds = contains(["frontend", "gateway"], each.key) ? 120 : 0
  wait_for_steady_state             = false

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = aws_subnet.private[*].id
    assign_public_ip = false
    security_groups = [
      each.value.tier == "frontend" ? aws_security_group.frontend.id :
      each.value.tier == "gateway" ? aws_security_group.gateway.id :
      aws_security_group.backend.id
    ]
  }

  service_connect_configuration {
    enabled   = true
    namespace = aws_service_discovery_private_dns_namespace.main.arn

    service {
      port_name      = each.key
      discovery_name = each.key

      client_alias {
        dns_name = each.key
        port     = each.value.port
      }

      # Service Connect (Envoy sidecar) mặc định cắt request sau 15s chờ
      # "complete response" — giết SSE stream dài và RAG HyDE (hợp lệ tới
      # 150s). per_request 300s phủ worst-case; idle giữ default 5 phút
      # (agent gửi heartbeat SSE mỗi 15s nên không bao giờ chạm).
      timeout {
        per_request_timeout_seconds = 300
      }
    }
  }

  dynamic "load_balancer" {
    for_each = each.key == "frontend" ? [aws_lb_target_group.frontend.arn] : each.key == "gateway" ? [aws_lb_target_group.gateway.arn] : []
    content {
      target_group_arn = load_balancer.value
      container_name   = each.key
      container_port   = each.value.port
    }
  }

  depends_on = [aws_lb_listener.http, aws_lb_listener_rule.gateway]
}
