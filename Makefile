.PHONY: help docker-build run down clean-state compose-build

PYTHON ?= python3
CONFIG ?= config.yaml
IMAGE ?= bilibili-monitor
STATE_DIR ?= state
HTTP_PROXY_URL ?= http://127.0.0.1:7890

help:
	@echo "Common targets:"
	@echo "  make docker-build   # Build Docker image ($(IMAGE))"
	@echo "  make run            # Start services via docker compose"
	@echo "  make down           # Stop services via docker compose"
	@echo "  make clean-state    # Remove generated state file(s)"

docker-build:
	docker build -t $(IMAGE) .

compose-build:
	docker compose build

run: compose-build
	@mkdir -p $(STATE_DIR)
	@cp -n config.example.yaml $(CONFIG) 2>/dev/null || true
	docker compose up -d

down:
	docker compose down

clean-state:
	rm -f $(STATE_DIR)/* $(STATE_DIR)/.gitkeep 2>/dev/null || true
	rm -f state.json
