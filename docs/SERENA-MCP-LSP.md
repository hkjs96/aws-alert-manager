# Serena MCP LSP Setup for Codex

Serena is an MCP server that gives Codex IDE-like code intelligence using language-server-backed semantic tools.

Use it for:

- symbol search
- find references
- go to definition style navigation
- semantic code edits
- safer cross-file refactoring

## Configure Codex

Run this from the repository root in PowerShell:

```powershell
cd C:\Users\MZC01-TLSGKS678\Desktop\workspace\aws-alert-manager

.\scripts\setup-serena-mcp.ps1
```

The script updates:

```text
C:\Users\MZC01-TLSGKS678\.codex\config.toml
```

It also creates a backup:

```text
C:\Users\MZC01-TLSGKS678\.codex\config.toml.bak.<timestamp>
```

The added Codex MCP config is:

```toml
[mcp_servers.serena]
startup_timeout_sec = 60
command = "uvx"
args = [
  "--from",
  "git+https://github.com/oraios/serena",
  "serena",
  "start-mcp-server",
  "--project",
  "C:\\Users\\MZC01-TLSGKS678\\Desktop\\workspace\\aws-alert-manager",
  "--context=codex"
]
```

## Verify

1. Restart Codex.
2. Run:

```text
/mcp
```

3. Confirm `serena` is connected.
4. If Codex does not activate the project automatically, say:

```text
Activate the current dir as project using serena
```

## Troubleshooting

### uv cache permission error

If `uvx` fails with access denied under `AppData\Local\uv`, set a writable cache directory before starting Codex:

```powershell
$env:UV_CACHE_DIR = "C:\Users\MZC01-TLSGKS678\Desktop\workspace\aws-alert-manager\.uv-cache"
codex
```

For a permanent user environment variable:

```powershell
[Environment]::SetEnvironmentVariable(
  "UV_CACHE_DIR",
  "C:\Users\MZC01-TLSGKS678\Desktop\workspace\aws-alert-manager\.uv-cache",
  "User"
)
```

Restart Codex after setting it.

### Python interpreter permission error

If `uvx` fails while inspecting a managed Python under `AppData\Roaming\uv`, install/run Serena outside the sandbox in a normal PowerShell session:

```powershell
uvx --from git+https://github.com/oraios/serena serena start-mcp-server --help
```

Once that command succeeds, restart Codex.

### npm is not required

This setup does not use npm. That avoids the existing npm cache `EPERM` issue on this machine.
