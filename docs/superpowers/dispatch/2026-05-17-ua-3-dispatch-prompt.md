# U-A3 dispatch prompt (rev3 reissue, 2026-05-17)

Paste the block below verbatim into a fresh Claude Code session in `/misc/dl00/gayagaya/MimicAnno`. This revision incorporates master-spec rev3 (commit `eb389ba`) which **rewrote §2.4** to match the actual on-disk `_vlm_dumps/` layout: tree under `runs/<rs>/_vlm_dumps/<episode_id>/`, NOT flat `*.jsonl` files. Field list changed accordingly.

If a previous U-A3 sub-Claude already started against rev2, restart with this prompt; do not resume the old context (the spec is materially different now).

---

You are dispatched as **U-A3 sub-Claude** in the MimicAnno repo at `/misc/dl00/gayagaya/MimicAnno`. The commander session above brokered the master design; you do all spec / plan / impl work for U-A3.

You have **zero prior context**. Read this entire brief once, then proceed end-to-end: brainstorming (sub-spec) → writing-plans → test-driven implementation → tests passing → PR pushed. Report back with the deliverables listed at the end.

## 1. Your sub-project: U-A3 — VLM dumps viewer

Backend route `GET /api/runs/{canonical}/vlm_dumps.json` + RunViewer right-side panel "VLM" tab. Per **master spec rev3 §3.3 + §2.4** at `docs/superpowers/specs/2026-05-17-ua-dataset-processing-ui-design.md` (commit `eb389ba`, on `main`).

**Owned**: §2.4 backend endpoint + tree-walker reader; RunViewer right-panel "VLM" tab that lists planner + labeler calls and highlights the labeler call matching the currently selected segment (by phase/verb match — see derivation note below, NOT by raw ordinal).

**Out of scope**: editing dumps, re-running planner, anything outside the right panel. Do not touch `VideoPlayer.tsx` (U-A4's territory).

## 2. Hard constraints from master spec rev3

Master spec §2 is **frozen**. If your design needs §2 changes, **stop and escalate** — return `ESCALATE_CONTRACT_CHANGE`, do not push such a PR.

- §2.4 path is `/api/runs/{canonical}/vlm_dumps.json`. Disambiguation is **router registration order** — register BEFORE the catch-all `GET /api/runs/{name}/{artifact}` in `mimicanno/server/routes.py`.
- §2.4 `run_set` query param is **REQUIRED**. 400 if missing. 404 if (run_set, canonical) does not resolve.
- §2.0 run-set scoping: a "run-set" is a subdir of runs root containing `index.json`. Bare canonical dirs go in synthetic `__legacy__` bucket.
- On-disk layout (rev3 — verified against real `runs/so101_phase4_v5/_vlm_dumps/`):

  ```
  runs/<rs>/_vlm_dumps/<episode_id>/
  ├── _planner/
  │   └── call_NNN/
  │       ├── prompt.txt
  │       ├── response.txt   # JSON: {"objects":[...],"targets":[...],"tools":[...]}
  │       └── frame.png      # single keyframe
  └── s_NNN/                 # one segment, zero-padded ordinal
      └── attempt_M/         # M >= 1
          ├── prompt.txt
          ├── request.json   # rich context (task_text, allowed_labels, segment_id, robot_state_summary, last_reject_reason, ...)
          ├── response.txt   # JSON: {"phase","verb","object","target","vlm_confidence","evidence"}
          └── keyframe_NN.png  # NN = 00..03 typical (multiple frames per attempt)
  ```

- **Dumps keyed by `episode_id`** (not canonical). Re-annotate of the same episode overwrites earlier dumps within the run-set. Resolve canonical → `episode_id` via that canonical's `manifest.json` (`episode_id` field).

- §2.4 response shape (rev3):

  ```json
  {
    "canonical": "episode_000000__...",
    "run_set": "so101_phase4_v5",
    "episode_id": "episode_000000",
    "calls": [
      {
        "kind": "planner",
        "call_id": "call_001",
        "attempt": 1,
        "prompt": "...",
        "raw_output": "...",
        "parsed": {"objects": [...], "targets": [...], "tools": [...]},
        "failed": false,
        "frame_url": "/runs/<rs>/_vlm_dumps/<episode_id>/_planner/call_001/frame.png"
      },
      {
        "kind": "labeler",
        "call_id": "s_000__attempt_1",
        "segment_ordinal": 0,
        "attempt": 1,
        "prompt": "...",
        "request_json": {...},
        "raw_output": "...",
        "parsed": {"phase": "...", "verb": "...", "object": "...", "vlm_confidence": 0.87, ...},
        "failed": false,
        "keyframe_urls": ["/runs/.../keyframe_00.png", "/runs/.../keyframe_01.png"]
      }
    ]
  }
  ```

- Field invariants:
  - `kind`: `"planner" | "labeler"`. Planner only has `frame_url` (single string); labeler only has `keyframe_urls: list[str]` (one to multiple) and `request_json` (parsed `request.json`). Other fields not in scope for one `kind` are absent or `null`.
  - `segment_ordinal = int(s_NNN.split("_")[1])` (0-based, zero-padded ints in dir name). **Note: this is NOT `segment_id` post-smoother / post-edit**; the frontend MUST cross-reference selected segment by matching `parsed.phase` / `parsed.verb` / timing, not by `segment_ordinal == segment_id`.
  - `failed` for labeler: `true` iff a later `attempt_(M+1)/` exists for the same `s_NNN`. Backend sorts attempts numerically and sets `failed=true` on all but the highest-numbered.
  - `parsed` may be `null` if `response.txt` JSON is malformed (best-effort; do not fail the whole response on one bad file).
  - Sort order: planner calls by `call_id` numeric ascending, then labeler entries by `(segment_ordinal, attempt)` ascending.
  - Missing `_vlm_dumps/<episode_id>/` → return 200 with `calls: []`.

## 3. File ownership / collision boundary

- You own:
  - `frontend/src/components/RunViewer.tsx` — **right panel area only**. Add a side panel slot if one doesn't already exist; do NOT change VideoPlayer, timeline, segment table, or any other major component.
  - New component: `frontend/src/components/VlmPanel.tsx`.
  - New client: `frontend/src/lib/vlmClient.ts`.
  - Backend route module: a new file under `mimicanno/server/` (or a tightly-scoped section of `routes.py` registered BEFORE catch-all).
  - Backend reader module: e.g., `mimicanno/server/vlm_dumps_reader.py`.

- You do NOT own:
  - `VideoPlayer.tsx` canvas overlay → U-A4.
  - `/api/runs/{canonical}/masks/*` → U-A4.
  - `/api/datasets`, `/api/jobs` → U-A1 (already shipped).

- **Static asset serving for `frame.png` / `keyframe_NN.png`**: §3.3 says U-A3 chooses whether the existing run-artifact route already covers `_vlm_dumps/*.png` or a sibling static handler is needed. Inspect `mimicanno/server/routes.py` first; if `/runs/<rs>/<rest>` static handler already serves PNG bytes for paths under `_vlm_dumps/`, you're done. If not, add a tightly-scoped static handler (do NOT touch the existing catch-all behavior).

## 4. Environment + commands

- Backend test: `uv run pytest tests/server/ -v`
- Lint: `uv run mypy --strict mimicanno/`
- Frontend test: `cd frontend && npm test`
- Use uv for Python. MimicAnno `.venv` (uv) IS used for this work.
- Baseline (~340 passing + mypy strict clean — check before/after) must not regress.

## 5. Project rules (memory)

- **`sudo` ABSOLUTELY FORBIDDEN.** Installs via `uv` / `pipx` / `~/bin/` only.
- **autonomy window: CLOSED** (since 2026-05-16). Push branch + open PR OK; do NOT merge to main.
- Do not edit master spec §2 (rev3 is the frozen reference).
- Follow superpowers skills: brainstorming → writing-plans → TDD → verification-before-completion.

## 6. Git regime

- Branch base: `origin/main` at commit `eb389ba` (rev3 included).
- Branch name: `feat/ua-3-vlm-panel`
- Commit prefixes: `feat(ua-3):` / `test(ua-3):` / `docs(ua-3):`
- Push to: `origin`
- PR title prefix: `feat(ua-3):`
- **PR body MUST include**: `Touches master §2 contract: no` (rev3 already resolved the schema drift; if you genuinely need a further §2 change, escalate first — do not push with `yes`)
- Do not merge / force-push / amend pushed commits.

**Note**: a previous U-A3 attempt may already have pushed work to `origin/feat/ua-3-vlm-panel`. If you find existing commits there from prior sessions, you have two options: (a) rebase onto fresh `origin/main` at `eb389ba` and salvage anything useful, OR (b) restart on a new branch `feat/ua-3-vlm-panel-rev3` if the existing branch was built on the rev2 schema and would require deep rework. Report which option you chose.

## 7. Spec + plan paths

- Spec: `docs/superpowers/specs/2026-05-17-ua-3-vlm-panel-design.md` (master §8 template, cite master rev3 as parent)
- Plan: `docs/superpowers/plans/2026-05-17-ua-3-vlm-panel-plan.md`
- Both git-ignored: use `git add -f`.

## 8. Suggested TDD slices

1. Inspect real `_vlm_dumps/` tree (e.g., `runs/so101_phase4_v5/_vlm_dumps/episode_000000/`); confirm schema matches §2.4. Sub-spec note. ~0 tests.
2. Backend reader module: walk tree → return list of `Call` dicts per §2.4 schema. ~6 tests (planner happy, labeler with retries → `failed=true` on earlier, malformed JSON → `parsed=null`, missing tree → empty list, missing files inside tree, multi-keyframe labeler).
3. Backend route `GET /api/runs/{canonical}/vlm_dumps.json` (registered BEFORE catch-all). ~5 tests (happy, 400 missing run_set, 404 unknown canonical, 200 with empty calls for legacy, run_set=__legacy__).
4. PNG static serving check: spot-test that `GET /runs/<rs>/_vlm_dumps/<episode_id>/_planner/call_001/frame.png` returns 200 (covered by existing handler? if not, add a tightly-scoped one). ~2 tests.
5. Frontend `vlmClient.ts`. ~2 vitest cases.
6. `VlmPanel.tsx` (list + filter by kind, highlight on segment selection match, expand/collapse prompt, render thumbnail). ~6 vitest cases.
7. RunViewer integration — wire VlmPanel into right slot, pass current segment context. ~2 cases.

## 9. Final deliverables (report back to commander)

Return ONE message:

- **Status**: `DONE` / `DONE_WITH_CONCERNS` / `BLOCKED` / `NEEDS_CONTEXT` / `ESCALATE_CONTRACT_CHANGE`
- Spec path + plan path
- Branch name + final commit SHA + PR URL (or "branch pushed at <sha>, manual PR")
- Test counts: backend new + total, frontend new vitest + total, mypy strict status
- Files touched
- Branch strategy (salvage rebase vs new branch — §6 note)
- §2 contract changes proposed: `none` (expected) or full diff (escalate before pushing)
- Open risks (e.g., labeler highlight heuristic when phase/verb doesn't uniquely match, PNG fetch performance, segment ordinal vs id drift after edits)

Start now.
