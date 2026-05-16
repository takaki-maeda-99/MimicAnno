# Phase 5 D — Evaluation harness results (2026-05-16)

## What shipped

- **EditEvent dataclass** (`mimicanno/schema.py`): tracks `edit_type`, `segment_id`, `edited_at` (ISO-8601 UTC), `client_edit_duration_ms` (optional int ≥ 0), `reviewer`.
- **AnnotationResult.history** (`list[EditEvent]`): append-only audit log persisted in `annotation.json` (key omitted when empty for backward compat). Annotation schema bumped `0.2.0 → 0.3.0` (COMPAT_BLOCK stays at major=0).
- **All 4 PATCH routes** now accept optional `client_edit_duration_ms` in request body:
  - `PATCH /api/runs/{name}/segments/{id}` (phase relabel)
  - `PATCH /api/runs/{name}/segments/{id}/reviewed`
  - `PATCH /api/runs/{name}/segments/{id}/labels`
  - `PATCH /api/runs/{name}/boundaries/{id}`
  - Validation: float → 400 `invalid_body`; negative int → 400 `invalid_body`; absent/null → `None` (no error).
- **`event_builder.py`** (`mimicanno/server/event_builder.py`): thin helper that builds an `EditEvent` with `datetime.now(UTC).isoformat()`.
- **`mimicanno eval` CLI** (`mimicanno/eval/`):
  - `metrics.py`: `RunMetrics`, `compute_metrics()`, `aggregate()`
  - `render.py`: `render_markdown()`, `render_json()`
  - `cli.py`: `eval` typer subcommand with `--run` filter and `--format markdown|json`
- **Frontend timing hook** (`frontend/src/`):
  - All 4 edit clients accept `clientEditDurationMs?: number | null`
  - `SegmentTable` / `SegmentRow`: `onEditFocus` prop wires `onFocus` on all editable inputs
  - `RunViewer`: single `editStartRef = useRef<number | null>(null)` shared across all edit types; duration computed and cleared on each submit

## Test results

- 10 new tests added (6 unit + 4 route); all pass
- 210 existing server tests: all pass
- mypy --strict on changed files: clean

## Smoke test (T13)

Server started at `/tmp/smoke_runs/` (copy of SO101 ep0).

```
PATCH /api/runs/episode_000000__e35061106394/segments/episode_000000__seg0000/reviewed
  body: {"reviewed": false, "client_edit_duration_ms": 2500}
→ 200 OK
```

`annotation.json` history:
```json
[
  {
    "client_edit_duration_ms": 2500,
    "edit_type": "reviewed",
    "edited_at": "2026-05-15T21:46:09.826669Z",
    "reviewer": null,
    "segment_id": "episode_000000__seg0000"
  }
]
```

`mimicanno eval /tmp/smoke_runs/ --format markdown`:
```
| run | edits | edit_time_ms | client_cov | human_segs | total_segs | label_agr |
|-----|-------|-------------|------------|------------|------------|----------|
| episode_000000__e35061106394 | 1 | 2500 | 1.00 | 0 | 5 | 0.00 |
| **total** | 1 | 2500 | 1.00 | 0 | 5 | 0.00 |
```

## What's next

- Phase 5 E: MimicRec integration (export + evaluation pipeline).
- Optional: `--output` flag for `mimicanno eval` to save report to file.
- Optional: per-edit-type breakdown in `RunMetrics`.
