# MimicAnno design.md brush-up progress

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

## Status (2026-04-26, after user review round 3 — spec approved, moving to writing-plans)

User review round 3 flagged 1 必須 + 1 強く推奨 + 1 任意:
- (必須) §11 stale-scavenger row was using the old "lock-holder" detection wording. Updated to the `.writer.json` contract.
- (強く推奨) Two CLIs could both pass the lock-free reuse short-circuit (§4.4 step 2), do heavy compute, and then race at lock acquisition. Added a **locked reuse re-check** as §4.4 step 6 so the second publisher reuses the first's output instead of overwriting.
- (任意) `.writer.json` lifecycle clarified: lives only in `*.tmp.<pid>/` and `*.bak.<pid>/`; explicitly removed before finalization so canonical run dirs are clean of writer-only metadata.

Codex round 14-15 verdict: "ready for user review". User approved verbally ("Go でよい") subject to the above 3 fixes — all applied. Next: invoke `superpowers:writing-plans` for Phase 1 implementation plan.

## Status (2026-04-25, after user review round 2 — historical)

User review round 2 flagged 5 actionable issues (3 必須 + 2 準必須) + 4 small fixes. All folded in:

Required:
- `config_hash` now covers `target_phase` + `model_config` (vlm/sam3 + checkpoints); `input_hash` now covers `robot_adapter_config_sha256` for GenericAdapter. Phase 1 vs 2 vs 3 produce different `run_hash`es.
- Scavenger no longer judges by lock holdership. Each `.tmp` / `.bak` carries `.writer.json` (pid, pid_start_time, canonical_name, kind, claimed_at). Deletion requires (PID gone OR start_time mismatch) AND age > threshold. Live writers are safe.
- Run-dir replacement: default is **reuse** (no-op when run_hash matches); `--force` triggers two-rename. Atomicity wording weakened to "brief missing-directory window between the two renames"; viewer retries.

Quasi-required:
- `canonical_name` suffix length 8 → 12 hex. Prefix collision extends to 16. Index upsert keys on full `run_hash` (full sha256 added to index entry).
- §6.6 consumer-capability check changed from `>=` to set membership.

Small:
- §5.3 same-source merge uses `max`, not last-wins.
- "gripper-anchored" → "gripper-biased" with explicit note that multiple non-gripper sources can co-promote.
- Disabled sources contribute 0; weights NOT renormalized — explicit.
- §15 exit criteria renumbered monotonically (1–17).

Codex rounds 11–13 verdict: "ready for user review".

## Status (2026-04-25, after user review round 1 — historical)

User review round 1 (the human reviewer) flagged 10 concrete issues (6 必須 + 4 推奨):
1. canonical_name was config_hash-only → input/task collisions. Fixed by introducing `run_hash = sha256(config_hash + input_hash)` and using `run_hash[:8]` as the directory suffix; `config_hash` and `input_hash` are recorded separately in manifest/index for filtering.
2. Phase 1 unlabeled segments could end up with `overall_confidence=1.0`. Fixed: §6.4 returns 0.0 for reserved phases.
3. §6.6 conflated producer-internal compat with consumer-capability check. Fixed: explicit two-check rule.
4. "Phase 1 hard rules" misnomer (no labeling = nothing to enforce). Fixed: forbidden transitions only apply in Phase 4.
5. `action` column required vs optional contradiction. Fixed: optional in Phase 1, required for Phase 5 export.
6. signals.json off-by-one. Fixed.
7. Vite serve approach was hand-waved. Fixed: §4.2 has a concrete sirv-middleware vite.config.ts.
8. Lock scope too narrow. Fixed: `runs/index.json.lock` is now a publish-transaction lock spanning run-dir replacement + index upsert + scavenger.
9. score_threshold intent unstated. Fixed: §5.3 spells out the precision-favoring (gripper-anchored) policy.
10. Label count "11" was stale. Fixed: 10.
11. (added beyond the 10) `pipeline_status` block on manifest top-level so degrade is observable run-level, not just per-segment.

Codex round 8-10 reviews pass: verdict "ready for user review".

## Status (2026-04-25, before user review round 1 — historical)

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
- Spec at `docs/superpowers/specs/2026-04-25-mimicanno-design-brushup.md`. Pending: user review gate → writing-plans transition.

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
- Final spec target path: `docs/superpowers/specs/2026-04-25-mimicanno-design-brushup.md` (overwrite/supplant `docs/design.md` once approved).
- Spec review loop, user review gate, and writing-plans transition still pending.
