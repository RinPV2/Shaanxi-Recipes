param(
    [string]$Root = "C:\hobby\Shanxi",
    [string[]]$BookId = @("sxcp-2", "sxcp-3", "sxcp-4")
)

$ErrorActionPreference = "Stop"
$env:PYTHONPATH = Join-Path $Root "project\src"
$argsList = @("-m", "shanxi_pipeline.cli", "build-page-review", "--root", $Root)
foreach ($item in $BookId) {
    $argsList += @("--book-id", $item)
}
& (Join-Path $Root ".venv\Scripts\python.exe") @argsList
