# U-A3 — VLM dumps viewer (sub-spec)

Date: 2026-05-17
Parent: `docs/superpowers/specs/2026-05-17-ua-dataset-processing-ui-design.md` (master, rev3)
Scope: master §2.4 (backend) + §3.3 (frontend right-panel "VLM" tab)

## 0. Background

Master spec rev2 §2.4 assumed `_vlm_dumps/*.jsonl` flat under each canonical. On-disk inspection during this dispatch found that to be incorrect everywhere (so101_phase4_v5, g3_smoke_*, gem4_*, piper_phase4_v5). Master §2.4 was rewritten to rev3 in commit `3f484ad`. This sub-spec builds on rev3.

## 1. Backend (`GET /api/runs/{canonical}/vlm_dumps.json`)

### 1.1 Route

- Path: `/api/runs/{canonical}/vlm_dumps.json`
- Method: GET
- Query: `run_set` (required, string; reuse `get_effective_root` dep from `routes.py`)
- Response: `200 application/json` with shape from master §2.4 rev3.
- Errors:
  - 400 if `run_set` missing → handled by existing `get_effective_root` dep that returns 404 only when run_set is given-but-not-found; we must add explicit 400 for missing case in our own handler (existing dep treats `None` as parent_root, which is wrong for this route).
  - 404 if canonical does not resolve in this run-set (no `episode_id` found in `index.json`).
- **Registration order**: must precede `/api/runs/{name}/{artifact}` catch-all (line 588). Add the new route within `make_router()` before that block.

### 1.2 Reader module (`mimicanno/server/vlm_dumps.py`, new)

Public API:

```python
@dataclass(frozen=True)
class VlmCall:
    call_id: str            # "_planner/call_000" | "s_001/attempt_1"
    kind: Literal["planner", "segment"]
    phase: str | None
    segment_id: str | None
    prompt: str
    raw_output: str
    parsed: object | None   # JSON-parsed response.txt; None on parse error
    failed: bool
    ms: float | None        # always None in rev3
    model_variant: str | None  # always None in rev3

def read_vlm_dumps(run_set_root: Path, episode_id: str) -> list[VlmCall]: ...
def resolve_episode_id(run_set_root: Path, canonical: str) -> str | None: ...
```

`resolve_episode_id`: reads `run_set_root/index.json`, finds entry where `manifest_url == f"{canonical}/manifest.json"`, returns its `episode_id` field. Returns `None` if not found (→ 404 in route).

`read_vlm_dumps`: walks `run_set_root/_vlm_dumps/{episode_id}/`:
- `_planner/call_NNN/` (sorted by NNN) → emit one VlmCall with `kind="planner"`.
- `s_NNN/attempt_M/` — for each `s_NNN`, take the **highest** `attempt_M` only; emit one VlmCall with `kind="segment"`.
- Missing `_vlm_dumps/<episode_id>/` → empty list.
- File-level missing handling: `prompt.txt` missing → `prompt=""`. `response.txt` missing → `raw_output=""`, `parsed=None`, `failed=True` (segments) / `failed=False` (planner is best-effort).
- JSON parse: `parsed = json.loads(response_text)` if valid JSON, else `None`. `failed = (kind=="segment" and parsed is None)`.

Ordering in returned list: all planner calls first (call_NNN ASC), then all segments (segment_id ASC).

## 2. Frontend

### 2.1 Client (`frontend/src/lib/vlmClient.ts`, new)

```ts
export type VlmCallKind = "planner" | "segment";
export interface VlmCall {
  call_id: string;
  kind: VlmCallKind;
  phase: string | null;
  segment_id: string | null;
  prompt: string;
  raw_output: string;
  parsed: unknown;
  failed: boolean;
  ms: number | null;
  model_variant: string | null;
}
export interface VlmDumps {
  canonical: string;
  run_set: string;
  episode_id: string;
  calls: VlmCall[];
}

export async function fetchVlmDumps(
  baseUrl: string, canonical: string, runSet: string,
): Promise<VlmDumps>;
```

Throws on non-200. Caller decides what to do on 404 (e.g., show "no dumps" state).

### 2.2 Component (`frontend/src/components/VlmPanel.tsx`, new)

Props:
```ts
interface VlmPanelProps {
  canonical: string | null;
  runSet: string | null;
  selectedSegmentId: string | null;   // e.g., "s_001"; null if no selection
}
```

Behavior:
- Fetches on `(canonical, runSet)` change. Loading / error / empty / data states.
- Renders list: planner rows in a header section; segment rows below, sorted.
- Row content: `[kind badge] [segment_id or "-"] phase prompt(truncated)` — clickable to expand prompt + raw_output + parsed JSON pretty-print.
- Row highlight: when `row.segment_id === selectedSegmentId`, add a CSS class `is-selected` (CSS bg color).
- Failed rows: `failed=true` adds class `is-failed` (red border).
- Empty `calls` → "No VLM dumps for this episode" placeholder.

### 2.3 RunViewer integration (`frontend/src/components/RunViewer.tsx`, edited)

- Add a right-side panel slot **only** if not already present (read first).
- Wire `<VlmPanel canonical={runState.canonical} runSet={runState.runSet} selectedSegmentId={selectedSegment?.id ?? null} />`.
- Reads segment selection from whatever signal SegmentTable already exposes (don't introduce new state).
- Do NOT touch VideoPlayer (U-A4 owns it) or any other left/center components.

## 3. Out of scope

- Editing dumps, re-running planner — read-only.
- Image bytes (`frame.png`, `keyframe_*.png`) — text-only in rev3; flagged for follow-up endpoint.
- Catalog / jobs / mask routes (U-A1 / U-A4).
- `ms` / `model_variant` writer-side enrichment.

## 4. Tests (TDD)

Backend (`tests/server/test_vlm_dumps.py`, new):
1. `read_vlm_dumps` empty (no `_vlm_dumps/`) → `[]`.
2. `read_vlm_dumps` happy path: one planner + two segments.
3. `read_vlm_dumps` skips lower attempt_M, keeps highest.
4. `read_vlm_dumps` malformed response.txt → `parsed=None, failed=True` for segment.
5. `resolve_episode_id` happy + miss.
6. Route 400 missing run_set.
7. Route 404 unknown canonical in run-set.
8. Route 200 happy path (shape match).
9. Route 200 missing `_vlm_dumps/` → `calls=[]`.
10. Route registered BEFORE catch-all (regression test: a canonical literally named "vlm_dumps.json" must still trip the catch-all... actually impossible since canonical doesn't have `.json` — assert route resolves to vlm dumps handler instead of artifact handler).

Frontend (`frontend/src/components/__tests__/VlmPanel.test.tsx`, new):
1. Renders loading state on mount.
2. Renders empty state when API returns 0 calls.
3. Renders planner + segment rows with correct ordering.
4. Row matching `selectedSegmentId` has `is-selected` class.
5. Failed row has `is-failed` class.
6. Click row → expanded prompt visible.
7. Error state when fetcher throws.

`frontend/src/components/__tests__/RunViewer.vlm.test.tsx` (small):
1. RunViewer renders VlmPanel when canonical+runSet present.
2. Segment selection in SegmentTable flows to VlmPanel's `selectedSegmentId` prop.

## 5. Risks

- The TypedDict / dataclass conversion at the route boundary needs care (FastAPI auto-serializes dataclass via `dataclasses.asdict`, but `parsed: object | None` may contain non-JSON-stringifiable Python objects). Mitigation: store `parsed` as `Any` JSON-decoded value (dict/list/etc.), never custom types.
- `index.json` schema: confirmed via `g3_smoke_20260517_1353/index.json` — entries have `manifest_url`, `episode_id`. Existing `RunsRepository.open_artifact("...","index.json")` returns bytes; we'll parse and walk.
- `attempt_M` could be 0-padded or not: glob pattern `attempt_*` + `int(name.split("_")[1])` for max selection.
- If a run-set has zero episodes annotated (no `_vlm_dumps/` at all), `read_vlm_dumps` returns empty; that is NOT a 404 (master §2.4 rev3 step 3).

## 6. Files touched

- `mimicanno/server/vlm_dumps.py` (new)
- `mimicanno/server/routes.py` (route registration before catch-all)
- `tests/server/test_vlm_dumps.py` (new)
- `frontend/src/lib/vlmClient.ts` (new)
- `frontend/src/components/VlmPanel.tsx` (new)
- `frontend/src/components/RunViewer.tsx` (right-panel slot integration)
- `frontend/src/components/__tests__/VlmPanel.test.tsx` (new)
- `frontend/src/components/__tests__/RunViewer.vlm.test.tsx` (new)
- Master spec rev3 (already committed in `3f484ad`).
