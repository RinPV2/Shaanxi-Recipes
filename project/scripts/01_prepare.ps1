param(
    [string]$Root = "C:\hobby\Shanxi"
)

$ErrorActionPreference = "Stop"
$env:PYTHONPATH = Join-Path $Root "project\src"
& (Join-Path $Root ".venv\Scripts\python.exe") -m shanxi_pipeline.cli prepare --root $Root
