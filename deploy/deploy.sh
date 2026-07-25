#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  echo "[xiaobai] missing deploy/.env; copy from .env.example first" >&2
  exit 1
fi

echo "[xiaobai] docker compose build"
docker compose --env-file .env -f docker-compose.yml build

echo "[xiaobai] docker compose up -d"
docker compose --env-file .env -f docker-compose.yml up -d

echo "[xiaobai] services"
docker compose --env-file .env -f docker-compose.yml ps
