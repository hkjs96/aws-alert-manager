param(
  [string]$ProjectRoot = "C:\Users\MZC01-TLSGKS678\Desktop\workspace\aws-alert-manager"
)

$ErrorActionPreference = "Stop"

$CodexDir = Join-Path $env:USERPROFILE ".codex"
$ConfigPath = Join-Path $CodexDir "config.toml"

New-Item -ItemType Directory -Force $CodexDir | Out-Null
if (-not (Test-Path $ConfigPath)) {
  New-Item -ItemType File -Path $ConfigPath -Force | Out-Null
}

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupPath = "$ConfigPath.bak.$Timestamp"
Copy-Item $ConfigPath $BackupPath -Force

$Content = Get-Content -Raw $ConfigPath

if ($Content -match '(?m)^\[mcp_servers\.serena\]') {
  Write-Host "Serena MCP is already configured in $ConfigPath"
  Write-Host "Backup created: $BackupPath"
  exit 0
}

$Block = @"

[mcp_servers.serena]
startup_timeout_sec = 60
command = "uvx"
args = [
  "--from",
  "git+https://github.com/oraios/serena",
  "serena",
  "start-mcp-server",
  "--project",
  "$($ProjectRoot.Replace('\', '\\'))",
  "--context=codex"
]
"@

Add-Content -Path $ConfigPath -Value $Block

Write-Host "Added Serena MCP to $ConfigPath"
Write-Host "Backup created: $BackupPath"
Write-Host ""
Write-Host "Next steps:"
Write-Host "1. Restart Codex."
Write-Host "2. In Codex, run /mcp and verify 'serena' is connected."
Write-Host "3. If needed, say: Activate the current dir as project using serena"
