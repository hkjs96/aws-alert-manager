param(
  [string]$ConfigPath = (Join-Path $env:USERPROFILE ".codex\config.toml")
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $ConfigPath)) {
  Write-Host "Codex config not found: $ConfigPath"
  exit 0
}

$ResolvedConfigPath = (Resolve-Path -LiteralPath $ConfigPath).Path
$Content = [System.IO.File]::ReadAllText($ResolvedConfigPath)

if ($Content -notmatch '(?m)^\[mcp_servers\.serena\]') {
  Write-Host "Serena MCP is not configured in $ConfigPath"
  exit 0
}

$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupPath = "$ConfigPath.bak.remove-serena.$Timestamp"
Copy-Item -LiteralPath $ResolvedConfigPath -Destination $BackupPath -Force

$Pattern = '(?ms)\r?\n?\[mcp_servers\.serena\]\r?\n.*?(?=\r?\n\[|\z)'
$Updated = [regex]::Replace($Content, $Pattern, '')
[System.IO.File]::WriteAllText($ResolvedConfigPath, $Updated, [System.Text.UTF8Encoding]::new($false))

Write-Host "Removed Serena MCP from $ResolvedConfigPath"
Write-Host "Backup created: $BackupPath"
Write-Host "Restart Codex after this change."
