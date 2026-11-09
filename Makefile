.PHONY: install dev dev-backend dev-frontend test lint format build clean data-check extract agents live dev-live

install:
	cd backend && uv sync
	cd frontend && npm install

# Runs both apps. The frontend is at http://localhost:5173.
dev:
	$(MAKE) -j2 dev-backend dev-frontend

dev-backend:
	cd backend && uv run uvicorn phenoctx.api:app --reload --port 8010

dev-frontend:
	cd frontend && npm run dev

# Optional. Like dev, but adds "Ask it yourself" to the app, using a real model. Needs the full
# CSVs, plus Ollama running or a backend set in .env.
live:
	$(MAKE) -j2 dev-live dev-frontend

dev-live:
	cd backend && LIVE_MODE=on uv run $(if $(wildcard .env),--env-file ../.env) uvicorn phenoctx.api:app --reload --port 8010

test:
	cd backend && uv run pytest

lint:
	cd backend && uv run ruff check . && uv run ruff format --check .

format:
	cd backend && uv run ruff check --fix . && uv run ruff format .

build:
	cd frontend && npm run build

# Removes caches and build output. Leaves dependencies and data alone.
clean:
	find backend -path backend/.venv -prune -o -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache \) -prune -exec rm -rf {} +
	rm -rf frontend/dist

# Fails if the local CSVs are not the canonical population.
data-check:
	cd data/synthea && shasum -a 256 -c checksums.sha256

# Rebuilds the committed data/extract/ from the full CSVs.
extract:
	cd backend && uv run python -m phenoctx.extract

# Optional. Regenerates the saved comparison on Anthropic or Ollama, see the README.
RUNS ?= 10
agents:
	cd backend && uv run $(if $(wildcard .env),--env-file ../.env) python -m phenoctx.agents --runs $(RUNS)
