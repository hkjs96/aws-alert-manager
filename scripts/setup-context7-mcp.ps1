param(
  [string]$ApiKey = ""
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

if ($Content -match '(?m)^\[mcp_servers\.context7\]') {
  Write-Host "Context7 MCP is already configured in $ConfigPath"
  Write-Host "Backup created: $BackupPath"
  exit 0
}

if ([string]::IsNullOrWhiteSpace($ApiKey)) {
  $Block = @"

[mcp_servers.context7]
url = "https://mcp.context7.com/mcp"
"@
} else {
  $Block = @"

[mcp_servers.context7]
url = "https://mcp.context7.com/mcp"
http_headers = { "CONTEXT7_API_KEY" = "$ApiKey" }
"@
}

Add-Content -Path $ConfigPath -Value $Block

Write-Host "Added Context7 MCP to $ConfigPath"
Write-Host "Backup created: $BackupPath"
Write-Host ""
Write-Host "Next steps:"
Write-Host "1. Restart Codex."
Write-Host "2. Run /mcp and verify 'context7' is connected."
Write-Host "3. Ask a docs question with 'use context7'."
