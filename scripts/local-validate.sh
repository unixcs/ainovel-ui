#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"

cp -f deploy/.env.example deploy/.env
python3 - <<'PY'
from pathlib import Path
p = Path('deploy/.env')
text = p.read_text(encoding='utf-8')
text = text.replace('XIAOBAI_SECRET_KEY=change-this-secret-before-production', 'XIAOBAI_SECRET_KEY=local-validation-secret')
p.write_text(text, encoding='utf-8')
PY
export XIAOBAI_HOST_DATA_DIR="$ROOT/deploy/data"

docker compose --env-file deploy/.env -f deploy/docker-compose.yml build

docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d

echo "[local-validate] waiting for API health..."
for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:3210/api/health >/dev/null 2>/dev/null; then
    break
  fi
  sleep 1
done

for _ in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:3210/ >/dev/null 2>/dev/null; then
    break
  fi
  sleep 1
done

curl -fsS http://127.0.0.1:3210/api/health | python3 -m json.tool
curl -fsS http://127.0.0.1:3210/ | head -c 200 >/dev/null

echo "[local-validate] stack is reachable on http://127.0.0.1:3210"
