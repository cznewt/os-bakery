.PHONY: help install dev migrate makemigrations run shell test lint format superuser celery clean

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
