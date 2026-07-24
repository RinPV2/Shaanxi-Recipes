param(
    [string]$Root = "C:\hobby\Shanxi",
    [string[]]$BookId = @(),
    [switch]$Overwrite
)

# 将四册书每页渲染为 144dpi 灰度 WebP（q55），输出到 assets\pages\<book_id>\p####.webp
$env:PYTHONPATH = Join-Path $Root "project\src"
$python = Join-Path $Root ".venv\Scripts\python.exe"
$args = @("-m", "shanxi_pipeline.cli", "export-page-images", "--root", ($Root -replace '\', '/'))
foreach ($id in $BookId) { $args += @("--book-id", $id) }
if ($Overwrite) { $args += "--overwrite" }
& $python @args
