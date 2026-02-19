#!/usr/bin/env bash
set -euo pipefail

# OpenClaw connectivity test (Shell).
#
# Safe to commit:
# - No hardcoded tokens.
# - Reads tokens from ~/.openclaw/openclaw.json via python if env vars are not set.
#
# Usage:
#   ./agentserver/openclaw/test_connection.sh
#
# Optional overrides:
#   export OPENCLAW_CONFIG_PATH="$HOME/.openclaw/openclaw.json"
#   export OPENCLAW_GATEWAY_URL="http://127.0.0.1:18789"
#   export OPENCLAW_GATEWAY_TOKEN="..."
#   export OPENCLAW_HOOKS_TOKEN="..."

OPENCLAW_CONFIG_PATH="${OPENCLAW_CONFIG_PATH:-$HOME/.openclaw/openclaw.json}"

if [[ -z "${OPENCLAW_GATEWAY_URL:-}" || -z "${OPENCLAW_GATEWAY_TOKEN:-}" || -z "${OPENCLAW_HOOKS_TOKEN:-}" ]]; then
  if ! command -v python >/dev/null 2>&1; then
    echo "python is required to read tokens from $OPENCLAW_CONFIG_PATH"
    echo "Set OPENCLAW_GATEWAY_URL / OPENCLAW_GATEWAY_TOKEN / OPENCLAW_HOOKS_TOKEN and retry."
    exit 1
  fi

  # Populate OPENCLAW_GATEWAY_URL / OPENCLAW_GATEWAY_TOKEN / OPENCLAW_HOOKS_TOKEN if not set.
  eval "$(
    python - <<'PY'
import json, os
from pathlib import Path

cfg_path = Path(os.environ.get("OPENCLAW_CONFIG_PATH", "") or Path.home() / ".openclaw" / "openclaw.json")
cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))

port = int(cfg.get("gateway", {}).get("port", 18789))
gateway_url = os.environ.get("OPENCLAW_GATEWAY_URL", "").strip() or f"http://127.0.0.1:{port}"
gateway_token = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "").strip() or (cfg.get("gateway", {}).get("auth", {}) or {}).get("token", "")
hooks_token = os.environ.get("OPENCLAW_HOOKS_TOKEN", "").strip() or (cfg.get("hooks", {}) or {}).get("token", "")

def q(v: str) -> str:
    # single-quote safe for bash eval
    return "'" + v.replace("'", "'\"'\"'") + "'"

print(f"OPENCLAW_GATEWAY_URL={q(gateway_url.rstrip('/'))}")
print(f"OPENCLAW_GATEWAY_TOKEN={q(str(gateway_token))}")
print(f"OPENCLAW_HOOKS_TOKEN={q(str(hooks_token))}")
PY
  )"
fi

GATEWAY_URL="${OPENCLAW_GATEWAY_URL%/}"
GATEWAY_TOKEN="${OPENCLAW_GATEWAY_TOKEN}"
HOOKS_TOKEN="${OPENCLAW_HOOKS_TOKEN}"

echo "=================================================="
echo "OpenClaw connectivity test (Shell)"
echo "Gateway: $GATEWAY_URL"
echo "=================================================="

echo ""
echo "[1] GET /"
curl -sS -w "\n    status: %{http_code}\n" \
  -H "Authorization: Bearer $GATEWAY_TOKEN" \
  "$GATEWAY_URL/"

echo ""
echo "[2] POST /hooks/agent"
curl -sS -w "\n    status: %{http_code}\n" \
  -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $HOOKS_TOKEN" \
  -d '{"message":"hello from naga test_connection.sh","sessionKey":"naga:test","name":"NagaTest"}' \
  "$GATEWAY_URL/hooks/agent"

echo ""
echo "[3] POST /hooks/wake"
curl -sS -w "\n    status: %{http_code}\n" \
  -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $HOOKS_TOKEN" \
  -d '{"text":"naga test wake","mode":"now"}' \
  "$GATEWAY_URL/hooks/wake"

echo ""
echo "[4] POST /tools/invoke (sessions_list)"
curl -sS -w "\n    status: %{http_code}\n" \
  -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $GATEWAY_TOKEN" \
  -d '{"tool":"sessions_list"}' \
  "$GATEWAY_URL/tools/invoke"

echo ""
echo "DONE"

