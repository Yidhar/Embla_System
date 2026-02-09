---
name: context7
description: Context7 MCP via mcporter (stdio). Use for library/API docs, setup, and configuration guidance with up-to-date sources.
allowed-tools: Bash(npx:*)
---

# Context7 via MCP (stdio)

Use the Context7 MCP server through mcporter in stdio mode. This keeps the MCP server local and avoids extra config files.

## Quick Checks

```bash
npx -y mcporter@latest list --stdio "npx -y @upstash/context7-mcp@latest" --name context7 --schema
```

## Resolve Library ID

```bash
npx -y mcporter@latest call --stdio "npx -y @upstash/context7-mcp@latest" --name context7 resolve-library-id \
  query="How do I use React hooks?" \
  libraryName="react"
```

## Query Docs

```bash
npx -y mcporter@latest call --stdio "npx -y @upstash/context7-mcp@latest" --name context7 query-docs \
  libraryId="/websites/react_dev" \
  query="useEffect cleanup examples"
```

## Optional API Key

If you have a Context7 API key, set `CONTEXT7_API_KEY` in the environment before running the commands above.
