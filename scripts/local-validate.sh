#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"

# Never reuse deploy/.env, production container names, ports, networks, or data.
# This script is safe to run beside another xiaobai-one stack.
PROJECT=${XIAOBAI_VALIDATE_PROJECT:-xiaobai-one-local-validate}
PORT=${XIAOBAI_VALIDATE_PORT:-33210}
DATA_DIR=${XIAOBAI_VALIDATE_DATA_DIR:-$ROOT/tmp/local-validate-data}
ENV_FILE=$(mktemp "$ROOT/.env.local-validate.XXXXXX")
trap 'rm -f "$ENV_FILE"' EXIT
mkdir -p "$DATA_DIR"

python3 - "$ROOT/deploy/.env.example" "$ENV_FILE" "$PROJECT" "$PORT" "$DATA_DIR" <<'PY'
from pathlib import Path
import sys

source, target, project, port, data_dir = sys.argv[1:]
values = {}
for line in Path(source).read_text(encoding="utf-8").splitlines():
    if not line or line.lstrip().startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    values[key] = value
values.update(
    {
        "COMPOSE_PROJECT_NAME": project,
        "XIAOBAI_WEB_BIND": "127.0.0.1",
        "XIAOBAI_WEB_PORT": port,
        "XIAOBAI_DATA_ROOT": data_dir,
        "XIAOBAI_HOST_DATA_DIR": data_dir,
        "XIAOBAI_SECRET_KEY": "local-validation-secret-not-for-production",
        "XIAOBAI_ENGINE_MODE": "mock",
        "XIAOBAI_ACTIVE_RUNS_GLOBAL": "1",
    }
)
Path(target).write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
PY

compose=(docker compose --env-file "$ENV_FILE" -f deploy/docker-compose.yml -p "$PROJECT")

printf '[local-validate] project=%s port=%s data=%s\n' "$PROJECT" "$PORT" "$DATA_DIR"
"${compose[@]}" build
"${compose[@]}" up -d --remove-orphans

echo "[local-validate] waiting for API health..."
healthy=0
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>/dev/null; then
    healthy=1
    break
  fi
  sleep 1
done
if [[ "$healthy" != 1 ]]; then
  "${compose[@]}" ps
  "${compose[@]}" logs --tail=100
  echo "[local-validate] API health timed out" >&2
  exit 1
fi

curl -fsS "http://127.0.0.1:$PORT/api/health" | python3 -m json.tool
curl -fsS "http://127.0.0.1:$PORT/" | head -c 200 >/dev/null

echo "[local-validate] isolated stack is reachable on http://127.0.0.1:$PORT"
echo "[local-validate] production deploy/.env and deploy/data were not modified"
