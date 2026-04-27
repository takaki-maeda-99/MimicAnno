# MimicAnno Phase 1 viewer

Read-only viewer for run directories produced by `mimicanno annotate`.
PoC-grade per `docs/superpowers/specs/2026-04-26-mimicanno-plan2-viewer-design.md`.

## Setup

```bash
pnpm install
```

## Dev

```bash
pnpm dev    # http://localhost:5173/
```

The dev server's `/runs/*` is the repo's `<repo>/runs/` directory (mounted via the `serve-runs` middleware in `vite.config.ts`). Generate a run with `mimicanno annotate` first.

## Test

```bash
pnpm test
```

Vitest unit tests live under `src/lib/__tests__/`. Components are not tested; the rendering exit criteria are verified by manual browser smoke (see the spec, §6.2).

## URL contract

| URL | Behavior |
|---|---|
| `/` | run list (sorted newest-first) |
| `/?run=<episode_id>` | open the newest run for that episode (banner if more than one) |
| `/?run=<episode_id>&hash=<run_hash_short>` | open the exact run |
