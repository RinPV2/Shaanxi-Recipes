param(
    [string]$Root = ".",
    [string]$Source = ".\work\page_review_md"
)

$ErrorActionPreference = "Stop"
$env:PYTHONPATH = Join-Path $Root "project\src"
& (Join-Path $Root ".venv\Scripts\python.exe") -m shanxi_pipeline.cli learn-from-confirmations --root $Root --source $Source
