param(
    [string]$Root = ".",
    [string]$MineruJson
)

$ErrorActionPreference = "Stop"
if (-not $MineruJson) {
    throw "Provide -MineruJson with the MinerU JSON path for sxcp-1."
}

$env:PYTHONPATH = Join-Path $Root "project\src"
& (Join-Path $Root ".venv\Scripts\python.exe") -m shanxi_pipeline.cli import-book --root $Root --book-id sxcp-1 --mineru-json $MineruJson
