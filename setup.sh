#!/usr/bin/env bash
# =============================================================================
#  HFabric setup — Linux / macOS
#
#    ./setup.sh            Guided setup (pick STUB / REAL / REAL+models)
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
MODE=""            # stub | real | all | (empty => guided)
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

  if [ "$MODE" != "stub" ]; then
    if [ "$OS" = "Darwin" ]; then
      warn "macOS has no CUDA — REAL/GPU mode is not supported here. Falling back to STUB."
      MODE="stub"
    elif ! have nvidia-smi; then
      warn "nvidia-smi not found — REAL mode needs an NVIDIA GPU + drivers."
      read -r -p "  Continue with STUB mode instead? (y/N) " ans
      [ "${ans:-n}" = "y" ] || exit 1
      MODE="stub"
    else
      ok "NVIDIA GPU: $(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -1)"
    fi
  fi
fi
[ -n "$PYHOST" ] || PYHOST="python3"

# --- guided mode selection ---------------------------------------------------
if [ -z "$MODE" ]; then
  section "Setup mode"
  echo "  1) STUB  — no GPU, test the foundation   ← fastest, recommended first"
  echo "  2) REAL  — GPU stack only"
  echo "  3) REAL + models  — GPU stack + download curated models (~80 GB)"
  read -r -p "  Select (1-3, default 1): " choice
  case "${choice:-1}" in
    2) MODE="real" ;;
    3) MODE="all" ;;
    *) MODE="stub" ;;
  esac
fi

REAL=0
[ "$MODE" = "real" ] || [ "$MODE" = "all" ] && REAL=1
printf '\n  Mode: %s%s%s\n' "$C_CYAN" "$MODE" "$C_RST"

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
  echo "  installing PyTorch + CUDA 12.8 (2–5 min, ~2 GB)..."
  "$PIPBIN" install torch torchvision --index-url https://download.pytorch.org/whl/cu128 >/dev/null
  ok "PyTorch + CUDA installed"
  echo "  verifying torch..."
  "$PYBIN" -c "import torch; print('    torch', torch.__version__, '| cuda', torch.cuda.is_available())" || \
    warn "torch imported but CUDA check failed (driver mismatch?)"

  echo "  installing GPU backends (diffusers, transformers, accelerate, bitsandbytes)..."
  "$PIPBIN" install -r backend/requirements-gpu.txt >/dev/null
  ok "GPU backends installed"

  if [ "$MODE" = "all" ]; then WANT_NUNCHAKU=1; fi
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

# --- llama.cpp note ----------------------------------------------------------
if [ "$REAL" -eq 1 ] && [ ! -x "bin/llama/llama-server" ]; then
  warn "LLM/RAG/TTS/Vision need a llama.cpp CUDA build at bin/llama/ (no .exe on Linux):"
  printf '      %sbin/llama/llama-server, llama-tts, llama-mtmd-cli%s\n' "$C_DIM" "$C_RST"
  printf '      %sBuild llama.cpp with -DGGML_CUDA=ON or grab a release, then copy the binaries there.%s\n' "$C_DIM" "$C_RST"
fi

# --- summary -----------------------------------------------------------------
section "Setup complete"
printf '\n  Start the app:\n'
if [ "$MODE" = "stub" ]; then
  printf '    %s./run.sh stub%s\n' "$C_CYAN" "$C_RST"
else
  printf '    %s./run.sh%s   %s(./run.sh stub for no-GPU mode)%s\n' "$C_CYAN" "$C_RST" "$C_DIM" "$C_RST"
fi
printf '    backend  → http://localhost:8260\n'
printf '    frontend → http://localhost:5173\n\n'
