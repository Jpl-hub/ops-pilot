$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot

$targets = @(
  ".pytest_cache",
  "docs\\screenshots",
  "src\\ops_pilot.egg-info",
  "frontend\\dist",
  "frontend\\tsconfig.app.tsbuildinfo",
  "src\\opspilot\\__pycache__",
  "src\\opspilot\\api\\__pycache__",
  "src\\opspilot\\application\\__pycache__",
  "src\\opspilot\\core\\__pycache__",
  "src\\opspilot\\domain\\__pycache__",
  "src\\opspilot\\infra\\__pycache__",
  "src\\opspilot\\ingest\\__pycache__",
  "src\\opspilot\\web\\__pycache__",
  "tests\\__pycache__"
)

$removed = @()

foreach ($relativePath in $targets) {
  $targetPath = Join-Path $repoRoot $relativePath
  if (-not (Test-Path -LiteralPath $targetPath)) {
    continue
  }

  $resolved = (Resolve-Path -LiteralPath $targetPath).Path
  if (-not $resolved.StartsWith($repoRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to remove outside repository: $resolved"
  }

  Remove-Item -LiteralPath $resolved -Recurse -Force
  $removed += $relativePath
}

if ($removed.Count -eq 0) {
  Write-Output "Workspace already clean."
} else {
  Write-Output "Removed:"
  $removed | ForEach-Object { Write-Output " - $_" }
}
