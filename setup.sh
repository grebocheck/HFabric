#!/usr/bin/env bash
# =============================================================================
#  HFabric setup — Linux / macOS
#
#    ./setup.sh            Auto setup (hardware probe -> recommended profile)
#    ./setup.sh stub       STUB mode only (no GPU/ML stack)
#    ./setup.sh real       REAL mode: GPU stack (Linux+CUDA) + optional models
#    ./setup.sh all        REAL mode + download ALL curated models (~80 GB)
#
#  Flags: --force (rebuild venv/node_modules), --skip-checks, --nunchaku
#
#  Mirrors setup.ps1. After it finishes, start the app with ./run.sh
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

VENV=".venv"
PYBIN="$VENV/bin/python"
PIPBIN="$VENV/bin/pip"

# --- args --------------------------------------------------------------------
MODE=""            # stub | real | all | (empty => auto)
FORCE=0
SKIP_CHECKS=0
WANT_NUNCHAKU=0
for arg in "$@"; do
  case "$arg" in
    stub) MODE="stub" ;;
    real) MODE="real" ;;
    all)  MODE="all" ;;
    --force) FORCE=1 ;;
    --skip-checks) SKIP_CHECKS=1 ;;
    --nunchaku) WANT_NUNCHAKU=1 ;;
    *) echo "unknown argument: $arg (expected stub|real|all|--force|--skip-checks|--nunchaku)"; exit 2 ;;
  esac
done

# --- pretty output -----------------------------------------------------------
if [ -t 1 ]; then
  C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_RED=$'\033[31m'; C_DIM=$'\033[2m'; C_RST=$'\033[0m'
else
  C_CYAN=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_DIM=""; C_RST=""
fi
section() { printf '\n%s► %s%s\n' "$C_GREEN" "$1" "$C_RST"; }
ok()      { printf '  %s✓%s %s\n' "$C_GREEN" "$C_RST" "$1"; }
warn()    { printf '  %s⚠%s %s\n' "$C_YELLOW" "$C_RST" "$1"; }
err()     { printf '  %s✗%s %s\n' "$C_RED" "$C_RST" "$1"; }
have()    { command -v "$1" >/dev/null 2>&1; }

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

OS="$(uname -s)"   # Linux | Darwin

printf '\n%s╔════════════════════════════════════════════════╗%s\n' "$C_CYAN" "$C_RST"
printf '%s║          HFabric Setup (Linux / macOS)         ║%s\n' "$C_CYAN" "$C_RST"
printf '%s╚════════════════════════════════════════════════╝%s\n' "$C_CYAN" "$C_RST"

# --- pick a Python interpreter ----------------------------------------------
PYHOST=""
for cand in python3.12 python3.11 python3 python; do
  if have "$cand"; then PYHOST="$cand"; break; fi
done

# --- prerequisite checks -----------------------------------------------------
if [ "$SKIP_CHECKS" -eq 0 ]; then
  section "Checking prerequisites"

  if [ -z "$PYHOST" ]; then
    err "Python 3 not found. Install Python 3.12 (e.g. 'sudo apt install python3.12 python3.12-venv')."
    exit 1
  fi
  PYVER="$("$PYHOST" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
  ok "Python found: $PYHOST ($PYVER)"
  case "$PYVER" in
    3.10|3.11|3.12|3.13) : ;;
    *) warn "Python $PYVER is untested; 3.12 is the validated version (nunchaku ships cp312 wheels)." ;;
  esac

  if ! have node; then
    err "Node.js not found. Install Node.js 18+ (https://nodejs.org/ or your package manager)."
    exit 1
  fi
  ok "Node.js found: $(node --version)"

  if [ "$MODE" != "stub" ] && have nvidia-smi; then
    ok "NVIDIA GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -1)"
  fi
fi
[ -n "$PYHOST" ] || PYHOST="python3"

# --- resolve install profile -------------------------------------------------
section "Hardware profile"
if [ "$MODE" = "stub" ]; then
  PROFILE_JSON="$("$PYHOST" scripts/install_profiles.py --prefer cpu-safe)"
else
  PROFILE_JSON="$("$PYHOST" scripts/install_profiles.py)"
fi
PROFILE_ID="$(profile_get selected_profile)"
PROFILE_TIER="$(profile_get hardware_tier)"
PROFILE_REASON="$(profile_get reason)"

REAL=0
if [ "$PROFILE_ID" != "cpu-safe" ]; then REAL=1; fi
if [ "$MODE" = "real" ] && [ "$REAL" -eq 0 ]; then
  warn "real requested, but no supported accelerator profile was found; setup will stay CPU-safe."
  MODE="stub"
fi
if [ "$MODE" = "all" ] && [ "$REAL" -eq 0 ]; then
  warn "all requested, but no supported accelerator profile was found; setup will stay CPU-safe."
  MODE="stub"
fi
if [ -z "$MODE" ]; then
  if [ "$REAL" -eq 1 ]; then MODE="auto"; else MODE="stub"; fi
fi

printf '\n  Profile: %s%s%s (%s)\n' "$C_CYAN" "$PROFILE_ID" "$C_RST" "$PROFILE_TIER"
printf '  %s\n' "$PROFILE_REASON"
while IFS= read -r warning; do
  [ -n "$warning" ] && warn "$warning"
done < <(profile_list warnings)

# --- create / update venv ----------------------------------------------------
section "Python virtual environment"
if [ -d "$VENV" ] && [ "$FORCE" -eq 0 ]; then
  ok "venv already exists at $VENV"
else
  [ -d "$VENV" ] && { warn "removing existing venv (--force)"; rm -rf "$VENV"; }
  echo "  creating venv with $PYHOST..."
  "$PYHOST" -m venv "$VENV"
  ok "venv created"
fi
[ -x "$PYBIN" ] || { err "venv python missing at $PYBIN — venv creation failed (need the python3-venv package?)."; exit 1; }

echo "  upgrading pip..."
"$PYBIN" -m pip install --upgrade pip >/dev/null
ok "pip upgraded"

# --- foundation deps ---------------------------------------------------------
section "Installing foundation dependencies"
"$PIPBIN" install -r backend/requirements.txt >/dev/null
ok "Foundation packages installed (FastAPI, SQLAlchemy, Pydantic, ...)"

# --- GPU / ML stack ----------------------------------------------------------
if [ "$REAL" -eq 1 ]; then
  section "Installing GPU / ML stack"
  TORCH_INDEX="$(profile_get install.torch.index_url)"
  TORCH_PACKAGES=()
  while IFS= read -r package; do
    [ -n "$package" ] && TORCH_PACKAGES+=("$package")
  done < <(profile_list install.torch.packages)
  echo "  installing PyTorch for $PROFILE_ID..."
  echo "  index: $TORCH_INDEX"
  "$PIPBIN" install "${TORCH_PACKAGES[@]}" --index-url "$TORCH_INDEX" >/dev/null
  ok "PyTorch installed"
  echo "  verifying torch profile..."
  VERIFY="$(profile_get install.verify)"
  if "$PYBIN" -c "$VERIFY"; then
    ok "PyTorch verified"
  else
    warn "torch imported but profile verification failed (driver/runtime mismatch?)"
  fi

  while IFS= read -r req; do
    [ -n "$req" ] || continue
    echo "  installing backend requirements from $req..."
    "$PIPBIN" install -r "$req" >/dev/null
  done < <(profile_list install.requirements)
  ok "Accelerated backend packages installed"

  if [ "$MODE" = "all" ]; then WANT_NUNCHAKU=1; fi
  if ! profile_list optional_features | grep -qx "nunchaku_cuda"; then
    WANT_NUNCHAKU=0
  fi
  if [ "$WANT_NUNCHAKU" -eq 1 ]; then
    NUNCHAKU_URL="https://github.com/nunchaku-ai/nunchaku/releases/download/v1.3.0dev20260213/nunchaku-1.3.0.dev20260213+cu12.8torch2.11-cp312-cp312-linux_x86_64.whl"
    echo "  installing Nunchaku (FLUX SVDQuant fp4)..."
    if "$PIPBIN" install "$NUNCHAKU_URL" >/dev/null 2>&1; then
      ok "Nunchaku installed"
    else
      warn "Nunchaku wheel install failed (needs Python 3.12 + Linux x86_64). Skipping — FLUX still works via the slower fp8 path."
    fi
  fi
fi

# --- frontend deps -----------------------------------------------------------
section "Installing frontend dependencies"
if [ -d "frontend/node_modules" ] && [ "$FORCE" -eq 0 ]; then
  ok "node_modules already exists"
else
  ( cd frontend && npm install >/dev/null )
  ok "Frontend packages installed (React, Tailwind, Vite, ...)"
fi

# --- optional model downloads ------------------------------------------------
if [ "$MODE" = "all" ]; then
  section "Downloading curated models (~80 GB)"
  "$PIPBIN" install huggingface-hub >/dev/null
  HF="$VENV/bin/huggingface-cli"
  read -r -p "  Start model downloads now? (y/N) " dl
  if [ "${dl:-n}" = "y" ]; then
    mkdir -p models/image models/llm models/lora models/embed models/vision
    "$HF" download black-forest-labs/FLUX.1-dev flux_dev.safetensors --local-dir models/image && ok "FLUX.1-dev"
    "$HF" download ByteDance/SDXL-Lightning sdxl_lightning_4step_lora.safetensors --local-dir models/lora && ok "SDXL Lightning LoRA"
    "$HF" download Gron1-ai/Gemma-3-12B-it-Heretic-v2-GGUF gemma-3-12b-it-heretic-v2-Q4_K_M.gguf --local-dir models/llm && ok "Gemma 3 12B"
    "$HF" download nomic-ai/nomic-embed-text-v1.5 nomic-embed-text-v1.5.f16.gguf --local-dir models/embed && ok "Nomic embed"
    "$HF" download Qwen/Qwen2.5-VL-3B-Instruct Qwen2.5-VL-3B-Instruct-Q4_K_M.gguf --local-dir models/vision && ok "Qwen2.5-VL"
    ok "All models downloaded to models/"
  else
    warn "Model downloads skipped — re-run './setup.sh all' later."
  fi
fi

# --- llama.cpp runtime -------------------------------------------------------
if [ "$REAL" -eq 1 ]; then
  section "Installing llama.cpp runtime"
  printf '  Downloading the matching prebuilt build (LLM/RAG/TTS/Vision)...\n'
  if ! "$PYBIN" scripts/fetch_llama.py; then
    warn "llama.cpp auto-install failed; install it later from Settings -> LLM runtime."
  fi
fi

# --- summary -----------------------------------------------------------------
section "Setup complete"
printf '\n  Start the app:\n'
if [ "$MODE" = "stub" ] || [ "$REAL" -eq 0 ]; then
  printf '    %s./run.sh stub%s\n' "$C_CYAN" "$C_RST"
else
  printf '    %s./run.sh%s   %s(./run.sh stub for no-GPU mode)%s\n' "$C_CYAN" "$C_RST" "$C_DIM" "$C_RST"
fi
printf '    backend  → http://localhost:8260\n'
printf '    frontend → http://localhost:5173\n\n'
