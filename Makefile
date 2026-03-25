.PHONY: help infra day1 day2 all down logs ps clean

COMPOSE  = docker compose -f docker-compose.day1.yml
ENV_FILE = .env

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------
infra: ## Start infrastructure only (postgres, neo4j, redis, kafka, temporal, minio, otel)
	$(COMPOSE) --profile infra up -d
	@echo "⏳ Waiting for infrastructure to be healthy..."
	@sleep 20
	@$(COMPOSE) ps

# ---------------------------------------------------------------------------
# Day 1 Services
# ---------------------------------------------------------------------------
day1: ## Start Day 1 services (requires: make infra first)
	$(COMPOSE) --profile day1 up -d --build
	@echo "✅ Day 1 services started"
	@echo "   Consent Engine:    http://localhost:8003/docs"
	@echo "   Role Classifier:   http://localhost:8001/docs"
	@echo "   Lifecycle Mapper:  http://localhost:8002/docs"
	@echo "   Rights Portal:     http://localhost:8004/docs"
	@echo "   Traefik Dashboard: http://localhost:8080"
	@echo "   Jaeger UI:         http://localhost:16686"

day1-clean: ## Rebuild Day 1 services from scratch
	$(COMPOSE) --profile day1 down
	$(COMPOSE) --profile day1 build --no-cache
	$(COMPOSE) --profile day1 up -d

# ---------------------------------------------------------------------------
# All services
# ---------------------------------------------------------------------------
all: ## Start everything
	$(COMPOSE) --profile all up -d

# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------
down: ## Stop all services
	$(COMPOSE) down

down-clean: ## Stop all services and remove volumes (DESTRUCTIVE)
	$(COMPOSE) down -v --remove-orphans

logs: ## Tail logs for Day 1 services
	$(COMPOSE) logs -f consent-engine role-classifier rights-portal

ps: ## Show service status
	$(COMPOSE) ps

health: ## Check health of all services
	@echo "Checking service health..."
	@for svc in consent-engine role-classifier rights-portal lifecycle-mapper; do \
		port=$$($(COMPOSE) port $$svc 8003 2>/dev/null | cut -d: -f2); \
		echo "$$svc: $$(curl -s http://localhost:$$port/health 2>/dev/null || echo 'not ready')"; \
	done

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------
test-consent: ## Quick smoke test of consent engine
	@echo "Testing Consent Engine..."
	curl -s -X POST http://localhost:8003/consent/grant \
		-H "Content-Type: application/json" \
		-d '{"principal_id":"user-123","data_fiduciary_id":"org-abc","purpose_ids":["marketing"],"data_categories":["email","name"],"retention_days":365}' | jq .

test-classify: ## Quick smoke test of role classifier
	@echo "Testing Role Classifier..."
	curl -s -X POST http://localhost:8001/classify \
		-H "Content-Type: application/json" \
		-d '{"entity_id":"org-abc","entity_name":"Acme Corp","sector":"ecommerce","user_count":15000000,"processes_child_data":false,"ai_ml_profiling":true}' | jq .

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
env: ## Generate .env file with safe defaults
	@cp -n .env.example .env 2>/dev/null && echo "Created .env from .env.example" || echo ".env already exists"
