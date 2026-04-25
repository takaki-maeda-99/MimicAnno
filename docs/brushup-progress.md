# MimicAno design.md brush-up progress

Resume with `/superpowers:brainstorming`. Mode: **brush-up of `docs/design.md`** (option A from initial scoping).

Visual Companion: skipped (mostly text/algorithm questions).

## Decisions confirmed so far

### Phase decomposition: B' (viewer-first, object-tracking-later, provisional-VLM-middle)

```
Phase 1: signals + read-only timeline viewer
Phase 2: provisional VLM labeling (no object_state)
Phase 3: SAM3 + integrated boundary score + relabel with object_state
Phase 4: smoothing / Viterbi
Phase 5: edit UI / export / evaluation
```

Phase 2 positioning: **provisional labeler**, not final quality. Stamp output with:
```python
label_source = "vlm_robot_state_only"
object_state_unavailable = True
reviewed = False
```
Phase 2's purpose is to lock down the VLM JSON schema, allowed-labels enforcement, and timeline-band rendering — not to evaluate VLM intelligence.

Phase 3 re-labels with `label_source = "vlm_with_object_state"`.

### GPT review filter (independent assessment, not blanket adoption)

**Adopt as-is:**
- Schema additions: `episode_id`, `segment_id`, `label_source`, `reviewed`, `reviewer_id`, `label_version`, `config_hash`, `model_versions`, `boundary_source: list[str]`, `failure_flags: list[str]`, `object_track_ids`
- SAM3 prompt generation takes **task name + initial frame** (not task name alone — "it" / "the object" can't be resolved without visual context)
- SAM3 failure fallback: degrade to robot-state-only with `object_state_unavailable=true`
- Boundary detection reformulated as **integrated weighted score** (Step1 signals + Step2 object signals combined), not "Step2 refines Step1"
- Performance assumptions made explicit (fps, resolution, episode length, model size)

**Adopt with narrowed scope:**
- Additional boundary candidates: only `object motion start/stop`, `gripper-object distance threshold crossing`, `action norm change`. Drop/defer `camera embedding change point` (new model dependency).
- Forbidden transitions → penalties: keep hard rules in Phase 1, promote to Viterbi/penalty in Phase 4 (smoothing).
- Confidence decomposition: 3 levels only — `vlm_confidence`, `boundary_confidence`, `overall_confidence`. Add tracking/smoothing confidences only when needed.
- evaluation module: defer to Phase 5. `human_edit_time` requires UI logging.

**Deferred / decide after seeing real data:**
- Expanded label list (`search_object`, `push_object`, `insert_object`, ...): "configurable per task type" is already the right answer; don't expand the core default until we see actual datasets.
- Failure subcategories (`failed_grasp`, `lost_object`, ...): same — see real failure data first.

**Structural reframe:**
- `failure_recovery` is **not a phase** — it's a `failure_flags: list[str]` attribute on a segment whose `phase` is the underlying activity (e.g., `phase="grasp_object", failure_flags=["failed_grasp"]`). This keeps normal-vs-failed trajectories separable downstream.

## Status (2026-04-25, autonomous mode — spec ready for user review)

- Q3 answered: **B-1''** (CLI writes self-contained run directory at `<repo>/runs/<canonical_name>/` where `canonical_name = <episode_id>__<config_hash[:8]>`; React/Vite reads `manifest.json`; Vite dev server mounts `../runs/` at `/runs/*`; no backend in Phase 1).
- Codex `gpt-5.4` reviews completed across **7 rounds**:
  - R1 (Q3 decision): 5 fixes — external runs root, manifest provenance, `runs/index.json`, typed `artifacts[]`, copy-default with symlink opt-in.
  - R2 (full spec): 12 fixes — per-edge `BoundaryRef`, object track ID contract, Phase-1 clip bracketing algo, EEF rule for joint-only robots, `signals.json` time alignment, `index.json` file lock, POSIX-only atomic rename, per-artifact schema versioning + `compat`, reserved phases `unlabeled`/`unknown`, perf compute-vs-I/O split.
  - R3: 4 fixes — `compat` scope (in-run only), `?run=` disambiguation table, stale `.bak` scavenger, dropped unreachable abort path.
  - R4: 2 fixes — canonical_name introduced; §4.1 + §6.5 path consistency.
  - R5: 1 fix — propagated canonical_name to remaining unsuffixed reference (line 65, §3 deliverables).
  - R6: 1 fix — relative-URL resolution rule (`manifest_url` against index dir, `artifact.url` against manifest dir).
  - R7: 1 fix — Phase 5 endpoint name unification (`/api/runs/index.json`).
  - Final verdict: **"ready for user review"**.
- Spec at `docs/superpowers/specs/2026-04-25-mimicano-design-brushup.md`. Pending: user review gate → writing-plans transition.

## Original Q3 description (kept for reference)

**Q3. Phase 1 viewer の実装パス**

Read-only viewer scope (already agreed): video player + timeline + playhead + boundary markers (colored by source) + gripper waveform + EEF velocity waveform + click-to-seek + JSON export. No edit affordances.

Three implementation paths:

- **A. Throwaway 軽量ツール** (gradio / streamlit): fastest to ship, but Phase 5 = total rewrite, breaks design.md's `frontend/` (React) commitment.
- **B. React frontend from the start** (matches design.md): no backend in Phase 1; CLI dumps `result.json` + video to `out/`; frontend reads statically via `vite dev`. Components: `VideoPlayer` / `Timeline` / `WaveformView` / `BoundaryMarkerLayer`. Phase 5 adds `SegmentEditor` etc. incrementally.
- **C. Backend + frontend both up-front**: FastAPI + React from Phase 1. Flexible but Phase 1 scope balloons.

**Recommendation: B**, specifically **B-1** sub-variant — CLI and viewer fully decoupled. CLI emits artifacts to `out/`, viewer reads statically. Backend deferred until Phase 5 needs persistence.

Sub-options inside B:
- **B-1**: CLI emits artifacts; viewer is independent (`pnpm dev`). Two-command operation.
- **B-2**: `mimicanno view <episode>` runs CLI + boots `vite dev` in one command.
- **B-3**: Same as B-1 but no CLI integration at all.

Awaiting user choice on A / B-1 / B-2 / B-3 / C.

## After Q3, remaining brush-up topics (likely follow-ups)

- Boundary score formulation (weights, normalization, threshold for declaring a boundary)
- Schema concrete shape (final `SubtaskSegment` + `AnnotationResult` + on-disk format / sidecar vs overwrite)
- Allowed-labels configuration story (where it lives, who edits it, unknown-task fallback)
- SAM3 prompt-generation contract (task + initial frame → object/target candidates; what if Gemma returns garbage)
- Phase 1 boundary-detection input/output contract precisely
- LeRobot parquet read contract (which keys, fps source, gripper signal location across robot variants)
- Error handling table (SAM3 fail / VLM bad JSON / robot-state gaps / video decode errors)

## Process state

- Brainstorming skill checklist: tasks 1–2 done. On task 3 (clarifying questions). Q1 answered (option A: brush up). Q2 answered (B' phase split). Q3 pending.
- Final spec target path: `docs/superpowers/specs/2026-04-25-mimicano-design-brushup.md` (overwrite/supplant `docs/design.md` once approved).
- Spec review loop, user review gate, and writing-plans transition still pending.
