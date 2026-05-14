# vtsls Language Server Notes

`vtsls` is a TypeScript language server. It speaks LSP over stdio, so editors or agents that support a `language-server` section can start it directly.

This is different from MCP. Codex can use an LSP only if there is an MCP bridge/server that exposes LSP operations as MCP tools. Without that bridge, `vtsls` can still be used by editors and Claude Code style LSP integrations, but not directly as a Codex MCP tool.

## Install

Run from the frontend directory:

```powershell
cd C:\Users\MZC01-TLSGKS678\Desktop\workspace\aws-alert-manager\frontend

npm install -D @vtsls/language-server
```

If npm cache permissions fail, use a writable npm cache:

```powershell
cd C:\Users\MZC01-TLSGKS678\Desktop\workspace\aws-alert-manager\frontend

$env:npm_config_cache = "C:\Users\MZC01-TLSGKS678\Desktop\workspace\aws-alert-manager\.npm-cache"
npm install -D @vtsls/language-server
```

## Smoke Test

This starts the server and waits for LSP JSON-RPC input on stdin.

```powershell
cd C:\Users\MZC01-TLSGKS678\Desktop\workspace\aws-alert-manager\frontend

npx vtsls --stdio
```

Terminate with `Ctrl+C`.

## Claude Code Style LSP Config

If your tool supports a `language-server` config block, the shape is usually:

```json
{
  "language-server": {
    "vtsls": {
      "command": "npx",
      "args": ["vtsls", "--stdio"],
      "root": "C:\\Users\\MZC01-TLSGKS678\\Desktop\\workspace\\aws-alert-manager\\frontend"
    }
  }
}
```

If the tool runs commands from the frontend directory already, this shorter form also works:

```json
{
  "language-server": {
    "vtsls": {
      "command": "npx",
      "args": ["vtsls", "--stdio"]
    }
  }
}
```

## Codex Note

Codex MCP config cannot use `vtsls --stdio` directly because `vtsls` speaks LSP, not MCP.

For Codex, use one of these:

- An LSP-to-MCP bridge that launches `vtsls --stdio` and exposes MCP tools.
- Context7 MCP for current library documentation. This is not a code-indexing
  replacement for LSP, but it is simpler and works with both Codex and Claude
  Code.

The Context7 setup for this repo is documented in:

```text
docs/CONTEXT7-MCP.md
```
