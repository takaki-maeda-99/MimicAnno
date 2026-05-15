# Run-set switcher — design spec (2026-05-16)

## Goal

Switch the active run-set (dataset) from the MimicAnno UI **without restarting the server**.

## Background

The `mimicanno serve` server is started with a fixed `--runs-root`. Under that root there may be multiple named subdirectories (e.g. `so101_phase4_v5/`, `piper_phase4_v5/`), each with their own `index.json`. Today the user must restart the server or change the Vite proxy to switch between them. This feature removes that friction.

## Definitions

- **runs_root**: directory passed to `mimicanno serve --runs-root`. May be a **leaf** (contains `index.json` directly — current single-dataset usage) or a **parent** (contains ≥1 named subdirectories each with their own `index.json`).
- **run-set**: a named direct-child directory of `runs_root` that contains `index.json`. A run-set is identified by its directory name (e.g. `so101_phase4_v5`).
- **leaf mode**: `runs_root` itself has `index.json` but no subdirectories with their own `index.json`. The dropdown is hidden.
- **parent mode**: `runs_root` has ≥1 subdirectory run-sets. The dropdown is shown.

> **Note**: both modes can coexist. `runs/` currently has a top-level `index.json` *and* named subdirs — the switcher only exposes the subdirs. The top-level leaf entries are ignored by the new UI (they remain accessible via the old static `/runs/` path or directly).

## API additions

### `GET /api/run-sets`

Scans `runs_root` for direct subdirectories that contain `index.json`.

**Response** (200) — bare JSON array, sorted lexicographically:
```json
[
  {"name": "gem4_pick_up_bottle", "label": "gem4_pick_up_bottle"},
  {"name": "piper_phase4_v5", "label": "piper_phase4_v5"},
  {"name": "so101_phase4_v5", "label": "so101_phase4_v5"}
]
```

`label` equals `name` for now (reserved for future human-readable aliases).

If `runs_root` has subdirs with `index.json`, they are returned (subdir mode takes priority even if `runs_root/index.json` also exists — this is the real-world `runs/` state). If no subdirs qualify, returns `[]` (empty array, leaf mode).

**Errors**: 500 only on OS error; otherwise always 200 (empty list is valid).

### Modified routes: `?run_set=<name>` query parameter

All existing `/api/runs/` routes accept an **optional** `?run_set=<name>` query parameter.

| `run_set` value | Behaviour |
|---|---|
| absent or `""` | Serve from `runs_root` directly (backwards-compatible leaf mode) |
| `"so101_phase4_v5"` | Serve from `runs_root/so101_phase4_v5/` |

**Security**: same validation as `RunsRepository`:
- `_NAME_RE = r'^[A-Za-z0-9_]+$'` (identical to existing episode name regex — no hyphen added; YAGNI)
- `(runs_root / name).resolve()` must be `relative_to(runs_root.resolve())` AND not equal to it — path traversal + level guard
- The resolved path must be an existing directory

Also handles: `run_set=""` (empty string) → treated same as absent → leaf fallback.

**Error responses**:
- `name` fails regex → 400 `invalid_run_set`
- Traversal detected → 400 `invalid_run_set` (same code; don't leak path info)
- Directory does not exist → 404 `run_set_not_found`

## Frontend changes

### `RunList.tsx`

1. On mount, fetch `GET /api/run-sets` (in `?api=1` mode only; in static mode, hide the dropdown).
2. If response has ≥2 run-sets, render a `<select>` dropdown above the episode table.
3. Selected value stored in URL query param `?run_set=<name>` (read from `URLSearchParams` on init).
4. On change, navigate to the same page with `?run_set=<newname>&api=1` (full reload — keeps implementation trivial).

### `RunList.tsx` → episode links

All `<a href>` links to episodes must propagate `?run_set=` alongside `?api=1`:
```
?run=${episode_id}&hash=${run_hash_short}&api=1&run_set=so101_phase4_v5
```

### `RunViewer.tsx` / `ApiToggleContext`

`ApiToggleContext` currently only tracks `apiEnabled` and `apiBase`. Add `runSet: string` (empty = no run-set).

All `fetch(${apiBase}index.json)` and `fetch(${apiBase}${name}/manifest.json)` calls append `?run_set=${runSet}` when `runSet !== ""`.

### `App.tsx`

Read `?run_set=` from `URLSearchParams`, pass into `ApiToggleProvider`:
```tsx
const runSet = params.get("run_set") ?? "";
<ApiToggleProvider apiEnabled={apiEnabled} runSet={runSet}>
```

## Out of scope

- Creating/deleting/renaming run-sets from the UI
- Nested subdirectories (only direct children of `runs_root`)
- Persistent selection (localStorage / cookie) — URL param is enough
- Human-readable labels beyond directory name
- Authentication / per-run-set access control

## Backwards compatibility

- All existing bookmarks (`?api=1` without `?run_set=`) continue to work (leaf-mode fallback).
- Static `/runs/` path (Vite dev proxy to `dist/`) is untouched.
- `--runs-root` CLI flag semantics unchanged; no new flags needed.

## Test plan

### Server unit tests
- `GET /api/run-sets` with a tmp dir containing 2 subdirs each with `index.json` → returns 2-entry bare array, sorted.
- `GET /api/run-sets` with a tmp dir containing root `index.json` AND subdirs → subdirs returned (not `[{"name":"."}]`).
- `GET /api/run-sets` with a tmp dir containing no qualifying subdirs → `[]`.
- `GET /api/runs/index.json?run_set=so101_phase4_v5` → reads from `runs_root/so101_phase4_v5/index.json`.
- `GET /api/runs/index.json?run_set=../evil` → 400.
- `GET /api/runs/index.json?run_set=` (empty) → falls back to `runs_root` directly.
- `GET /api/runs/index.json?run_set=nonexistent` → 404.

### Frontend unit tests (vitest)
- `RunList` renders dropdown when `run-sets` response has ≥2 entries.
- `RunList` hides dropdown when `run-sets` response is empty.
- Episode links include `run_set` param when active.

### Smoke test
1. Start server with `--runs-root runs/` (parent mode).
2. Open UI in browser at `?api=1`.
3. Dropdown shows `piper_phase4_v5`, `so101_phase4_v5`, `gem4_pick_up_bottle`, `gem4_replace_the_cookie`.
4. Select `so101_phase4_v5` → episode list updates to 23 SO101 episodes.
5. Select `piper_phase4_v5` → episode list updates to 39 Piper episodes.
6. Click an episode → viewer loads, PATCH still works with `?run_set=` in URL.
