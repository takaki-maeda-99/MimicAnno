# U-A3 dispatch prompt (zero-context brief)

Paste the block below verbatim into a fresh Claude Code session in `/misc/dl00/gayagaya/MimicAnno`. Do not edit — the prompt is self-contained.

---

You are dispatched as **U-A3 sub-Claude** in the MimicAnno repo at `/misc/dl00/gayagaya/MimicAnno`. The commander session above brokered the master design; you do all spec / plan / impl work for U-A3.

You have **zero prior context**. Read this entire brief once, then proceed end-to-end: brainstorming (sub-spec) → writing-plans → test-driven implementation → tests passing → PR pushed. Report back with the deliverables listed at the end.

## 1. Your sub-project: U-A3 — VLM dumps viewer

Backend route `GET /api/runs/{canonical}/vlm_dumps.json` + RunViewer right-side panel "VLM" tab. Per **master spec §3.3 + §2.4** at `docs/superpowers/specs/2026-05-17-ua-dataset-processing-ui-design.md` (rev2, commit `1ba138d`, on `main`).

**Owned**: §2.4 backend endpoint; RunViewer right-panel "VLM" tab that lists planner calls and highlights the call matching the currently selected segment.

**Out of scope**: editing dumps, re-running planner, anything outside the right panel. Do not touch VideoPlayer (that's U-A4's territory).

## 2. Hard constraints from master spec

Master spec §2 is **frozen**. If your design needs §2 changes, **stop and escalate to commander** — return `ESCALATE_CONTRACT_CHANGE`, do not push such a PR.

- §2.4 path is `/api/runs/{canonical}/vlm_dumps.json` (suffix is for readability; **disambiguation is purely router registration order** — register BEFORE the catch-all `GET /api/runs/{name}/{artifact}` at `mimicanno/server/routes.py`).
- §2.4 `run_set` query param is **REQUIRED**. 400 if missing. 404 if (run_set, canonical) does not resolve.
- §2.0 run-set scoping: a "run-set" is a subdir of runs root containing `index.json`. Bare canonical dirs go in synthetic `__legacy__` bucket.
- §2.4 response shape: `{canonical, run_set, calls: [{call_id, phase, segment_id, prompt, raw_output, parsed, failed, ms, model_variant}]}`. Missing `_vlm_dumps/` dir → empty `calls`.
- Reads `runs/<rs>/<canonical>/_vlm_dumps/*.jsonl`.

## 3. File ownership / collision boundary

- You own: `frontend/src/components/RunViewer.tsx` **right panel area only**, new component for the VLM tab, new client lib.
- You do NOT own: `frontend/src/components/VideoPlayer.tsx` (U-A4), backend `/api/jobs` or `/api/datasets` (U-A1), `/api/runs/{canonical}/masks` (U-A4).
- backend additions go in a new file under `mimicanno/server/` or a tightly-scoped section of `routes.py` (register before catch-all).

## 4. Existing code map

- `mimicanno/server/routes.py` — existing GET / PATCH routes. Catch-all is at the tail; your new route MUST be registered before it.
- `mimicanno/server/app.py` — FastAPI app. No CORS change needed (your route is GET, already in allow_methods).
- `mimicanno/runindex.py` / `mimicanno/server/run_repo.py` — run-set + canonical resolution helpers; reuse for the `(run_set, canonical) → path` lookup.
- `runs/so101_phase4_v5/episode_000000__*/_vlm_dumps/` — real example of `_vlm_dumps/*.jsonl` schema; inspect to confirm field names match §2.4 contract. If field names disagree (e.g., the JSONL uses different keys than §2.4 lists), this is a §2 contract drift → escalate, do not silently rename.
- `tests/server/conftest.py` — frozen fixtures (`tmp_runs_root_loadable`, etc.). Reuse.
- `frontend/src/components/RunViewer.tsx` — existing layout; add a right-panel slot if not present.
- `frontend/src/components/SegmentTable.tsx` — likely where segment selection state lives. Read it to find the selection signal you'll listen to.

## 5. Environment + commands

- Backend test: `uv run pytest tests/server/ -v`
- Lint: `uv run mypy --strict mimicanno/`
- Frontend test: `cd frontend && npm test`
- Use uv for all Python ops. MimicAnno `.venv` (uv) is USED for this work.
- Don't break baseline (≥ 252 passing + mypy strict clean).

## 6. Project rules (memory)

- **`sudo` ABSOLUTELY FORBIDDEN.** No exceptions. Installs via `uv` / `pipx` / `~/bin/` only.
- **autonomy window: CLOSED** (since 2026-05-16). You may push your branch and open a PR but **do not merge** to main. Commander/user merges.
- Do not edit master spec §2. Escalate via the final report.
- Follow superpowers skills: brainstorming → writing-plans → test-driven-development → verification-before-completion.

## 7. Git regime

- Branch base: `origin/main` (current tip, master spec rev2 is in ancestry)
- Branch name: `feat/ua-3-vlm-panel`
- Commit prefixes: `feat(ua-3):` / `test(ua-3):` / `docs(ua-3):`
- Push to: `origin`
- PR title prefix: `feat(ua-3):`
- **PR body MUST include**: `Touches master §2 contract: no` (or `yes` + diff proposal if you must — escalate first)
- Do not merge. Do not force-push. Do not amend pushed commits.

## 8. Spec + plan paths

- Spec: `docs/superpowers/specs/2026-05-17-ua-3-vlm-panel-design.md` (master §8 template, cite master as parent)
- Plan: `docs/superpowers/plans/2026-05-17-ua-3-vlm-panel-plan.md`
- Both paths are git-ignored: use `git add -f`.

## 9. Suggested TDD slices

1. Inspect `_vlm_dumps/*.jsonl` schema against §2.4 contract; report drift if any (do not silently adapt). ~0 tests, design step.
2. Backend reader: `_vlm_dumps/` → list of `Call` dataclasses. ~4 tests (happy, missing dir, malformed line, multi-file).
3. Route `GET /api/runs/{canonical}/vlm_dumps.json` (registered before catch-all). ~5 tests (happy, 400 missing run_set, 404 unknown, __legacy__ run_set, empty calls).
4. Frontend `vlmClient.ts` fetcher. ~2 vitest cases.
5. Frontend `VlmPanel.tsx` component (list + highlight on segment selection). ~5 vitest cases (render, segment match highlight, failed-call style, empty state, prompt expand toggle).
6. RunViewer integration — wire VlmPanel into right side slot. ~2 cases.

## 10. Final deliverables (report back to commander)

Return ONE message containing:

- **Status**: `DONE` / `DONE_WITH_CONCERNS` / `BLOCKED` / `NEEDS_CONTEXT` / `ESCALATE_CONTRACT_CHANGE`
- Spec path + plan path
- Branch name + final commit SHA + PR URL (or "PR not yet created, branch pushed at <sha>")
- Test counts: backend new + total, frontend new vitest, mypy --strict status
- Files touched
- §2 contract changes proposed: `none` or full diff proposal
- Open risks / follow-ups

Do not guess on ambiguity — return `NEEDS_CONTEXT` with the exact question. If `_vlm_dumps/*.jsonl` field names differ from §2.4 contract, return `ESCALATE_CONTRACT_CHANGE` with the proposed diff.

Start now.
