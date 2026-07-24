[CmdletBinding()]
param(
    [string]$Root = "C:\hobby\Shanxi",
    [string[]]$BookIds = @("sxcp-2", "sxcp-3", "sxcp-4")
)

$ErrorActionPreference = "Stop"
$python = Join-Path $Root ".venv\Scripts\python.exe"
$env:PYTHONPATH = Join-Path $Root "project\src"

$args = @(
    "-m", "shanxi_pipeline.cli",
    "build-review-priority",
    "--root", $Root
)

foreach ($bookId in $BookIds) {
    $args += @("--book-id", $bookId)
}

& $python @args
