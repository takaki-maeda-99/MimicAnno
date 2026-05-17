# U-A4 dispatch prompt (zero-context brief)

Paste the block below verbatim into a fresh Claude Code session in `/misc/dl00/gayagaya/MimicAnno`.

---

You are dispatched as **U-A4 sub-Claude** in the MimicAnno repo at `/misc/dl00/gayagaya/MimicAnno`. The commander session above brokered the master design; you do all spec / plan / impl work for U-A4.

You have **zero prior context**. Read this entire brief, then proceed end-to-end: brainstorming (sub-spec) → writing-plans → test-driven implementation → tests passing → PR pushed. Report deliverables.

## 1. Your sub-project: U-A4 — SAM3 mask overlay

Backend routes `GET /api/runs/{canonical}/masks/{frame}.png` + `GET /api/runs/{canonical}/masks/meta.json` + canvas overlay component inside VideoPlayer. Per **master spec §3.4 + §2.5** at `docs/superpowers/specs/2026-05-17-ua-dataset-processing-ui-design.md` (rev2, commit `1ba138d`, on `main`).

**Owned**: §2.5 backend endpoints; canvas overlay child of `VideoPlayer.tsx` that renders the current frame's tracks (per-track color + alpha + toggle).

**Out of scope**: editing masks, RunViewer right-panel (U-A3 owns that), backend /api/jobs/datasets (U-A1).

## 2. Hard constraints from master spec

Master spec §2 is **frozen**. If your design needs §2 changes, **stop and escalate** — return `ESCALATE_CONTRACT_CHANGE`, do not push.

- §2.5 paths: `/api/runs/{canonical}/masks/{frame}.png` and `/api/runs/{canonical}/masks/meta.json`. Suffixes are readability only; **disambiguation is router registration order** — register BEFORE the catch-all in `routes.py`.
- §2.5 `run_set` query param **REQUIRED**. 400 if missing.
- §2.5 status codes: 200 PNG, 204 frame in range but no objects, 400 missing/invalid params, 404 (run_set, canonical) not resolvable or no `tracks.json`.
- §2.0 run-set scoping rules apply (run-set = subdir with `index.json`, bare canonicals → `__legacy__`).
- §3.4 leaves the implementation choice **on-the-fly rasterization vs pre-bake** to your sub-spec. Either is fine. If pre-bake, sidecar lives at `runs/<rs>/<canonical>/_masks/<frame>.png` and you amend the annotate pipeline to write it; the HTTP contract is unchanged.
- §2.5 `meta.json` shape: `{canonical, run_set, frame_count, tracks: [{track_id, label, color, first_frame, last_frame}]}`.
- §2.5 PNG: RGBA, alpha = mask presence × per-track color.

## 3. File ownership / collision boundary

- You own: `frontend/src/components/VideoPlayer.tsx` **canvas overlay child only**, new mask overlay component, new client lib.
- You do NOT own: `RunViewer.tsx` right panel (U-A3), `/api/runs/{canonical}/vlm_dumps.json` (U-A3), `/api/datasets`/`/api/jobs` (U-A1).
- Backend additions go in a tightly-scoped section of `routes.py` (registered before catch-all) or a new file under `mimicanno/server/`.

## 4. Existing code map

- `mimicanno/server/routes.py` — existing GET / PATCH routes. Catch-all at the tail; register new routes BEFORE it.
- `mimicanno/server/app.py` — no CORS change needed (your routes are GET).
- `mimicanno/runindex.py` / `mimicanno/server/run_repo.py` — `(run_set, canonical) → path` resolution helpers.
- `runs/so101_phase4_v5/episode_000000__*/tracks.json` — real example of `tracks.json` schema (RLE? polygons? per-frame masks?). Inspect first — if it does not contain the data needed to render masks per frame (e.g., only bbox no mask), this is a §2 contract drift or a missing data-prep step → escalate, do not silently change contract.
- `frontend/src/components/VideoPlayer.tsx` — existing video element + time cursor.
- `tests/server/conftest.py` — frozen fixtures incl. `tracks.json`. Reuse.

## 5. Project rule: SAM3 grounding camera

**Critical for U-A4 only**: SAM3 grounding uses **external/overhead camera**, NOT wrist camera. If your overlay component pulls the wrong camera stream from RunViewer, masks will appear misaligned with video. Memory: `feedback_sam3_use_external_cam`. Confirm which video stream RunViewer is rendering before drawing the overlay on top.

## 6. Environment + commands

- Backend test: `uv run pytest tests/server/ -v`
- Lint: `uv run mypy --strict mimicanno/`
- Frontend test: `cd frontend && npm test`
- Use uv for Python. MimicAnno `.venv` (uv) IS used here.
- Baseline (≥ 252 passing + mypy strict clean) must not regress.

## 7. Project rules (memory)

- **`sudo` ABSOLUTELY FORBIDDEN.** Installs via `uv` / `pipx` / `~/bin/` only.
- **autonomy window: CLOSED** (2026-05-16). Push branch + open PR OK; do NOT merge to main.
- Do not edit master spec §2.
- Follow superpowers skills: brainstorming → writing-plans → TDD → verification-before-completion.

## 8. Git regime

- Branch base: `origin/main` (current tip)
- Branch name: `feat/ua-4-mask-overlay`
- Commit prefixes: `feat(ua-4):` / `test(ua-4):` / `docs(ua-4):`
- Push to: `origin`
- PR title prefix: `feat(ua-4):`
- **PR body MUST include**: `Touches master §2 contract: no` (or `yes` + diff proposal — escalate first)
- Do not merge / force-push / amend pushed commits.

## 9. Spec + plan paths

- Spec: `docs/superpowers/specs/2026-05-17-ua-4-mask-overlay-design.md` (master §8 template)
- Plan: `docs/superpowers/plans/2026-05-17-ua-4-mask-overlay-plan.md`
- Both git-ignored: use `git add -f`.

## 10. Suggested TDD slices

1. Inspect `tracks.json` schema; decide rasterize-on-fly vs pre-bake; report drift if any. Design step.
2. Backend mask rasterizer (or sidecar reader). ~5 tests (happy frame, frame out of range, no objects → 204, multiple tracks, malformed tracks.json).
3. Route `GET /api/runs/{canonical}/masks/{frame}.png` (registered before catch-all). ~5 tests.
4. Route `GET /api/runs/{canonical}/masks/meta.json`. ~3 tests.
5. (If pre-bake) annotate-pipeline patch to emit `_masks/<frame>.png`. ~3 tests.
6. Frontend `masksClient.ts`. ~2 vitest cases.
7. `MaskOverlay.tsx` canvas component (per-track color, alpha control, toggle list). ~5 vitest cases.
8. VideoPlayer integration (overlay child mounts, time cursor → frame index fetch). ~2 cases.

## 11. Final deliverables (report back to commander)

Return ONE message:

- **Status**: `DONE` / `DONE_WITH_CONCERNS` / `BLOCKED` / `NEEDS_CONTEXT` / `ESCALATE_CONTRACT_CHANGE`
- Spec path + plan path
- Branch name + final commit SHA + PR URL
- Test counts: backend new + total, frontend new vitest, mypy strict status
- Implementation choice: rasterize-on-fly OR pre-bake (+ rationale)
- Files touched
- §2 contract changes proposed: `none` or full diff
- Open risks (e.g., performance of per-frame PNG fetch at 15 fps cursor scrubbing)

Do not guess on `tracks.json` schema. If it lacks per-frame mask data, escalate — do not silently add a contract field or downgrade the overlay to bbox-only.

Start now.
