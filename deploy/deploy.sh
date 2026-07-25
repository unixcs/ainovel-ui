#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  echo "[xiaobai] missing deploy/.env; copy from .env.example first" >&2
  exit 1
fi

if [[ -z "${XIAOBAI_HOST_DATA_DIR:-}" ]]; then
  data_root=$(awk -F= "/^XIAOBAI_DATA_ROOT=/{print \$2}" .env)
  data_root=${data_root:-./data}
  if [[ "$data_root" == /* ]]; then
    export XIAOBAI_HOST_DATA_DIR="$data_root"
  else
    export XIAOBAI_HOST_DATA_DIR="$ROOT_DIR/${data_root#./}"
  fi
fi

echo "[xiaobai] using host data dir: $XIAOBAI_HOST_DATA_DIR"
echo "[xiaobai] docker compose build"
docker compose --env-file .env -f docker-compose.yml build

echo "[xiaobai] docker compose up -d"
docker compose --env-file .env -f docker-compose.yml up -d

echo "[xiaobai] services"
docker compose --env-file .env -f docker-compose.yml ps
