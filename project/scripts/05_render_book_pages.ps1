param(
    [string]$Root = "C:\hobby\Shanxi",
    [string[]]$BookId = @("sxcp-2", "sxcp-3", "sxcp-4"),
    [switch]$Overwrite
)

$ErrorActionPreference = "Stop"
$env:PYTHONPATH = Join-Path $Root "project\src"
$argsList = @("-m", "shanxi_pipeline.cli", "render-book-pages", "--root", $Root)
foreach ($item in $BookId) {
    $argsList += @("--book-id", $item)
}
if ($Overwrite) {
    $argsList += "--overwrite"
}
& (Join-Path $Root ".venv\Scripts\python.exe") @argsList
