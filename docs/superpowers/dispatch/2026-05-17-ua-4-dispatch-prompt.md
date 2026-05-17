# U-A4 dispatch prompt (rev3 reissue, 2026-05-17)

Paste the block below verbatim into a fresh Claude Code session in `/misc/dl00/gayagaya/MimicAnno`. This revision incorporates master-spec rev3 (commit `eb389ba`) which **mandates pre-bake** for the mask overlay sidecar — the rev2 "on-the-fly OR pre-bake" choice is gone, since `tracks.json` lacks the RLE/polygon data on-the-fly would require.

If a previous U-A4 sub-Claude already ESCALATED on rev2, restart with this prompt; do not resume the old context.

---

You are dispatched as **U-A4 sub-Claude** in the MimicAnno repo at `/misc/dl00/gayagaya/MimicAnno`. The commander session above brokered the master design; you do all spec / plan / impl work for U-A4.

You have **zero prior context**. Read this entire brief, then proceed end-to-end: brainstorming (sub-spec) → writing-plans → test-driven implementation → tests passing → PR pushed. Report deliverables.

## 1. Your sub-project: U-A4 — SAM3 mask overlay (pre-bake)

Two backend routes + a canvas overlay component inside `VideoPlayer.tsx` + an amendment to the annotate pipeline that pre-bakes mask PNGs as a sidecar. Per **master spec rev3 §3.4 + §2.5** at `docs/superpowers/specs/2026-05-17-ua-dataset-processing-ui-design.md` (commit `eb389ba`, on `main`).

**Owned**:

- Backend: `GET /api/runs/{canonical}/masks/{frame}.png` + `GET /api/runs/{canonical}/masks/meta.json` (both register **before** the catch-all in `mimicanno/server/routes.py`).
- Pipeline amendment: persist `MaskCache.by_frame` (populated in `mimicanno/object_tracker/propagator.py`, currently transient and consumed by `mimicanno/pipeline.py:881-998` `vlm_labeler`) as `<canonical>/_masks/<frame>.png` (RGBA, alpha = mask presence × per-track palette color). Write site: post-`mask_cache` collection, pre-Stage 3 return.
- Frontend: canvas overlay child of `VideoPlayer.tsx`, per-track color legend, per-track toggle, alpha control.

**Out of scope**:

- On-the-fly rasterization (rev3 dropped this option — `tracks.json` only has bbox/score, no polygon/RLE).
- Editing masks.
- Backfill of legacy runs without `_masks/` (separate `U-A4-followup-backfill` TODO; pre-rev3 runs degrade gracefully via 204).
- RunViewer right-panel (U-A3 territory) or backend `/api/jobs`, `/api/datasets`, `/api/runs/{canonical}/vlm_dumps.json` (U-A1 / U-A3).

## 2. Hard constraints from master spec rev3

Master spec §2 is **frozen**. If your design needs §2 changes, **stop and escalate** — return `ESCALATE_CONTRACT_CHANGE`, do not push.

- §2.0 run-set scoping rules apply. `__legacy__` bucket for bare canonicals.
- §2.0.1 CORS: no new methods needed for U-A4 (your routes are GET; U-A1 already added POST/DELETE).
- §2.5 routes use **router registration order** for disambiguation (suffixes `.png` / `.json` are readability only).
- §2.5 `run_set` query param is **REQUIRED** on both routes. 400 if missing.
- §2.5 status codes:
  - **404** = path-resolution error only (unknown `run_set`, unknown canonical).
  - **204** = valid query but no overlay content. Covers BOTH (a) run dir has no `_masks/` sidecar (legacy run), AND (b) frame is in range but has no tracked objects.
  - **200** image/png on success.
  - **400** on missing `run_set` or non-numeric `frame`.
- §2.5 `meta.json` response: `{canonical, run_set, frame_count, tracks: [{track_id, label, color, first_frame, last_frame}]}`. Legacy runs (no `_masks/`) return 200 with `frame_count: 0, tracks: []` — frontend branches on that to disable the overlay control.
- §3.4 mandates **pre-bake**: writes go through the existing atomic-publish flow at `mimicanno/publish.py` (write into scratch / temp, then atomic move into the published rundir). Never stream PNGs into the live run dir.
- Sidecar layout: `runs/<rs>/<canonical>/_masks/<frame>.png` (per-canonical, NOT shared like `_vlm_dumps/`).
- `tracks.json` schema is **unchanged**. No new schema fields on disk other than `_masks/<frame>.png` files.

## 3. File ownership / collision boundary

- You own:
  - `frontend/src/components/VideoPlayer.tsx` — **canvas overlay child only**. Do not change the video element or time cursor logic beyond exposing a slot.
  - New file: `frontend/src/components/MaskOverlay.tsx` (or similar) — the overlay component itself.
  - New file: `frontend/src/lib/masksClient.ts` — fetcher.
  - Backend mask routes (new module under `mimicanno/server/`, or a tightly-scoped section of `routes.py` registered **before** the catch-all).
  - `mimicanno/pipeline.py:881-998` — extend the existing mask_cache consumption to also call a new `write_masks_sidecar(...)` helper. **Read the surrounding code carefully** — the pipeline has a defined Stage 1/2/3 structure and an atomic-publish flow at the end; do not break either.
  - `mimicanno/publish.py` — add a function that accepts mask_cache + canonical and writes `_masks/<frame>.png` into the temp/scratch dir before the atomic move. If `publish.py` doesn't have an obvious extension point, escalate before inventing one.
  - New helper module if needed: `mimicanno/masks/` (single-file or small package — your judgment).

- You do NOT own:
  - `RunViewer.tsx` right panel area → U-A3.
  - `/api/runs/{canonical}/vlm_dumps.json` → U-A3.
  - `/api/datasets`, `/api/jobs` → already-shipped U-A1 (don't touch unless coordinating).

## 4. Project rule: SAM3 grounding camera

**Critical for U-A4**: SAM3 grounding uses the **external/overhead camera**, NOT the wrist camera. `tracks.json` is generated against whichever camera is configured (see robot YAML). Your overlay must draw on the same video stream RunViewer is rendering, OR refuse to draw if cameras mismatch. Read the camera identifier from `manifest.json` or `tracks.json` and confirm it matches the video being shown. Memory: `feedback_sam3_use_external_cam`.

## 5. Existing code map

- `mimicanno/server/routes.py` — existing GET / PATCH routes. Catch-all at the tail; new routes go before it.
- `mimicanno/server/app.py` — FastAPI app. No CORS change needed.
- `mimicanno/runindex.py` / `mimicanno/server/runs_repo.py` — `(run_set, canonical) → path` resolution helpers.
- `mimicanno/pipeline.py:881-998` — vlm_labeler section that already iterates over `mask_cache.by_frame`. This is where you add the sidecar write (just before the cache goes out of scope).
- `mimicanno/object_tracker/propagator.py` (look for the `MaskCache` class and `mask_image_size_px` flag — that's the path that populates per-frame RLE).
- `mimicanno/publish.py` — atomic-publish flow. The scratch dir → final rundir move pattern.
- `runs/so101_phase4_v5/episode_000000__e35061106394/tracks.json` — real example. Inspect the `tracks` and `samples` arrays for what's available to drive `meta.json`'s `tracks: [{track_id, label, color, first_frame, last_frame}]` derivation.
- `frontend/src/components/VideoPlayer.tsx` — existing video element + time cursor.
- `tests/server/conftest.py` — frozen fixtures (`tmp_runs_root_loadable`, etc.). Reuse. Add a fixture for `_masks/` if needed.

## 6. Environment + commands

- Backend test: `uv run pytest tests/server/ -v`
- Lint: `uv run mypy --strict mimicanno/`
- Frontend test: `cd frontend && npm test`
- Use uv for Python. MimicAnno `.venv` (uv) IS used here.
- Baseline (~340 passing + mypy strict clean — check current count before/after) must not regress.

## 7. Project rules (memory)

- **`sudo` ABSOLUTELY FORBIDDEN.** Installs via `uv` / `pipx` / `~/bin/` only.
- **autonomy window: CLOSED** (since 2026-05-16). Push branch + open PR OK; do NOT merge to main.
- Do not edit master spec §2 (rev3 is the frozen reference).
- Follow superpowers skills: brainstorming → writing-plans → TDD → verification-before-completion.

## 8. Git regime

- Branch base: `origin/main` at commit `eb389ba` (master spec rev3 included).
- Branch name: `feat/ua-4-mask-overlay`
- Commit prefixes: `feat(ua-4):` / `test(ua-4):` / `docs(ua-4):`
- Push to: `origin`
- PR title prefix: `feat(ua-4):`
- **PR body MUST include**: `Touches master §2 contract: no` (rev3 already resolves the schema drift; if you genuinely need a further §2 change, escalate first — do not push with `yes`)
- Do not merge / force-push / amend pushed commits.

## 9. Spec + plan paths

- Spec: `docs/superpowers/specs/2026-05-17-ua-4-mask-overlay-design.md` (master §8 template, cite master rev3 as parent)
- Plan: `docs/superpowers/plans/2026-05-17-ua-4-mask-overlay-plan.md`
- Both git-ignored: use `git add -f`.

## 10. Suggested TDD slices

1. Read `tracks.json` schema in real data and document `meta.json` derivation (track id, label, color assignment policy, first_frame/last_frame computation). Update sub-spec.
2. Confirm `MaskCache.by_frame` payload shape in `propagator.py` and `pipeline.py:881-998` consumption. Spot-check that per-frame RLE/bitmap is in scope at the write site you choose. If anything is missing, escalate — do not introduce a new propagator pass.
3. `write_masks_sidecar(...)` helper + atomic-publish integration. ~4 tests (happy, empty mask_cache, write into temp then move, palette correctness).
4. Pipeline integration call. ~2 tests (integration-style with a tiny synthetic mask_cache).
5. Backend `GET /api/runs/{canonical}/masks/{frame}.png` (registered before catch-all). ~5 tests (200 happy, 204 missing _masks/, 204 empty frame, 400 bad frame, 404 unknown canonical, 400 missing run_set).
6. Backend `GET /api/runs/{canonical}/masks/meta.json`. ~4 tests (200 happy, 200 legacy empty, 400 missing run_set, 404 unknown).
7. Frontend `masksClient.ts`. ~2 vitest cases.
8. `MaskOverlay.tsx` canvas (per-track color, alpha toggle, per-track visibility). ~5 vitest cases.
9. VideoPlayer integration — overlay child mounts, time cursor → frame index fetch with reasonable debounce. ~2 cases.

## 11. Final deliverables (report back to commander)

Return ONE message:

- **Status**: `DONE` / `DONE_WITH_CONCERNS` / `BLOCKED` / `NEEDS_CONTEXT` / `ESCALATE_CONTRACT_CHANGE`
- Spec path + plan path
- Branch name + final commit SHA + PR URL (or "branch pushed at <sha>, manual PR")
- Test counts: backend new + total, frontend new vitest + total, mypy strict status
- Files touched
- §2 contract changes proposed: `none` (expected — rev3 already corrected the drift) or full diff (escalate before pushing)
- Open risks (e.g., per-frame PNG fetch latency during scrub — debounce or pre-fetch needed? legacy-run UX without backfill? camera-mismatch handling?)

Start now.
