# Embla BoxLite Runtime Image

Canonical local build context for the default BoxLite execution runtime.

## Purpose

- Provide a stable Embla-owned image tag for BoxLite sessions.
- Keep guest dependencies minimal and deterministic.
- Include the shell/runtime tools that Embla child sessions expect by default:
  - `python`
  - `bash`
  - `git`
  - `ca-certificates`
  - `curl`

The runtime image does **not** bake the full repository into the image. Embla mounts the task worktree into `/workspace` at execution time, and the guest helper runs from that mounted checkout.

## Build

```bash
python scripts/build_boxlite_runtime_image.py
```

Or prepare and validate through the runtime lifecycle entrypoint:

```bash
python main.py --prepare-runtime
```
