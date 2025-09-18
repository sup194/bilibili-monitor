.PHONY: help install run once docker-build docker-run docker-once clean-state

PYTHON ?= python3
CONFIG ?= config.yaml
IMAGE ?= bilibili-monitor
STATE_DIR ?= state

help:
	@echo "Common targets:"
	@echo "  make install        # Install Python dependencies"
	@echo "  make run            # Run monitor with $(CONFIG)"
	@echo "  make once           # Run a single polling cycle"
	@echo "  make docker-build   # Build Docker image ($(IMAGE))"
	@echo "  make docker-run     # Run container using $(CONFIG)"
	@echo "  make docker-once    # Run container for one cycle"
	@echo "  make clean-state    # Remove generated state file(s)"

install:
	$(PYTHON) -m pip install -r requirements.txt

run:
	$(PYTHON) main.py --config $(CONFIG)

once:
	$(PYTHON) main.py --config $(CONFIG) --once --log-level INFO

docker-build:
	docker build -t $(IMAGE) .

docker-run: docker-build
	@mkdir -p $(STATE_DIR)
	docker run -d \
		-v $(PWD)/$(CONFIG):/config/config.yaml:ro \
		-v $(PWD)/$(STATE_DIR):/data \
		$(IMAGE)

docker-once: docker-build
	@mkdir -p $(STATE_DIR)
	docker run --rm \
		-v $(PWD)/$(CONFIG):/config/config.yaml:ro \
		-v $(PWD)/$(STATE_DIR):/data \
		$(IMAGE) --once --log-level INFO

clean-state:
	rm -f $(STATE_DIR)/* $(STATE_DIR)/.gitkeep 2>/dev/null || true
	rm -f state.json
