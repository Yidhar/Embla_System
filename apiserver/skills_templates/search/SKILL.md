---
name: search
description: Search via Firecrawl MCP using mcporter.
allowed-tools: Bash(npx:*)
---

# Search (Firecrawl MCP)

This skill routes search requests through the Firecrawl MCP server using mcporter.

## Configure mcporter

The installer writes a mcporter config file at:

- `~/.mcporter/config.json`

Make sure the file contains a `firecrawl-mcp` entry with a valid API key:

```json
{
  "mcpServers": {
    "firecrawl-mcp": {
      "command": "npx",
      "args": ["-y", "firecrawl-mcp"],
      "env": {
        "FIRECRAWL_API_KEY": "YOUR_FIRECRAWL_API_KEY"
      }
    }
  }
}
```

## List tools

```bash
npx -y mcporter@latest list --config ~/.mcporter/config.json firecrawl-mcp
```

## Example call

```bash
npx -y mcporter@latest call --config ~/.mcporter/config.json firecrawl-mcp.search query="YOUR_QUERY"
```
