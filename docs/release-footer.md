**Pre-release / beta** — runs entirely on your machine; nothing is sent to a cloud.

## Install & run

1. Download and extract the source zip, or clone the repository:
   `git clone https://github.com/grebocheck/HFabric.git`
2. Run setup for your platform: `setup.bat` on Windows, or `./setup.sh` on
   Linux/macOS.
3. First try **STUB mode** to see the UI with no GPU: `run.bat stub` on Windows or
   `./run.sh stub` on Linux/macOS.
4. Start in REAL mode with `run.bat` or `./run.sh`.
5. Open **System → Model downloads** and fetch a starter model.

Platform support: NVIDIA CUDA is validated; AMD ROCm on Linux and Apple Silicon
MPS are experimental — testers welcome.

More detail: [README.md](https://github.com/grebocheck/HFabric/blob/main/README.md)
and [CHANGELOG.md](https://github.com/grebocheck/HFabric/blob/main/CHANGELOG.md).
