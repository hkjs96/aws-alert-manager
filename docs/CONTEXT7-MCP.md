# Context7 MCP Setup

Context7 provides up-to-date library and framework documentation through MCP.

Use it when asking about current APIs and docs, for example:

```text
How do I use Next.js 15 app router metadata? use context7
```

## Codex Setup: Remote MCP

This avoids local npm/npx cache issues.

Run from the repository root:

```powershell
cd C:\Users\MZC01-TLSGKS678\Desktop\workspace\aws-alert-manager

.\scripts\setup-context7-mcp.ps1
```

Then restart Codex and verify:

```text
/mcp
```

You should see `context7` connected.

## Claude Code Setup

Context7 supports Claude Code through remote HTTP MCP. From a normal PowerShell
session, run:

```powershell
claude mcp add --scope user --transport http context7 https://mcp.context7.com/mcp
```

With an API key:

```powershell
claude mcp add --scope user --header "CONTEXT7_API_KEY: YOUR_CONTEXT7_API_KEY" --transport http context7 https://mcp.context7.com/mcp
```

Then restart Claude Code and verify with:

```text
/mcp
```

## With API Key

An API key is recommended for higher rate limits. Create one from the Context7 dashboard, then run:

```powershell
cd C:\Users\MZC01-TLSGKS678\Desktop\workspace\aws-alert-manager

.\scripts\setup-context7-mcp.ps1 -ApiKey "YOUR_CONTEXT7_API_KEY"
```

The script updates:

```text
C:\Users\MZC01-TLSGKS678\.codex\config.toml
```

It also creates a timestamped backup:

```text
C:\Users\MZC01-TLSGKS678\.codex\config.toml.bak.<timestamp>
```

## Config Added

Without an API key:

```toml
[mcp_servers.context7]
url = "https://mcp.context7.com/mcp"
```

With an API key:

```toml
[mcp_servers.context7]
url = "https://mcp.context7.com/mcp"
http_headers = { "CONTEXT7_API_KEY" = "YOUR_CONTEXT7_API_KEY" }
```

## Local npm Alternative

Use this only if remote MCP is unavailable:

```toml
[mcp_servers.context7]
command = "npx"
args = ["-y", "@upstash/context7-mcp"]
```

With API key:

```toml
[mcp_servers.context7]
command = "npx"
args = ["-y", "@upstash/context7-mcp", "--api-key", "YOUR_CONTEXT7_API_KEY"]
```

This machine has shown npm cache `EPERM` issues, so remote MCP is preferred.
