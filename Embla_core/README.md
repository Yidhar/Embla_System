# Embla_core

Embla_core is the standalone Next.js dashboard frontend for autonomous runtime operations.

## Scope

Current P0 routes:

- `/runtime-posture`
- `/mcp-fabric`
- `/memory-graph`
- `/workflow-events`

## Quick Start

```bash
cd Embla_core
npm install
npm run dev
```

Optional API base override:

```bash
NEXT_PUBLIC_API_BASE=http://127.0.0.1:8000 npm run dev
```

## API Wiring

- Runtime posture: `/v1/ops/runtime/posture`
- MCP fabric: `/v1/ops/mcp/fabric`

The first two routes are wired in `lib/api/ops.ts`; memory/workflow pages are scaffold placeholders for the next slice.
