# ReadyTrader-Crypto Makefile
# Developer workflow automation
#
# Usage:
#   make help          - Show available targets
#   make dev           - Start development server
#   make test          - Run all tests
#   make lint          - Run linters
#   make docker-build  - Build Docker image

.PHONY: help dev test lint format check docker-build docker-run frontend clean setup

# Default target
help:
	@echo "ReadyTrader-Crypto Development Commands"
	@echo "========================================"
	@echo ""
	@echo "Setup:"
	@echo "  make setup          Install all dependencies"
	@echo "  make setup-frontend Install frontend dependencies"
	@echo ""
	@echo "Development:"
	@echo "  make dev            Start MCP server (paper mode)"
	@echo "  make dev-api        Start FastAPI server"
	@echo "  make dev-frontend   Start Next.js frontend"
	@echo "  make dev-all        Start all services"
	@echo ""
	@echo "Testing:"
	@echo "  make test           Run all tests"
	@echo "  make test-cov       Run tests with coverage"
	@echo "  make test-int       Run integration tests only"
	@echo ""
	@echo "Quality:"
	@echo "  make lint           Run all linters"
	@echo "  make format         Auto-format code"
	@echo "  make check          Run all quality checks"
	@echo "  make security       Run security scans"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-build   Build the MCP image and the API image"
	@echo "  make docker-run     Run the MCP server over stdio (paper mode)"
	@echo "  make docker-test    Test container"
	@echo ""
	@echo "Utilities:"
	@echo "  make clean          Remove generated files"
	@echo "  make docs           Check the docs against the registered tools"

# =============================================================================
# Setup
# =============================================================================
setup:
	pip install --upgrade pip
	pip install -r requirements-dev.txt
	@echo "Setup complete! Run 'make dev' to start."

setup-frontend:
	cd frontend && npm ci

setup-all: setup setup-frontend

# =============================================================================
# Development
# =============================================================================
dev:
	PAPER_MODE=true DEV_MODE=true python app/main.py

dev-api:
	PAPER_MODE=true DEV_MODE=true uvicorn api_server:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev

dev-all:
	@echo "Starting all services..."
	@echo "Run in separate terminals:"
	@echo "  Terminal 1: make dev-api"
	@echo "  Terminal 2: make dev-frontend"

# =============================================================================
# Testing
# =============================================================================
test:
	PAPER_MODE=true SIGNER_TYPE=null DEV_MODE=true pytest

test-cov:
	PAPER_MODE=true SIGNER_TYPE=null DEV_MODE=true pytest --cov=. --cov-report=term-missing --cov-report=html

test-int:
	PAPER_MODE=true SIGNER_TYPE=null DEV_MODE=true pytest tests/integration/ -v

test-frontend:
	cd frontend && npm run lint && npx tsc --noEmit

# =============================================================================
# Quality Checks
# =============================================================================
lint:
	ruff check .
	ruff format --check .
	cd frontend && npm run lint

format:
	ruff check --fix .
	ruff format .

check: lint test-cov
	bandit -q -r . -c bandit.yaml
	pip-audit -r requirements.txt
	python tools/verify_docs.py
	mdformat --check docs README.md RUNBOOK.md SECURITY.md CONTRIBUTING.md CHANGELOG.md

security:
	bandit -r . -c bandit.yaml
	pip-audit -r requirements.txt
	npm audit --prefix frontend
	@echo "For full secret scan, use: trufflehog git file://. --only-verified"

# =============================================================================
# Docker
# =============================================================================
docker-build:
	docker build -t readytrader-crypto:latest .
	docker build --target api -t readytrader-crypto:api .

# The MCP server over stdio (what an MCP client runs).
docker-run:
	docker run --rm -i \
		-e PAPER_MODE=true \
		readytrader-crypto:latest

# The approval/dashboard API server (DEV_MODE=true: no JWT, local use only).
docker-run-api:
	docker run --rm -it \
		-e PAPER_MODE=true \
		-e DEV_MODE=true \
		-p 8000:8000 \
		readytrader-crypto:api

docker-test:
	docker run --rm \
		-e PAPER_MODE=true \
		-e DEV_MODE=true \
		readytrader-crypto:latest \
		python -c "from app.core.settings import settings; print(f'OK: {settings.PROJECT_NAME} v{settings.VERSION}')"

# =============================================================================
# Documentation
# =============================================================================
docs:
	python tools/verify_docs.py
	pytest -q tests/test_docs_tool_roster.py

docs-format:
	mdformat docs README.md RUNBOOK.md SECURITY.md CONTRIBUTING.md CHANGELOG.md

# =============================================================================
# Cleanup
# =============================================================================
clean:
	rm -rf .pytest_cache
	rm -rf __pycache__
	rm -rf coverage_html
	rm -rf htmlcov
	rm -rf .coverage
	rm -rf coverage.xml
	rm -rf .ruff_cache
	rm -rf data/*.db
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

clean-all: clean
	rm -rf .venv
	rm -rf frontend/node_modules
	rm -rf frontend/.next

# =============================================================================
# Release
# =============================================================================
release-check: check
	@echo "Release checklist:"
	@echo "  1. Update version in pyproject.toml"
	@echo "  2. Update CHANGELOG.md"
	@echo "  3. Run 'make check' (completed)"
	@echo "  4. Create git tag: git tag -a vX.Y.Z -m 'Release X.Y.Z'"
	@echo "  5. Push with tags: git push --follow-tags"
