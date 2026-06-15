#!/usr/bin/env bash
# =============================================================================
#  HFabric launcher — Linux / macOS
#
#    ./run.sh          Auto mode (hardware probe selects REAL/STUB)
#    ./run.sh stub     STUB mode: full pipeline, no GPU/ML stack
#    ./run.sh --prod   PROD mode: one FastAPI port serves frontend/dist
#
#  Frees stale ports, bootstraps venv + npm on first run, then runs the FastAPI
#  backend (:8260) and the Vite frontend (:5173) in THIS terminal. Ctrl+C stops
#  both. Mirrors scripts/run.ps1.
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PYBIN="$ROOT/.venv/bin/python"
STUB_ARG=0
PROD=0

for arg in "$@"; do
  case "$arg" in
    stub|--stub) STUB_ARG=1 ;;
    --prod) PROD=1 ;;
    *)
      printf 'unknown argument: %s\n' "$arg" >&2
      exit 2
      ;;
  esac
done

load_env() {
  local file="$1"
  [ -f "$file" ] || return 0

  local line key value
  while IFS= read -r line || [ -n "$line" ]; do
    line="$(printf '%s' "$line" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    case "$line" in ""|\#*) continue ;; esac

    key="${line%%=*}"
    value="${line#*=}"
    key="$(printf '%s' "$key" | tr -d '[:space:]')"
    value="$(printf '%s' "$value" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue

    if { [ "${value:0:1}" = '"' ] && [ "${value: -1}" = '"' ]; } ||
       { [ "${value:0:1}" = "'" ] && [ "${value: -1}" = "'" ]; }; then
      value="${value:1:${#value}-2}"
    fi

    if [ -z "${!key+x}" ]; then
      export "$key=$value"
    fi
  done < "$file"
}

load_env "$ROOT/.env"

PORT="${HFAB_PORT:-8260}"
FPORT="${HFAB_FRONTEND_PORT:-5173}"
BIND_HOST="${HFAB_HOST:-127.0.0.1}"
LLAMA_PORT="${HFAB_LLAMA_PORT:-8261}"
LLAMA_EMBED_PORT="${HFAB_LLAMA_EMBED_PORT:-8262}"
export HFAB_HOST="$BIND_HOST"
export HFAB_PORT="$PORT"

if [ -t 1 ]; then
  C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_CYAN=$'\033[36m'; C_DIM=$'\033[2m'; C_RST=$'\033[0m'
else
  C_GREEN=""; C_YELLOW=""; C_CYAN=""; C_DIM=""; C_RST=""
fi
have() { command -v "$1" >/dev/null 2>&1; }

PYHOST=""
if [ -x "$PYBIN" ]; then
  PYHOST="$PYBIN"
else
  for cand in python3.12 python3.11 python3 python; do
    if have "$cand"; then PYHOST="$cand"; break; fi
  done
fi
[ -n "$PYHOST" ] || PYHOST="python3"

truthy() {
  case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

PROFILE_JSON=""
profile_get() {
  "$PYHOST" -c 'import json, sys
data = json.loads(sys.stdin.read())
value = data
for part in sys.argv[1].split("."):
    value = value[part]
if isinstance(value, bool):
    print("true" if value else "false")
elif value is not None:
    print(value)
' "$1" <<< "$PROFILE_JSON"
}

profile_list() {
  "$PYHOST" -c 'import json, sys
data = json.loads(sys.stdin.read())
value = data
for part in sys.argv[1].split("."):
    value = value[part]
for item in value or []:
    print(item)
' "$1" <<< "$PROFILE_JSON"
}

resolve_profile() {
  local prefer="${1:-}"
  local args=(scripts/install_profiles.py)
  if [ -n "$prefer" ]; then args+=(--prefer "$prefer"); fi
  PROFILE_JSON="$("$PYHOST" "${args[@]}")"
}

print_profile_summary() {
  [ -n "$PROFILE_JSON" ] || return 0
  local profile_id tier reason
  profile_id="$(profile_get selected_profile)"
  tier="$(profile_get hardware_tier)"
  reason="$(profile_get reason)"
  printf '%s[profile] %s (%s)%s\n' "$C_CYAN" "$profile_id" "${tier:-unknown}" "$C_RST"
  [ -n "$reason" ] && printf '%s[profile] %s%s\n' "$C_DIM" "$reason" "$C_RST"
  while IFS= read -r warning; do
    [ -n "$warning" ] && printf '%s[profile] warning: %s%s\n' "$C_YELLOW" "$warning" "$C_RST"
  done < <(profile_list warnings)
}

print_accelerator_install_hint() {
  printf '%s[setup] REAL mode also needs the accelerator stack.%s\n' "$C_YELLOW" "$C_RST"
  if [ -z "$PROFILE_JSON" ]; then
    printf '%s        Run ./setup.sh real to install it.%s\n' "$C_YELLOW" "$C_RST"
    return 0
  fi

  local torch_index
  torch_index="$(profile_get install.torch.index_url)"
  hint_packages=()
  while IFS= read -r package; do
    [ -n "$package" ] && hint_packages+=("$package")
  done < <(profile_list install.torch.packages)
  if [ "${#hint_packages[@]}" -gt 0 ] && [ -n "$torch_index" ]; then
    printf '%s        "%s" -m pip install %s --index-url %s%s\n' \
      "$C_YELLOW" "$PYBIN" "${hint_packages[*]}" "$torch_index" "$C_RST"
  elif [ "${#hint_packages[@]}" -gt 0 ]; then
    printf '%s        "%s" -m pip install %s%s\n' \
      "$C_YELLOW" "$PYBIN" "${hint_packages[*]}" "$C_RST"
  fi
  while IFS= read -r req; do
    [ -n "$req" ] && printf '%s        "%s" -m pip install -r %s%s\n' "$C_YELLOW" "$PYBIN" "$req" "$C_RST"
  done < <(profile_list install.requirements)
  printf '%s        Or run ./setup.sh real for the guided install.%s\n' "$C_YELLOW" "$C_RST"
}

STUB_ENV_SET=0
STUB_ENV_RAW="${HFAB_STUB_MODE-}"
if [ -n "${HFAB_STUB_MODE+x}" ] && [ -n "$HFAB_STUB_MODE" ]; then
  STUB_ENV_SET=1
fi

if [ "$STUB_ARG" = "1" ]; then
  export HFAB_STUB_MODE="true"
  printf '%s[mode] STUB - pipeline only, no GPU/ML stack%s\n' "$C_YELLOW" "$C_RST"
elif [ "$STUB_ENV_SET" = "1" ]; then
  if truthy "$STUB_ENV_RAW"; then
    export HFAB_STUB_MODE="true"
    printf '%s[mode] STUB - HFAB_STUB_MODE override%s\n' "$C_YELLOW" "$C_RST"
  else
    export HFAB_STUB_MODE="false"
    printf '%s[mode] REAL - HFAB_STUB_MODE override%s\n' "$C_GREEN" "$C_RST"
  fi
else
  resolve_profile
  print_profile_summary
  PROFILE_ID="$(profile_get selected_profile)"
  if [ "$PROFILE_ID" = "cpu-safe" ]; then
    export HFAB_STUB_MODE="true"
    printf '%s[mode] STUB - CPU-safe profile selected automatically%s\n' "$C_YELLOW" "$C_RST"
  else
    export HFAB_STUB_MODE="false"
    printf '%s[mode] REAL - %s profile selected automatically%s\n' "$C_GREEN" "$PROFILE_ID" "$C_RST"
  fi
fi

if [ "$PROD" = "0" ] && truthy "${HFAB_SERVE_FRONTEND:-}"; then
  PROD=1
fi
if [ "$PROD" = "1" ]; then
  export HFAB_SERVE_FRONTEND="true"
  printf '%s[mode] PROD - FastAPI serves frontend/dist on one port%s\n' "$C_CYAN" "$C_RST"
else
  export HFAB_SERVE_FRONTEND="${HFAB_SERVE_FRONTEND:-false}"
fi

# --- free ports held by stale instances --------------------------------------
free_port() {
  local p="$1"
  if have fuser; then
    fuser -k "${p}/tcp" >/dev/null 2>&1 || true
  elif have lsof; then
    local pids; pids="$(lsof -ti "tcp:${p}" 2>/dev/null || true)"
    [ -n "$pids" ] && kill -9 $pids >/dev/null 2>&1 || true
  fi
}
sweep_llama() {
  # A run closed by killing the terminal can orphan child llama processes that
  # keep holding RAM/VRAM; sweep them so every launch starts clean.
  for n in llama-server llama-tts; do
    pkill -9 -f "$n" >/dev/null 2>&1 || true
  done
}
for p in "$PORT" "$LLAMA_PORT" "$LLAMA_EMBED_PORT" "$FPORT"; do free_port "$p"; done
sweep_llama
sleep 0.4

# --- bootstrap backend venv --------------------------------------------------
if [ ! -x "$PYBIN" ]; then
  printf '%s[setup] creating venv + installing foundation deps...%s\n' "$C_CYAN" "$C_RST"
  "$PYHOST" -m venv .venv
  "$PYBIN" -m pip install --upgrade pip >/dev/null
  "$PYBIN" -m pip install -r backend/requirements.txt >/dev/null
  if [ "${HFAB_STUB_MODE}" = "false" ]; then
    print_accelerator_install_hint
  fi
fi

# --- bootstrap frontend deps -------------------------------------------------
if [ ! -d "$ROOT/frontend/node_modules" ]; then
  printf '%s[setup] installing frontend deps...%s\n' "$C_CYAN" "$C_RST"
  ( cd frontend && npm install )
fi

dist_stale() {
  "$PYBIN" - "$ROOT" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
front = root / "frontend"
index = front / "dist" / "index.html"
if not index.exists():
    raise SystemExit(0)
paths = [
    front / "src",
    front / "public",
    front / "index.html",
    front / "package.json",
    front / "package-lock.json",
    front / "vite.config.ts",
    front / "tsconfig.json",
]
latest = 0.0
for path in paths:
    if not path.exists():
        continue
    if path.is_file():
        latest = max(latest, path.stat().st_mtime)
        continue
    for child in path.rglob("*"):
        if child.is_file():
            latest = max(latest, child.stat().st_mtime)
raise SystemExit(0 if latest > index.stat().st_mtime else 1)
PY
}

health_ready() {
  if have curl; then
    curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1
  else
    "$PYBIN" - "$PORT" <<'PY'
from urllib.request import urlopen
import sys

try:
    with urlopen(f"http://127.0.0.1:{sys.argv[1]}/api/health", timeout=2) as res:
        raise SystemExit(0 if res.status == 200 else 1)
except Exception:
    raise SystemExit(1)
PY
  fi
}

wait_health() {
  local deadline=$((SECONDS + 45))
  while [ "$SECONDS" -lt "$deadline" ]; do
    if health_ready; then return 0; fi
    sleep 0.5
  done
  return 1
}

if [ "$PROD" = "1" ] && dist_stale; then
  printf '%s[build] frontend/dist is missing or stale -> npm run build%s\n' "$C_CYAN" "$C_RST"
  ( cd frontend && npm run build )
fi

printf '%s[run] backend  → http://%s:%s%s\n' "$C_GREEN" "$BIND_HOST" "$PORT" "$C_RST"
if [ "$PROD" = "1" ]; then
  printf '%s[run] frontend → http://localhost:%s (served by FastAPI)%s\n' "$C_GREEN" "$PORT" "$C_RST"
  printf '%s[run] one server runs in THIS terminal; press Ctrl+C to stop.%s\n\n' "$C_YELLOW" "$C_RST"
else
  printf '%s[run] frontend → http://localhost:%s%s\n' "$C_GREEN" "$FPORT" "$C_RST"
  printf '%s[run] both run in THIS terminal; press Ctrl+C to stop.%s\n\n' "$C_YELLOW" "$C_RST"
fi

# --- start backend (background) ----------------------------------------------
( cd backend && exec "$PYBIN" -m uvicorn app.main:app --host "$BIND_HOST" --port "$PORT" ) &
BACKPID=$!

cleanup() {
  printf '\n%s[stop] shutting down...%s\n' "$C_DIM" "$C_RST"
  kill "$BACKPID" >/dev/null 2>&1 || true
  sweep_llama
  free_port "$PORT"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

if [ "$PROD" = "1" ]; then
  if wait_health; then
    if have xdg-open; then xdg-open "http://localhost:$PORT"
    elif have open; then open "http://localhost:$PORT"; fi
  else
    printf '%s[warn] backend did not answer /api/health before timeout%s\n' "$C_YELLOW" "$C_RST"
  fi
  wait "$BACKPID"
else
  # --- open the UI once servers are up ---------------------------------------
  ( sleep 6
    if have xdg-open; then xdg-open "http://localhost:$FPORT"
    elif have open; then open "http://localhost:$FPORT"; fi ) >/dev/null 2>&1 &

  # --- frontend (foreground; blocks until Ctrl+C) ----------------------------
  ( cd frontend && npm run dev )
fi
