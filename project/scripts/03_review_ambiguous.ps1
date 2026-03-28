param(
    [string]$Root = ".",
    [string[]]$BookId = @(),
    [int]$Limit = 20
)

$ErrorActionPreference = "Stop"
$env:PYTHONPATH = Join-Path $Root "project\src"
$argsList = @("-m", "shanxi_pipeline.cli", "review-ambiguous", "--root", $Root, "--limit", $Limit)
foreach ($item in $BookId) {
    $argsList += @("--book-id", $item)
}
& (Join-Path $Root ".venv\Scripts\python.exe") @argsList
