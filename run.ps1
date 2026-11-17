$ErrorActionPreference = "Stop"
$VenvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) { throw "尚未创建虚拟环境，请先运行：.\setup.ps1" }
if (-not $env:OMP_NUM_THREADS) { $env:OMP_NUM_THREADS = "4" }
if (-not $env:MKL_NUM_THREADS) { $env:MKL_NUM_THREADS = "4" }
if (-not $env:OPENBLAS_NUM_THREADS) { $env:OPENBLAS_NUM_THREADS = "1" }
if (-not $env:NUMEXPR_NUM_THREADS) { $env:NUMEXPR_NUM_THREADS = "1" }
& $VenvPython (Join-Path $PSScriptRoot "main.py") @args
exit $LASTEXITCODE
