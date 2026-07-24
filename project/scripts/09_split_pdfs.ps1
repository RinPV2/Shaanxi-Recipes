param(
    [string]$Root = "C:\hobby\Shanxi",
    [string[]]$BookId = @("sxcp-1", "sxcp-2", "sxcp-3", "sxcp-4"),
    [int]$MaxPages = 200,
    [int]$MaxMegabytes = 100
)

$ErrorActionPreference = "Stop"
$env:PYTHONPATH = Join-Path $Root "project\src"
$argsList = @("-m", "shanxi_pipeline.cli", "split-pdfs", "--root", $Root, "--max-pages", $MaxPages, "--max-megabytes", $MaxMegabytes)
foreach ($item in $BookId) {
    $argsList += @("--book-id", $item)
}
& (Join-Path $Root ".venv\Scripts\python.exe") @argsList
