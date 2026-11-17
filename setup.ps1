$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$PythonLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($PythonLauncher) {
    & py -3.11 --version
    if ($LASTEXITCODE -ne 0) { throw "请安装 Python 3.11（建议从 python.org 安装并启用 Python Launcher）。" }
    if (-not (Test-Path ".venv")) { & py -3.11 -m venv .venv }
} else {
    $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $PythonCommand) { throw "未找到 Python。请安装 Python 3.11 并加入 PATH。" }
    & python -c "import sys; assert sys.version_info[:2] == (3, 11), '需要 Python 3.11'"
    if ($LASTEXITCODE -ne 0) { throw "请安装 Python 3.11。" }
    if (-not (Test-Path ".venv")) { & python -m venv .venv }
}

$VenvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) { throw "虚拟环境创建失败：$VenvPython" }

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue) -or -not (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
    Write-Host "请先安装 FFmpeg 并将 ffmpeg.exe、ffprobe.exe 所在目录加入 PATH。"
    Write-Host "可使用 winget install Gyan.FFmpeg 或从 https://www.ffmpeg.org/download.html 获取 Windows 构建。"
    throw "未找到 ffmpeg 或 ffprobe。"
}

function Invoke-VenvPip {
    param([string[]]$PipArguments)
    & $VenvPython -m pip @PipArguments
    if ($LASTEXITCODE -ne 0) { throw "pip 命令执行失败：$($PipArguments -join ' ')" }
}

Invoke-VenvPip @("install", "--upgrade", "pip")
Invoke-VenvPip @("install", "--index-url", "https://download.pytorch.org/whl/cpu", "torch", "torchaudio")
Invoke-VenvPip @("install", "-r", "requirements.txt")
& $VenvPython -c "import numpy, torch, demucs, torchaudio; print('NumPy:', numpy.__version__); print('PyTorch:', torch.__version__); print('TorchAudio:', torchaudio.__version__); print('CUDA available:', torch.cuda.is_available())"
if ($LASTEXITCODE -ne 0) { throw "Python 依赖检查失败。" }
Write-Host "环境安装完成。运行：.\run.ps1"
