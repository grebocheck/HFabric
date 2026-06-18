#!/usr/bin/env bash
# =============================================================================
#  HFabric updater - Linux / macOS
#
#    ./update.sh             git pull + refresh dependencies
#    ./update.sh stub        refresh as STUB / CPU-safe
#    ./update.sh all         refresh + starter models + voice assets
#    ./update.sh --no-pull   only refresh local dependencies
#    ./update.sh --prod      also rebuild frontend/dist
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

MODE=""
NO_PULL=0
PROD=0
FORCE=0

for arg in "$@"; do
  case "$arg" in
    stub|--stub) MODE="stub" ;;
    all|--all) MODE="all" ;;
    --no-pull) NO_PULL=1 ;;
    --prod) PROD=1 ;;
    --force) FORCE=1 ;;
    *)
      printf 'unknown argument: %s\n' "$arg" >&2
      exit 2
      ;;
  esac
done

if [ -t 1 ]; then
  C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_CYAN=$'\033[36m'; C_RST=$'\033[0m'
else
  C_GREEN=""; C_YELLOW=""; C_CYAN=""; C_RST=""
fi

section() { printf '\n%s> %s%s\n' "$C_GREEN" "$1" "$C_RST"; }
warn() { printf '  %s!%s %s\n' "$C_YELLOW" "$C_RST" "$1"; }

printf '\n%sHFabric updater%s\n' "$C_CYAN" "$C_RST"

if [ "$NO_PULL" -eq 0 ]; then
  section "Updating source"
  if command -v git >/dev/null 2>&1 && [ -d ".git" ]; then
    pull_args=(pull --ff-only)
    if [ -n "$(git status --porcelain)" ]; then
      warn "Local edits detected; git pull will use --autostash."
      pull_args+=(--autostash)
    fi
    git "${pull_args[@]}"
  else
    warn "This folder is not a git checkout or git is missing; skipping source update."
  fi
fi

section "Refreshing dependencies"
setup_args=()
[ -n "$MODE" ] && setup_args+=("$MODE")
[ "$FORCE" -eq 1 ] && setup_args+=(--force)
./setup.sh "${setup_args[@]}"

if [ "$PROD" -eq 1 ]; then
  section "Rebuilding frontend"
  ( cd frontend && npm run build )
fi

printf '\n%sUpdate complete. Start with ./run.sh (or ./run.sh --prod).%s\n\n' "$C_GREEN" "$C_RST"
