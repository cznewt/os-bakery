.PHONY: help install dev migrate makemigrations run shell test lint format superuser celery clean orm-diagram seed-catalog compose-up compose-down compose-logs compose-shell compose-reset

help:
	@awk 'BEGIN{FS=":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install runtime dependencies
	uv pip install -e .

dev: ## Install dev dependencies
	uv pip install -e ".[dev]"

migrate: ## Apply database migrations
	python manage.py migrate

makemigrations: ## Create new migrations from model changes
	python manage.py makemigrations

run: ## Run the dev server on :8000
	python manage.py runserver 0.0.0.0:8000

shell: ## Open a Django shell (django-extensions shell_plus if available)
	python manage.py shell_plus || python manage.py shell

test: ## Run the test suite
	pytest

lint: ## Lint with ruff
	ruff check .

format: ## Format with ruff
	ruff format .

superuser: ## Create a superuser
	python manage.py createsuperuser

celery: ## Run a Celery worker for the builds queue
	celery -A osbakery worker -l info -Q builds,default

clean: ## Remove caches and build intermediates
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage

seed-catalog: ## Populate Architecture / HardwareTarget / OperatingSystem / OSRelease / UpstreamImage rows
	python manage.py seed_catalog

# ---------------------------------------------------------------------------
# Docker compose stack (postgres, redis, minio, salt-master, web, worker)
# ---------------------------------------------------------------------------

compose-up: ## Boot the full local stack in the background
	docker compose up -d --build

compose-down: ## Stop the stack (keep volumes)
	docker compose down

compose-reset: ## Stop the stack AND wipe volumes (fresh DB / S3 / Salt pki)
	docker compose down -v

compose-logs: ## Tail logs for web + worker
	docker compose logs -f web worker

compose-shell: ## Drop into a Django shell against the running stack
	docker compose exec web python manage.py shell

orm-diagram: ## Regenerate docs/orm.{svg,png,dot} via the Docker base image
	docker build --target base -t os-bakery-base .
	docker run --rm -v $(CURDIR):/app -w /app \
		-e DJANGO_SECRET_KEY=dev -e DATABASE_URL=sqlite:////tmp/dev.sqlite3 \
		os-bakery-base sh -c '\
			apt-get update -qq && \
			DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends -qq \
				graphviz libgraphviz-dev pkg-config build-essential >/dev/null && \
			pip install --quiet pygraphviz pydot && \
			python manage.py graph_models tenants catalog recipes builds infra \
				--pygraphviz --rankdir=LR --color-code-deletions \
				--arrow-shape normal -o docs/orm.svg && \
			python manage.py graph_models tenants catalog recipes builds infra \
				--pygraphviz --rankdir=LR --color-code-deletions \
				--arrow-shape normal -o docs/orm.png && \
			python manage.py graph_models tenants catalog recipes builds infra \
				--dot --rankdir=LR --color-code-deletions \
				--arrow-shape normal -o docs/orm.dot && \
			chown -R $(shell id -u):$(shell id -g) docs/orm.svg docs/orm.png docs/orm.dot \
		'
