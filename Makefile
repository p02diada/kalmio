SHELL := /bin/bash
.DEFAULT_GOAL := dev

.PHONY: help dev dev-local reve-import down logs

LAN_IP ?= $(shell python -c 'import socket; s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("8.8.8.8", 80)); print(s.getsockname()[0])' 2>/dev/null || echo 127.0.0.1)
DEV_ORIGIN := http://$(LAN_IP):5173
DEV_ORIGINS := http://localhost:5173,http://127.0.0.1:5173,$(DEV_ORIGIN)

help:
	@printf "Targets:\n"
	@printf "  make dev         Start the Docker Compose dev stack and expose it on the LAN IP (%s)\n" "$(LAN_IP)"
	@printf "  make reve-import Run the REVE bootstrap import into the Postgres dev database\n"
	@printf "  make down        Stop the Compose stack\n"
	@printf "  make logs        Tail Compose logs\n"

dev:
	@set -euo pipefail; \
	  export DJANGO_ALLOWED_HOSTS="localhost,127.0.0.1,0.0.0.0,backend,$(LAN_IP)"; \
	  export CORS_ALLOWED_ORIGINS="$(DEV_ORIGINS)"; \
	  export CSRF_TRUSTED_ORIGINS="$(DEV_ORIGINS)"; \
	  export VITE_API_BASE_URL="same-origin"; \
	  export VITE_DEV_API_PROXY_TARGET="http://backend:8000"; \
	  docker compose up --build

dev-local:
	@set -euo pipefail; \
	  export DJANGO_ALLOWED_HOSTS="localhost,127.0.0.1,0.0.0.0,backend"; \
	  export CORS_ALLOWED_ORIGINS="http://localhost:5173,http://127.0.0.1:5173"; \
	  export CSRF_TRUSTED_ORIGINS="http://localhost:5173,http://127.0.0.1:5173"; \
	  export VITE_API_BASE_URL="same-origin"; \
	  export VITE_DEV_API_PROXY_TARGET="http://backend:8000"; \
	  docker compose up --build

reve-import:
	@set -euo pipefail; \
	  export DJANGO_ALLOWED_HOSTS="localhost,127.0.0.1,0.0.0.0,backend,$(LAN_IP)"; \
	  export CORS_ALLOWED_ORIGINS="$(DEV_ORIGINS)"; \
	  export CSRF_TRUSTED_ORIGINS="$(DEV_ORIGINS)"; \
	  docker compose --profile tools run --rm reve-import

down:
	@docker compose down

logs:
	@docker compose logs -f
