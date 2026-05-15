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

Vitest unit + component tests live under `src/lib/__tests__/` and
`src/components/__tests__/` (jsdom + @testing-library/react). The
component tests cover the Phase 5 B r1 segment dropdown / PATCH client /
labelset cache / RunViewer end-to-end PATCH wiring.

## URL contract

| URL | Behavior |
|---|---|
| `/` | run list (sorted newest-first) |
| `/?run=<episode_id>` | open the newest run for that episode (banner if more than one) |
| `/?run=<episode_id>&hash=<run_hash_short>` | open the exact run |
| `/?api=1` | route all fetches through `/api/runs/` (Phase 5 A server) instead of static `/runs/`, and render the phase dropdown for editing (Phase 5 B r1) |

Combine `?api=1` with the run selectors, e.g.
`/?api=1&run=episode_000000&hash=e3506110`.

## Phase 5 B r1 edit mode

When `?api=1` is on, each segment row's phase cell renders as a
`<select>` populated from `/api/labelset`. Changing the value fires a
`PATCH /api/runs/<name>/segments/<segment_id>` with
`If-Match: "<run_hash>"` taken from the currently-loaded manifest. The
client enforces a single in-flight PATCH at a time (all `<select>`s
disabled while one is pending) so the manifest hash never lags behind
the actual server state during rapid edits.

On 412 (`etag_mismatch`) the cell rolls back to its prior value, an
alert toast appears, every dropdown is disabled, and a `reload` button
is rendered — the only safe recovery in r1 is a full page reload to
re-read the new `run_hash`.

`MIMICANNO_REVIEWER` (set on the server when running `mimicanno serve`)
is captured at server startup and stamped as `reviewer_id` on every
persisted edit.
