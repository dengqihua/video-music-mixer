#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "错误：未找到 python3。请先安装 Python 3.11。" >&2
  exit 1
fi

python3 - <<'PY'
import sys
if not ((3, 10) <= sys.version_info[:2] <= (3, 12)):
    raise SystemExit("建议使用 Python 3.10、3.11 或 3.12；优先推荐 Python 3.11。")
PY

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "错误：未找到 ffmpeg 或 ffprobe，请先安装 FFmpeg 并加入 PATH。" >&2
  if [[ "$(uname -s)" == "Darwin" ]]; then
    echo "macOS 安装命令：brew install ffmpeg" >&2
  else
    echo "Ubuntu/Debian：sudo apt update && sudo apt install -y ffmpeg" >&2
    echo "Fedora：sudo dnf install -y ffmpeg" >&2
  fi
  exit 1
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
PYTHON=".venv/bin/python"
"$PYTHON" -m pip install --upgrade pip

case "$(uname -s)" in
  Darwin)
    echo "检测到 macOS：安装适用于 Apple Silicon / Intel Mac 的 PyTorch wheel（CPU 推理由程序指定）。"
    "$PYTHON" -m pip install torch torchaudio
    ;;
  Linux)
    echo "检测到 Linux：从 PyTorch 官方 CPU wheel 源安装 torch / torchaudio。"
    "$PYTHON" -m pip install --index-url https://download.pytorch.org/whl/cpu torch torchaudio
    ;;
  *)
    echo "当前系统未自动配置：$(uname -s)" >&2
    exit 1
    ;;
esac

"$PYTHON" -m pip install -r requirements.txt
"$PYTHON" - <<'PY'
import numpy, torch, demucs, torchaudio
print("NumPy:", numpy.__version__)
print("PyTorch:", torch.__version__)
print("TorchAudio:", torchaudio.__version__)
print("Demucs:", getattr(demucs, "__version__", "installed"))
print("CUDA available:", torch.cuda.is_available())
print("MPS available:", bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available()))
PY

echo
echo "环境安装完成。运行：./run.sh"
