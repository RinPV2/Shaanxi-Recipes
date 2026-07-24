param(
    [string]$Root = "C:\hobby\Shanxi",
    [string]$Host = "127.0.0.1",
    [int]$Port = 8765,
    [switch]$Background
)

$ErrorActionPreference = "Stop"
$python = Join-Path $Root ".venv\Scripts\python.exe"
$env:PYTHONPATH = Join-Path $Root "project\src"

if ($Background) {
    $logPath = Join-Path $Root "logs\\review-web.log"
    $argsList = @("-m", "shanxi_pipeline.cli", "serve-review-web", "--root", $Root, "--host", $Host, "--port", $Port)
    Start-Process -FilePath $python -ArgumentList $argsList -WorkingDirectory $Root -RedirectStandardOutput $logPath -RedirectStandardError $logPath
    Write-Output "review-web started at http://$Host`:$Port"
} else {
    & $python -m shanxi_pipeline.cli serve-review-web --root $Root --host $Host --port $Port
}
