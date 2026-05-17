# U-A3 — VLM dumps viewer (implementation plan)

Date: 2026-05-17
Spec: `docs/superpowers/specs/2026-05-17-ua-3-vlm-panel-design.md`
Branch: `feat/ua-3-vlm-panel` (worktree at `.claude/worktrees/feat+ua-3-vlm-panel`)

## Slice order (TDD)

Each slice = write failing tests → minimum impl → green → commit.

### S1. Backend reader (no route yet)

Files: `mimicanno/server/vlm_dumps.py` + `tests/server/test_vlm_dumps.py`.

1. Fixture builder utility in test file: `build_vlm_dump_tree(tmp_path, run_set, episode_id, planner=[...], segments={"s_001": [{"attempt":1,"response":"..."}], ...})`. Writes the actual directory tree.
2. T1 `read_vlm_dumps` empty dir → `[]`.
3. T2 happy path: 1 planner + 2 segments → 3 calls, correct kind / segment_id / phase / parsed.
4. T3 multiple attempts → highest attempt_M wins (others ignored).
5. T4 malformed JSON in segment response.txt → `parsed=None, failed=True`.
6. T5 missing response.txt in segment → `failed=True, raw_output=""`.
7. T6 `resolve_episode_id` happy.
8. T7 `resolve_episode_id` miss → `None`.
9. Implement `VlmCall` dataclass + the two helpers. Use `pathlib.Path`, `json.loads`, `re` for attempt parsing.

Commit: `feat(ua-3): vlm_dumps reader module + tests`

### S2. Route registration

Files: `mimicanno/server/routes.py` (edit) + extend `tests/server/test_vlm_dumps.py` with route tests.

1. T8 route 400 when `run_set` missing.
2. T9 route 404 when canonical not in index.json for that run-set.
3. T10 route 200 happy path: shape match (canonical, run_set, episode_id, calls).
4. T11 route 200 with no `_vlm_dumps/<episode_id>/` → `calls=[]`.
5. T12 registration order: `/api/runs/<known canonical>/vlm_dumps.json?run_set=<rs>` returns VLM dumps shape, NOT a `404 artifact_not_found` (which would mean catch-all matched first).
6. Implement: add `@router.get("/api/runs/{canonical}/vlm_dumps.json")` BEFORE the catch-all block at line ~588. Use explicit `run_set: str | None = Query(None)` (not the `get_effective_root` dep) so we can raise 400 instead of defaulting to parent_root.

Commit: `feat(ua-3): GET /api/runs/{canonical}/vlm_dumps.json route`

### S3. Frontend client + panel

Files:
- `frontend/src/lib/vlmClient.ts` (new)
- `frontend/src/components/VlmPanel.tsx` (new)
- `frontend/src/components/VlmPanel.module.css` (new, scoped CSS — if project uses CSS Modules; otherwise inline / Tailwind matching the repo's existing pattern)
- `frontend/src/components/__tests__/VlmPanel.test.tsx` (new)

1. vitest cases for `vlmClient.fetchVlmDumps` (2): happy, throws on 500.
2. vitest cases for `VlmPanel` (7 per sub-spec §4).
3. Implement client (small wrapper around `fetch`).
4. Implement component:
   - `useEffect` on `[canonical, runSet]` → fetch.
   - Local state: loading / error / data.
   - Render list with planner header section + segment rows.
   - Expanded state in `useState<string | null>(null)` keyed by `call_id`.
   - CSS classes for `is-selected` / `is-failed`.

Commit: `feat(ua-3): VlmPanel component + vlmClient`

### S4. RunViewer integration

Files: `frontend/src/components/RunViewer.tsx` (edit) + `frontend/src/components/__tests__/RunViewer.vlm.test.tsx` (new).

1. Read RunViewer first; locate existing right-side panel area (if any) or add one minimally.
2. vitest case: VlmPanel mounts when canonical + runSet present.
3. vitest case: selecting a segment in SegmentTable flows through to VlmPanel `selectedSegmentId` prop (use a shared selection signal — read SegmentTable first to find it).
4. Wire prop. Don't refactor existing logic.

Commit: `feat(ua-3): wire VlmPanel into RunViewer right slot`

### S5. Verification + push

1. `uv run pytest tests/server/ -v` → expect prior ≥252 still passing + ~12 new.
2. `uv run mypy --strict mimicanno/` → clean.
3. `cd frontend && npm test` → all vitest green (~11 new).
4. `git push -u origin feat/ua-3-vlm-panel`.
5. `gh pr create` with body noting "Touches master §2 contract: yes (rev3, commander-approved, see commit 3f484ad)".

Commit (already implicit per slice). No squash.

## Notes on edge cases (from sub-spec §5)

- `parsed: object | None` — typed as `Any` at FastAPI boundary to allow JSON dict/list/scalar. Use `pydantic.BaseModel` or a `TypedDict` if needed.
- attempt parsing: use `int(name.removeprefix("attempt_"))` (Python 3.9+). Skip dirs that don't match.
- `index.json` could conceivably have multiple entries with same `episode_id` but different canonicals (re-runs). `_vlm_dumps/<episode_id>/` is shared — that's actually fine for read-only; all canonicals for the same source episode see the same dumps. This is acceptable behavior per master §2.4 rev3.

## Out of plan

- Image serving endpoint (deferred).
- `ms` / `model_variant` enrichment (writer-side change).
- Mode B / non-LeRobot inputs.
