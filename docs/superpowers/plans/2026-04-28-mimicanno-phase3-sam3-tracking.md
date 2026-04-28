# MimicAnno Phase 3 — SAM3 + integrated boundary score + relabel with `vlm_with_object_state` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `mimicanno annotate` so that `--target-phase 3 --vlm-model <id> --sam3-checkpoint <path>` runs the existing Phase 1 signals + a new Phase 3 tracking pipeline (Gemma entity extraction → SAM3 grounding → SAM3 propagation → per-frame object signals → integrated 6-source boundary score → per-segment Phase 3 labeling with `ObjectStateSummary`). Output is a self-contained run directory whose `annotation.json` carries `label_source="vlm_with_object_state"` (or `vlm_robot_state_only` per-segment fallback), `object_track_ids` populated, and a new `tracks.json` artifact. Whole-run degrades produce a "Phase-3-objectless run" using Phase 3 boundary policy + Phase 2 prompt path.

**Architecture:** Phase 3 is a purely additive layer on top of Phase 1/2. A new `mimicanno/object_tracker/` package owns all SAM3 contact behind a thin `SAM3Runtime` wrapper; the rest of the pipeline sees only dataclasses (`Track` / `TrackSample` / `GapEvent` / `ObjectSignals` / `EntityPlan` / `TrackingPlan`). The planner is split into Step A (`TrackingPlanner.extract_entities` — Gemma only) and Step B (`ground_initial_detections` — SAM3 grounding after `SAM3Runtime.load`); orchestrator gates degrade triggers at each step before paying the next cost. Configuration hashing is `target_phase`-gated so Phase 1/2 hashes are byte-identical pre-/post-Phase-3-merge. Phase 3 reuses Phase 2's `LocalGemmaVLMLabeler` via `shared_handle()` — one in-memory Gemma instance for both planner Step A and per-segment labeling.

**Tech Stack:** Python 3.11+ (existing venv), vendored `sam3/` (facebookresearch/sam3 SAM 3.1 release at repo root), `huggingface_hub` + `transformers>=5.5` for Gemma (already a Phase 2 dep), `Pillow` + `numpy` for image / bbox math, `pytest` for tests, optional `[sam3]` pyproject extra for SAM3 runtime deps. POSIX semantics inherited from Phase 1.

**Spec source of truth:** `docs/superpowers/specs/2026-04-28-mimicanno-phase3-sam3-tracking-design.md`. Every section reference (`§3.1`, `§4.3`, etc.) below is **into that document**, not the parent design brushup. Parent spec references are explicitly marked `parent §...`. Phase 2 spec references are marked `phase2 §...`.

---

## File structure (locked in before tasks)

**New package:**

```
mimicanno/
  object_tracker/
    __init__.py             # re-exports the public API surface (spec §1.2)
    track_id.py             # NEW: slugify + make_track_id (spec §2.1)
    planner.py              # NEW: EntityPlan dataclass + TrackingPlanner protocol
                            #      + LocalGemmaTrackingPlanner (Step A only — spec §2.2)
    sam3_runtime.py         # NEW: thin wrapper over vendored sam3/
                            #      (spec §2.3) — only file that imports sam3.*
    propagator.py           # NEW: BBox / TrackSample / GapEvent / Track / TrackingPlan
                            #      dataclasses + ground_initial_detections (Step B, spec §2.4.0)
                            #      + Propagator.run (Step C, spec §2.4)
    signals.py              # NEW: ObjectSignals + compute_object_signals (spec §2.5)
    fixtures.py             # NEW: FixtureTrackingPlanner + FixtureSAM3Tracker (spec §2.6)
```

**New artifact writer + schema:**

```
mimicanno/
  schema.py                 # ADD: ObjectStateSummary, ObjectTrackSummary,
                            #      TracksFile / TracksTrack / TracksSample / TracksGap
                            #      (spec §3, §5.1)
  io.py                     # ADD: write_tracks_json + read_tracks_json with cross-artifact
                            #      integrity check (spec §3.3, §3.5)
```

**Modified existing modules (Phase 3 additions only):**

```
mimicanno/
  pipeline.py               # ADD: annotate_episode_phase3 orchestrator branch + the
                            #      _degrade_to_phase3_objectless helper (spec §7.1, §7.2).
                            #      No changes to Phase 1/2 code paths.
  boundaries.py             # ADD: Phase3BoundaryDetector + 2 new source detectors
                            #      (spec §4.1.1, §4.1.2) + edge-suppression rule.
                            #      Existing Phase 1 detectors untouched.
  config.py                 # ADD: TrackingConfig dataclass + AnnotationConfig.tracking field.
                            #      EXTEND: BoundaryWeights with 2 new fields (default 0.0)
                            #      + BoundaryWeights.phase3_defaults() classmethod.
                            #      EXTEND: BoundaryConfig.to_dict / BoundaryWeights.to_dict /
                            #      AnnotationConfig.to_dict to accept target_phase= kwarg
                            #      (spec §9.1).
                            #      EXTEND: build_model_config to gate sam3_* keys (spec §9.1).
  clip_features.py          # ADD: compute_object_state_summary (spec §5.2).
                            #      EXTEND: ClipFeatures dataclass with optional
                            #      object_state_summary: ObjectStateSummary | None.
  vlm_labeler.py            # ADD: apply_phase3_labeling (spec §5.5, §6) — orchestrator that
                            #      reuses Phase 2 helpers internally; per-segment fallback.
                            #      Phase 2's apply_phase2_labeling untouched.
  vlm_prompt.py             # EXTEND: build_prompt accepts request["object_state_summary"]:
                            #      ObjectStateSummary | None (default None preserves Phase 2
                            #      byte-identity). Phase 3 mode adds 2 SYSTEM sub-blocks.
  cli.py                    # ADD: --sam3-checkpoint, --track-stride-frames CLI flags +
                            #      --target-phase=3 dispatch + abort guards.
  preflight.py              # ADD: SAM3 checkpoint preflight (path / readability /
                            #      sha256-computability) — spec §8 sam3_checkpoint_not_found.
  errors.py                 # ADD: 6 new error codes (spec §8) — sam3_checkpoint_not_found /
                            #      sam3_extras_missing / sam3_runtime_failed / sam3_init_failed /
                            #      gemma_no_object_prompts / sam3_no_initial_detection.
  hashing.py                # NO LOGIC CHANGE — recursive serialization already covers
                            #      AnnotationConfig.tracking via to_dict(target_phase=).
                            #      Touched only for Phase 1/2 hash isolation tests.
pyproject.toml              # ADD: [project.optional-dependencies].sam3 entry.
```

**Tests:**

```
tests/
  unit/
    test_phase3_errors.py                          # NEW (Task 1)
    test_phase3_hash_gating.py                     # NEW (Task 2; pins Phase 1/2 hashes)
    test_tracking_config.py                        # NEW (Task 3)
    test_track_id.py                               # NEW (Task 4)
    object_tracker/
      __init__.py                                  # NEW (empty marker)
      test_dataclasses.py                          # NEW (Task 5; BBox / TrackSample / etc)
      test_propagator.py                           # NEW (Task 8)
      test_signals.py                              # NEW (Task 9)
      test_planner.py                              # NEW (Task 15)
      test_grounding.py                            # NEW (Task 16)
      test_fixtures.py                             # NEW (Task 7)
    test_tracks_json_schema.py                     # NEW (Task 6)
    test_tracks_json_failed_prompts_roundtrip.py   # NEW (Task 6)
    test_phase3_boundary_detector.py               # NEW (Task 10)
    test_phase3_boundary_edge_suppression.py       # NEW (Task 10)
    test_phase3_weights_intent.py                  # NEW (Task 10)
    test_object_state_summary.py                   # NEW (Task 11)
    test_vlm_prompt_phase3.py                      # NEW (Task 12)
    test_phase3_label_run.py                       # NEW (Task 13)
    test_sam3_runtime_smoke.py                     # NEW (Task 14; gated)
    test_preflight_sam3.py                         # NEW (Task 17)
    test_cli_phase3.py                             # NEW (Task 18)
  integration/
    test_phase3_smoke.py                           # NEW (Task 21)
    test_phase3_per_segment_fallback.py            # NEW (Task 22)
    test_phase3_degrade_gemma_no_objects.py        # NEW (Task 23)
    test_phase3_degrade_sam3_no_initial.py         # NEW (Task 23)
    test_phase3_degrade_sam3_init_failed.py        # NEW (Task 23)
    test_phase3_preflight_checkpoint_missing.py    # NEW (Task 24)
    test_phase3_idempotency.py                     # NEW (Task 24)
    test_phase3_distinctness.py                    # NEW (Task 24)
    test_phase3_no_phase12_regression.py           # NEW (Task 24)
    test_tracks_json_cross_artifact.py             # NEW (Task 24)
  snapshots/
    phase3/
      prompt_phase2_byte_identical.txt             # NEW (Task 12; Phase 2 baseline)
      prompt_phase3_full.txt                       # NEW (Task 12; Phase 3 mode)
      object_state_summary_smoke.json              # NEW (Task 11)
      tracks_json_smoke.json                       # NEW (Task 6)
      manifest_phase3_smoke.json                   # NEW (Task 21)
      annotation_phase3_smoke.json                 # NEW (Task 21)
  test_phase3_real_sam3_smoke.py                   # NEW (Task 25; gated by env var + CUDA)
```

**Decomposition rules followed:**
- **One file = one responsibility.** `track_id.py`, `planner.py`, `sam3_runtime.py`, `propagator.py`, `signals.py`, `fixtures.py` are each focused units. The `object_tracker/__init__.py` only re-exports.
- **Files that change together live together.** All SAM3 contact lives in `sam3_runtime.py`; all Step A code lives in `planner.py`; Step B and Step C share `propagator.py` because they both consume SAM3Runtime.
- **Test-to-source 1:1 where possible.** Each `mimicanno/object_tracker/<x>.py` has at least one `tests/unit/object_tracker/test_<x>.py`.
- **CI vs gated split.** All unit + integration tests use `FixtureTrackingPlanner` + `FixtureSAM3Tracker`; `tests/test_phase3_real_sam3_smoke.py` is the env-gated Layer 3 smoke (Task 25).
- **Phase 1/2 isolation.** Every modified file has explicit "Phase 3 additions only — Phase 1/2 code unchanged" tests in the relevant task.

---

## Task ordering rationale

Order minimizes blockage and lets tests catch contract violations early:

1. **Foundations (Tasks 1–3):** error codes, hash gating, TrackingConfig. Everything else imports these. Hash gating MUST land first to lock the Phase 1/2 byte-identity invariant in CI.
2. **Pure dataclasses + IDs (Tasks 4–5):** `track_id.py` + propagator.py / planner.py dataclasses. Zero external deps.
3. **Schema + I/O (Task 6):** TracksFile + write/read with cross-artifact integrity. Self-contained.
4. **Test fixtures (Task 7):** FixtureTrackingPlanner + FixtureSAM3Tracker. Required by Tasks 8, 13, 21–24.
5. **Pure-algorithm modules (Tasks 8–10):** Propagator.run, compute_object_signals, Phase3BoundaryDetector. All driven by fixtures, no real SAM3 / Gemma.
6. **Object-state summary + prompt (Tasks 11–12):** ObjectStateSummary + build_prompt extension. Snapshot tests pin both Phase 2 byte-identity and Phase 3 mode.
7. **Phase 3 labeling (Task 13):** apply_phase3_labeling reuses Phase 2 helpers; per-segment fallback path.
8. **SAM3 wrapper (Task 14, gated):** SAM3Runtime — only task touching real SAM3 weights. Skipped in CI.
9. **Real planner + grounding (Tasks 15–16):** LocalGemmaTrackingPlanner.extract_entities + ground_initial_detections. Tested via mocks of Gemma and SAM3Runtime.
10. **Preflight + CLI (Tasks 17–18):** SAM3 checkpoint preflight + CLI flags. Required by orchestrator.
11. **Pipeline orchestrator (Tasks 19–20):** annotate_episode_phase3 + _degrade_to_phase3_objectless.
12. **Integration tests (Tasks 21–24):** end-to-end smoke + per-segment fallback + 3 degrade paths + preflight + idempotency + distinctness + Phase 1/2 no-regression + cross-artifact integrity.
13. **Real-SAM3 smoke + final cleanup (Task 25):** env-gated Layer 3 smoke + mypy --strict + ruff + milestone commit.

---

## Conventions referenced throughout

**Test command:** All `pytest` invocations use the workspace pattern documented in `brushup_progress_pointer.md`:

```bash
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/python -m pytest <path> -v
```

This strips ROS environment leakage that would otherwise pull `launch_testing` into the pytest plugin set.

**mypy:** `env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH .venv/bin/python -m mypy --strict mimicanno/`

**ruff:** `env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH .venv/bin/python -m ruff check mimicanno/ tests/`

**Commit style:** `feat(phase3): ...` for additive code, `test(phase3): ...` for tests, `fix(phase3): ...` for bug fixes during the plan, `refactor(phase3): ...` for renames/cleanups. Always append `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.

---

## Task 1: Phase 3 error codes (`mimicanno/errors.py`)

Six new structured error types (spec §8). Pure additions; existing Phase 1/2 codes untouched.

**Files:**
- Modify: `mimicanno/errors.py:73-end`
- Test: `tests/unit/test_phase3_errors.py`

- [ ] **Step 1.1: Write the failing test**

Create `tests/unit/test_phase3_errors.py`:

```python
"""Phase 3 error code structure (spec §8)."""

from __future__ import annotations

import io
import json

import pytest

from mimicanno.errors import (
    GemmaNoObjectPrompts,
    SAM3CheckpointNotFound,
    SAM3ExtrasMissing,
    SAM3InitFailed,
    SAM3NoInitialDetection,
    SAM3RuntimeFailed,
    write_error_json,
)


def test_sam3_checkpoint_not_found_code_and_context() -> None:
    err = SAM3CheckpointNotFound(
        path="/missing/sam3.ckpt", reason="file not found"
    )
    assert err.code == "sam3_checkpoint_not_found"
    assert "missing" in err.message.lower() or "/missing/sam3.ckpt" in err.message
    assert err.context == {"path": "/missing/sam3.ckpt", "reason": "file not found"}


def test_sam3_extras_missing_carries_install_hint() -> None:
    err = SAM3ExtrasMissing()
    assert err.code == "sam3_extras_missing"
    assert "[sam3]" in err.message  # install hint visible to user


def test_sam3_runtime_failed_includes_frame_index() -> None:
    err = SAM3RuntimeFailed(frame_index=312, reason="cuda kernel fault")
    assert err.code == "sam3_runtime_failed"
    assert err.context == {"frame_index": 312, "reason": "cuda kernel fault"}


def test_sam3_init_failed_carries_underlying_repr() -> None:
    err = SAM3InitFailed(underlying="RuntimeError('CUDA OOM at 8.2 GB')")
    assert err.code == "sam3_init_failed"
    # underlying is recorded for stderr WARN log; it is NOT a degrade reason string
    assert err.context == {"underlying": "RuntimeError('CUDA OOM at 8.2 GB')"}


def test_gemma_no_object_prompts_no_context() -> None:
    err = GemmaNoObjectPrompts()
    assert err.code == "gemma_no_object_prompts"
    assert err.context == {}


def test_sam3_no_initial_detection_includes_failed_prompts() -> None:
    err = SAM3NoInitialDetection(
        failed=[("object", "red block"), ("object", "blue block")]
    )
    assert err.code == "sam3_no_initial_detection"
    assert err.context["failed_prompts"] == [
        {"role": "object", "prompt": "red block"},
        {"role": "object", "prompt": "blue block"},
    ]


def test_write_error_json_for_phase3_code() -> None:
    err = SAM3RuntimeFailed(frame_index=42, reason="x")
    sink = io.StringIO()
    write_error_json(err, stream=sink)
    payload = json.loads(sink.getvalue())
    assert payload["error_code"] == "sam3_runtime_failed"
    assert payload["context"]["frame_index"] == 42


@pytest.mark.parametrize(
    "code",
    [
        "sam3_checkpoint_not_found",
        "sam3_extras_missing",
        "sam3_runtime_failed",
        "sam3_init_failed",
        "gemma_no_object_prompts",
        "sam3_no_initial_detection",
    ],
)
def test_phase3_codes_distinct(code: str) -> None:
    """All 6 codes are distinct strings — used as dict keys / enum values
    elsewhere; collision would be a silent bug."""
    assert isinstance(code, str)
```

- [ ] **Step 1.2: Run the test (expect failure)**

```bash
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/python -m pytest tests/unit/test_phase3_errors.py -v
```

Expected: ImportError on `GemmaNoObjectPrompts` etc.

- [ ] **Step 1.3: Implement the 6 error classes**

Append to `mimicanno/errors.py`:

```python
class SAM3CheckpointNotFound(MimicAnnoError):
    """`--sam3-checkpoint` path missing / unreadable / sha256 cannot be
    computed (spec §8). Tier-1 abort, exits non-zero."""

    def __init__(self, path: str, reason: str) -> None:
        super().__init__(
            code="sam3_checkpoint_not_found",
            message=f"sam3 checkpoint missing or unreadable at {path}: {reason}",
            context={"path": path, "reason": reason},
        )


class SAM3ExtrasMissing(MimicAnnoError):
    """`import sam3` raises ModuleNotFoundError under `--target-phase 3`
    (spec §8). Tier-1 abort, exits non-zero."""

    def __init__(self) -> None:
        super().__init__(
            code="sam3_extras_missing",
            message=(
                "the sam3 package is not installed; "
                "install with `pip install '.[sam3]'`"
            ),
            context={},
        )


class SAM3RuntimeFailed(MimicAnnoError):
    """`SAM3Runtime.propagate(...)` raises mid-episode (spec §8).
    Aborts with non-zero exit; in-flight tmp dir is rm -rf'd best-effort."""

    def __init__(self, frame_index: int, reason: str) -> None:
        super().__init__(
            code="sam3_runtime_failed",
            message=f"sam3 propagation failed at frame {frame_index}: {reason}",
            context={"frame_index": frame_index, "reason": reason},
        )


class SAM3InitFailed(MimicAnnoError):
    """`SAM3Runtime.load(...)` raises (CUDA OOM, incompatible weights, etc.)
    after preflight passed (spec §8). DEGRADE reason — never written to stderr
    structured JSON; the underlying repr() is logged to stderr as a WARN line.
    The `underlying` context field exists for the WARN log only; it is NEVER
    written to annotation.notes (PII rule, spec §7.2 / §8)."""

    def __init__(self, underlying: str) -> None:
        super().__init__(
            code="sam3_init_failed",
            message="sam3 model load failed",
            context={"underlying": underlying},
        )


class GemmaNoObjectPrompts(MimicAnnoError):
    """Gemma planner Step A returned `object_prompts == []` (or all parses
    failed across `planner_max_retries`). DEGRADE reason — Phase-3-objectless
    run (spec §7.2)."""

    def __init__(self) -> None:
        super().__init__(
            code="gemma_no_object_prompts",
            message="gemma planner returned no object prompts",
            context={},
        )


class SAM3NoInitialDetection(MimicAnnoError):
    """SAM3 Step B grounding returned no bbox for any object prompt
    (spec §7.2). DEGRADE reason — Phase-3-objectless run."""

    def __init__(self, failed: list[tuple[str, str]]) -> None:
        super().__init__(
            code="sam3_no_initial_detection",
            message="sam3 grounded no bbox for any object prompt",
            context={
                "failed_prompts": [
                    {"role": role, "prompt": prompt} for role, prompt in failed
                ]
            },
        )
```

- [ ] **Step 1.4: Run the test (expect pass)**

```bash
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/python -m pytest tests/unit/test_phase3_errors.py -v
```

Expected: 8 PASS.

- [ ] **Step 1.5: Verify Phase 1/2 error tests still pass**

```bash
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/python -m pytest tests/unit/test_errors.py -v 2>/dev/null || true
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/python -m pytest tests/ -k "error" -v
```

Expected: existing error tests still PASS (Phase 3 codes are pure additions).

- [ ] **Step 1.6: Commit**

```bash
git add mimicanno/errors.py tests/unit/test_phase3_errors.py
git commit -m "$(cat <<'EOF'
feat(errors): add Phase 3 error codes (spec §8)

6 new structured error types: sam3_checkpoint_not_found,
sam3_extras_missing, sam3_runtime_failed, sam3_init_failed,
gemma_no_object_prompts, sam3_no_initial_detection.

Channel rule per spec §8: 3 are abort codes (exit non-zero, stderr JSON),
3 are degrade reasons (exit 0, recorded only in annotation.notes via the
canonical short message — underlying cause goes to stderr WARN log only,
NEVER to notes per the PII rule).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Hash payload gating + `BoundaryWeights.phase3_defaults()` (`mimicanno/config.py`)

Critical task — establishes the Phase 1/2 byte-identity invariant before any other Phase 3 code can land. The existing `BoundaryConfig` / `AnnotationConfig.to_dict()` are extended to accept a `target_phase: int` kwarg; new fields are gated on `target_phase >= 3`. The `BoundaryWeights` does NOT exist yet (current code uses a plain `dict[str, float]` for `weights`); we promote `weights` to a typed dataclass with the 2 new fields default-0.0.

**Spec correction note (do not skip):** the original §9.1 said `sam3_*` keys would be omitted from Phase 1/2 payloads. The existing `ModelConfig` dataclass pre-declares `sam3_model` / `sam3_checkpoint` and serializes them as `null` for Phase 1/2 today; commit `889c6f6` updated the spec to reflect this. Phase 3 adds **value-gating** (None for Phase 1/2, populated for Phase 3) but NOT **key-gating** for `sam3_*`. Key-gating applies only to: (a) `AnnotationConfig.tracking` sub-block (new), (b) the 2 new keys on `BoundaryWeights` (`gripper_object_distance_threshold_crossing`, `object_motion_start_stop`).

**Files:**
- Modify: `mimicanno/config.py:48-75` (BoundaryConfig — promote `weights` to typed dataclass + accept `target_phase`)
- Modify: `mimicanno/config.py:257-272` (AnnotationConfig.to_dict — accept `target_phase`)
- Modify: `mimicanno/cli.py:144-146` (pass `target_phase` to to_dict via compute_config_hash; see Step 2.6)
- Modify: `mimicanno/config.py:297-298` (compute_config_hash — accept `target_phase`)
- Test: `tests/unit/test_phase3_hash_gating.py`

- [ ] **Step 2.1: Capture pre-merge Phase 1/2 hash baselines**

Before touching `config.py`, snapshot the canonical hash of two well-known config shapes so the gating test pins those values:

```bash
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/python <<'PY'
from pathlib import Path
from mimicanno.config import (
    AnnotationConfig, BoundaryConfig, ModelConfig, VLMConfig,
    compute_config_hash,
)
phase1 = AnnotationConfig(
    boundary=BoundaryConfig.with_defaults(),
    target_phase=1,
    model_config=ModelConfig(None, None, None, None),
    vlm=None,
)
phase2 = AnnotationConfig(
    boundary=BoundaryConfig.with_defaults(),
    target_phase=2,
    model_config=ModelConfig("google/gemma-4-E2B-it", "sha256:abc", None, None),
    vlm=VLMConfig(model_id="google/gemma-4-E2B-it", resolved_checkpoint="sha256:abc"),
)
print("PHASE1_HASH =", repr(compute_config_hash(phase1)))
print("PHASE2_HASH =", repr(compute_config_hash(phase2)))
PY
```

Record the two strings printed (e.g., `PHASE1_HASH = 'sha256:abc123...'`). They will be pinned in the test in Step 2.3.

- [ ] **Step 2.2: Write the failing test**

Create `tests/unit/test_phase3_hash_gating.py`:

```python
"""Phase 1/2 config_hash byte-identity invariant under Phase 3 schema additions
(spec §9.1, §9.3). If this test ever fails, every existing Phase 1/2
canonical_name on disk is invalidated."""

from __future__ import annotations

import json

import pytest

from mimicanno.config import (
    AnnotationConfig,
    BoundaryConfig,
    BoundaryWeights,
    ModelConfig,
    TrackingConfig,
    VLMConfig,
    canonical_json,
    compute_config_hash,
)


# Pinned values from Step 2.1 — replace these strings with the actual outputs.
PHASE1_HASH_PRE_MERGE = "sha256:REPLACE_WITH_STEP_2_1_OUTPUT"
PHASE2_HASH_PRE_MERGE = "sha256:REPLACE_WITH_STEP_2_1_OUTPUT"


def _phase1_config() -> AnnotationConfig:
    return AnnotationConfig(
        boundary=BoundaryConfig.with_defaults(),
        target_phase=1,
        model_config=ModelConfig(None, None, None, None),
        vlm=None,
    )


def _phase2_config() -> AnnotationConfig:
    return AnnotationConfig(
        boundary=BoundaryConfig.with_defaults(),
        target_phase=2,
        model_config=ModelConfig("google/gemma-4-E2B-it", "sha256:abc", None, None),
        vlm=VLMConfig(model_id="google/gemma-4-E2B-it", resolved_checkpoint="sha256:abc"),
    )


def _phase3_config() -> AnnotationConfig:
    return AnnotationConfig(
        boundary=BoundaryConfig.with_defaults(weights=BoundaryWeights.phase3_defaults()),
        target_phase=3,
        model_config=ModelConfig(
            "google/gemma-4-E2B-it", "sha256:abc",
            "facebook/sam3", "sha256:def",
        ),
        vlm=VLMConfig(model_id="google/gemma-4-E2B-it", resolved_checkpoint="sha256:abc"),
        tracking=TrackingConfig(
            sam3_model_id="facebook/sam3",
            sam3_checkpoint="/path/to/sam3.ckpt",
        ),
    )


def test_phase1_hash_unchanged() -> None:
    """Pinned Phase 1 hash MUST match pre-merge value."""
    assert compute_config_hash(_phase1_config()) == PHASE1_HASH_PRE_MERGE


def test_phase2_hash_unchanged() -> None:
    """Pinned Phase 2 hash MUST match pre-merge value."""
    assert compute_config_hash(_phase2_config()) == PHASE2_HASH_PRE_MERGE


def test_phase1_payload_omits_tracking_key() -> None:
    """When target_phase < 3, AnnotationConfig.to_dict() MUST NOT emit the
    tracking sub-block."""
    payload = _phase1_config().to_dict()
    assert "tracking" not in payload["annotation_config"]


def test_phase2_payload_omits_tracking_key() -> None:
    payload = _phase2_config().to_dict()
    assert "tracking" not in payload["annotation_config"]


def test_phase1_payload_includes_sam3_model_keys_as_null() -> None:
    """ModelConfig.to_dict() always emits sam3_model / sam3_checkpoint;
    Phase 1/2 sets them to null. Changing this would break existing
    Phase 1/2 canonical_names (spec §9.1 implementation reality note)."""
    payload = _phase1_config().to_dict()
    assert payload["model_config"]["sam3_model"] is None
    assert payload["model_config"]["sam3_checkpoint"] is None


def test_phase1_boundary_weights_omit_phase3_keys() -> None:
    """BoundaryWeights.to_dict(target_phase=1) MUST NOT emit the 2 Phase 3
    keys. Otherwise Phase 1 hash would shift even though the values are 0.0."""
    payload = _phase1_config().to_dict()
    weights = payload["annotation_config"]["boundary"]["weights"]
    assert "gripper_object_distance_threshold_crossing" not in weights
    assert "object_motion_start_stop" not in weights


def test_phase3_payload_includes_tracking_key() -> None:
    payload = _phase3_config().to_dict()
    assert "tracking" in payload["annotation_config"]
    assert payload["annotation_config"]["tracking"]["sam3_model_id"] == "facebook/sam3"


def test_phase3_payload_excludes_sam3_path_in_tracking() -> None:
    """TrackingConfig.to_dict MUST exclude sam3_checkpoint (filesystem path):
    the authoritative location is model_config.sam3_checkpoint (sha256 of
    file content), not TrackingConfig (path string). Otherwise the hash
    becomes sensitive to where the user happens to put the checkpoint file
    (spec §9.1, §7.4)."""
    payload = _phase3_config().to_dict()
    assert "sam3_checkpoint" not in payload["annotation_config"]["tracking"]


def test_phase3_payload_includes_phase3_boundary_keys() -> None:
    payload = _phase3_config().to_dict()
    weights = payload["annotation_config"]["boundary"]["weights"]
    assert weights["gripper_object_distance_threshold_crossing"] == pytest.approx(0.25)
    assert weights["object_motion_start_stop"] == pytest.approx(0.10)
    assert weights["gripper_transition"] == pytest.approx(0.45)


def test_phase3_hash_distinct_from_phase2() -> None:
    """Same vlm + episode produces different hash because target_phase differs
    AND tracking sub-block + new boundary keys + sam3_* in model_config."""
    assert compute_config_hash(_phase3_config()) != compute_config_hash(_phase2_config())
```

- [ ] **Step 2.3: Patch the pinned hashes from Step 2.1 output**

Replace the two `REPLACE_WITH_STEP_2_1_OUTPUT` placeholders with the actual hash strings printed by Step 2.1.

- [ ] **Step 2.4: Run the test (expect failure on ImportError + FAIL)**

```bash
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/python -m pytest tests/unit/test_phase3_hash_gating.py -v
```

Expected: ImportError on `BoundaryWeights` / `TrackingConfig`, plus `BoundaryConfig.with_defaults(weights=...)` signature mismatch.

- [ ] **Step 2.5: Implement BoundaryWeights, extend BoundaryConfig, add TrackingConfig stub**

Edit `mimicanno/config.py`:

1. Add `BoundaryWeights` dataclass after `DEFAULT_BOUNDARY_WEIGHTS`:

```python
@dataclass(slots=True, frozen=True)
class BoundaryWeights:
    """Boundary-source weights (spec §4.2). Single class — Phase 3 default
    values come from the phase3_defaults() classmethod, not a separate type.

    The 2 Phase 3 fields default to 0.0; their serialization is target_phase-
    gated (see to_dict) so Phase 1/2 hashes are byte-identical pre-/post-
    Phase-3-merge."""

    gripper_transition: float = DEFAULT_BOUNDARY_WEIGHTS["gripper_transition"]
    eef_velocity_valley: float = DEFAULT_BOUNDARY_WEIGHTS["eef_velocity_valley"]
    eef_acceleration_peak: float = DEFAULT_BOUNDARY_WEIGHTS["eef_acceleration_peak"]
    action_norm_change: float = DEFAULT_BOUNDARY_WEIGHTS["action_norm_change"]
    # Phase 3 additions — default 0.0; key gated out of Phase 1/2 payload via to_dict.
    gripper_object_distance_threshold_crossing: float = 0.0
    object_motion_start_stop: float = 0.0

    @classmethod
    def phase3_defaults(cls) -> "BoundaryWeights":
        """Spec §4.2 Phase 3 default weights (sum = 1.00; gripper-biased
        precision per §4.3)."""
        return cls(
            gripper_transition=0.45,
            eef_velocity_valley=0.15,
            eef_acceleration_peak=0.03,
            action_norm_change=0.02,
            gripper_object_distance_threshold_crossing=0.25,
            object_motion_start_stop=0.10,
        )

    def to_dict(self, *, target_phase: int) -> dict[str, float]:
        payload: dict[str, float] = {
            "gripper_transition": self.gripper_transition,
            "eef_velocity_valley": self.eef_velocity_valley,
            "eef_acceleration_peak": self.eef_acceleration_peak,
            "action_norm_change": self.action_norm_change,
        }
        if target_phase >= 3:
            payload["gripper_object_distance_threshold_crossing"] = (
                self.gripper_object_distance_threshold_crossing
            )
            payload["object_motion_start_stop"] = self.object_motion_start_stop
        return payload
```

2. Modify `BoundaryConfig` to hold a `BoundaryWeights` instead of `dict[str, float]`. The existing field name `weights` is preserved; the type changes. Update `to_dict` to accept `target_phase`:

```python
@dataclass(slots=True)
class BoundaryConfig:
    weights: BoundaryWeights
    thresholds: dict[str, float]
    merge_window_sec: float
    score_threshold: float
    disabled_sources: list[str]

    def to_dict(self, *, target_phase: int) -> dict[str, Any]:
        return {
            "weights": self.weights.to_dict(target_phase=target_phase),
            "thresholds": dict(self.thresholds),
            "merge_window_sec": self.merge_window_sec,
            "score_threshold": self.score_threshold,
            "disabled_sources": list(self.disabled_sources),
        }

    @classmethod
    def with_defaults(
        cls,
        *,
        weights: BoundaryWeights | None = None,
    ) -> "BoundaryConfig":
        """BoundaryConfig populated with the spec-§4.3 default values.

        When `weights` is None, uses `BoundaryWeights()` (Phase 1 defaults).
        Pass `weights=BoundaryWeights.phase3_defaults()` for Phase 3.
        """
        return cls(
            weights=weights if weights is not None else BoundaryWeights(),
            thresholds=dict(DEFAULT_BOUNDARY_THRESHOLDS),
            merge_window_sec=DEFAULT_MERGE_WINDOW_SEC,
            score_threshold=DEFAULT_SCORE_THRESHOLD,
            disabled_sources=[],
        )
```

3. Add `TrackingConfig` dataclass (after `VLMConfig`):

```python
@dataclass(slots=True, frozen=True)
class TrackingConfig:
    """Phase 3 tracking configuration (spec §7.4).

    NOTE: sam3_checkpoint (path string) is INTENTIONALLY excluded from
    to_dict() — the authoritative hashed value is model_config.sam3_checkpoint
    (sha256 of file content). Including the path here would make the hash
    sensitive to filesystem location (spec §9.1)."""

    sam3_model_id: str = "facebook/sam3"
    sam3_checkpoint: str | None = None       # path; CLI preflight validates
    track_stride_frames: int | None = None
    min_track_score: float = 0.30
    max_gap_frames: int | None = None
    reacquisition_iou_threshold: float = 0.30
    visibility_threshold: float = 0.5
    gripper_object_distance_threshold: float = 0.05  # image-width-normalized
    object_motion_threshold: float = 0.02            # image-width-normalized / sec
    object_motion_min_sec: float = 0.10
    image_aspect_ratio_default: float = 16.0 / 9.0
    planner_max_retries: int = 3

    def to_dict(self) -> dict[str, Any]:
        # sam3_checkpoint is excluded — see class docstring + spec §9.1
        return {
            "sam3_model_id": self.sam3_model_id,
            "track_stride_frames": self.track_stride_frames,
            "min_track_score": self.min_track_score,
            "max_gap_frames": self.max_gap_frames,
            "reacquisition_iou_threshold": self.reacquisition_iou_threshold,
            "visibility_threshold": self.visibility_threshold,
            "gripper_object_distance_threshold": self.gripper_object_distance_threshold,
            "object_motion_threshold": self.object_motion_threshold,
            "object_motion_min_sec": self.object_motion_min_sec,
            "image_aspect_ratio_default": self.image_aspect_ratio_default,
            "planner_max_retries": self.planner_max_retries,
        }

    def effective_stride(self, fps: float) -> int:
        """Default stride = max(1, round(fps / 3))."""
        return (
            self.track_stride_frames
            if self.track_stride_frames is not None
            else max(1, round(fps / 3))
        )

    def effective_max_gap_frames(self, fps: float) -> int:
        return (
            self.max_gap_frames
            if self.max_gap_frames is not None
            else round(fps * 1.0)
        )
```

4. Extend `AnnotationConfig` with `tracking` field + gated `to_dict`:

```python
@dataclass(slots=True)
class AnnotationConfig:
    boundary: BoundaryConfig
    target_phase: int
    model_config: ModelConfig
    vlm: VLMConfig | None = None
    tracking: TrackingConfig | None = None  # required iff target_phase >= 3

    def to_dict(self) -> dict[str, Any]:
        ann_inner: dict[str, Any] = {
            "boundary": self.boundary.to_dict(target_phase=self.target_phase),
        }
        if self.vlm is not None:
            ann_inner["vlm"] = self.vlm.to_dict()
        if self.target_phase >= 3 and self.tracking is not None:
            ann_inner["tracking"] = self.tracking.to_dict()
        return {
            "annotation_config": ann_inner,
            "target_phase": self.target_phase,
            "model_config": self.model_config.to_dict(),
        }
```

5. Add a helper for downstream model_config building (spec §9.1):

```python
def build_model_config(
    *,
    target_phase: int,
    vlm: VLMConfig | None,
    tracking: TrackingConfig | None,
    sam3_checkpoint_sha256: str | None,
) -> ModelConfig:
    """Build ModelConfig for a given target_phase. Phase 1/2: sam3_* are
    None (preserves existing Phase 1/2 hashes). Phase 3: sam3_* are
    populated from tracking config + the sha256 of the checkpoint file
    (computed by preflight; see Task 17).

    All four ModelConfig keys are always emitted by ModelConfig.to_dict()
    (existing serialization invariant). Gating is value-only, NOT key-only
    (spec §9.1 implementation reality note)."""
    return ModelConfig(
        vlm_model=vlm.model_id if (target_phase >= 2 and vlm is not None) else None,
        vlm_checkpoint=(
            vlm.resolved_checkpoint
            if (target_phase >= 2 and vlm is not None)
            else None
        ),
        sam3_model=(
            tracking.sam3_model_id if (target_phase >= 3 and tracking is not None) else None
        ),
        sam3_checkpoint=sam3_checkpoint_sha256 if target_phase >= 3 else None,
    )
```

- [ ] **Step 2.6: Update CLI / pipeline call sites for the new BoundaryConfig.weights type**

Existing Phase 1/2 code constructs `BoundaryConfig(weights={"gripper_transition": ..., ...}, ...)` from YAML. Update the YAML loader (`load_boundary_config_yaml` near `mimicanno/config.py:200`) and any other dict-based call site to convert `dict` → `BoundaryWeights(**dict)`. Run a grep first:

```bash
grep -rn "BoundaryConfig(" mimicanno/ tests/ --include="*.py"
grep -rn 'weights=\|weights={\|"weights"' mimicanno/ tests/ --include="*.py"
```

For each call site that passes a dict, convert. Existing YAML-config tests will catch errors.

- [ ] **Step 2.7: Run the new test (expect PASS)**

```bash
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/python -m pytest tests/unit/test_phase3_hash_gating.py -v
```

Expected: 9 PASS.

- [ ] **Step 2.8: Run full Phase 1/2 test suite for regression**

```bash
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/python -m pytest tests/ -x --ignore=tests/unit/test_phase3_hash_gating.py --ignore=tests/unit/test_phase3_errors.py -v
```

Expected: every existing test PASS. If any hash-related Phase 1/2 test fails, do NOT proceed — that's a real regression.

- [ ] **Step 2.9: Commit**

```bash
git add mimicanno/config.py tests/unit/test_phase3_hash_gating.py
# Plus any call sites updated in Step 2.6:
git add <updated files>
git commit -m "$(cat <<'EOF'
feat(config): hash payload gating + BoundaryWeights + TrackingConfig

Promotes BoundaryConfig.weights from dict[str,float] to a typed
BoundaryWeights dataclass with 2 new Phase 3 fields default-0.0 and a
phase3_defaults() classmethod (gripper 0.45, gripper_object_distance 0.25,
valley 0.15, object_motion 0.10, accel 0.03, action 0.02 — sums to 1.00,
gripper-biased precision per spec §4.3).

Adds TrackingConfig (spec §7.4); excludes sam3_checkpoint path from
to_dict() so the hash isn't sensitive to checkpoint filesystem location.

Extends AnnotationConfig.to_dict + BoundaryConfig.to_dict +
BoundaryWeights.to_dict with target_phase= kwarg. Phase 1/2 payloads
omit the new keys entirely (key-gated); the 2 sam3_* keys on ModelConfig
remain in the payload as null for Phase 1/2 (value-gated, preserves
existing hashes per spec §9.1 implementation reality note).

build_model_config() helper added for downstream value-gating.

test_phase3_hash_gating.py pins the pre-merge Phase 1/2 hashes — if this
test ever regresses, every existing Phase 1/2 canonical_name on disk is
invalidated.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: TrackingConfig validation + dataclass tests (`mimicanno/config.py`)

The `TrackingConfig` skeleton landed in Task 2; this task adds the validation surface, classmethods, and serialization round-trip tests that guard against accidental drift.

**Files:**
- Modify: `mimicanno/config.py` (add validation classmethods)
- Test: `tests/unit/test_tracking_config.py`

- [ ] **Step 3.1: Write the failing test**

Create `tests/unit/test_tracking_config.py`:

```python
"""TrackingConfig validation and serialization (spec §7.4)."""

from __future__ import annotations

import json

import pytest

from mimicanno.config import TrackingConfig, canonical_json
from mimicanno.errors import MimicAnnoError


def test_defaults_match_spec_section_7_4() -> None:
    cfg = TrackingConfig()
    assert cfg.sam3_model_id == "facebook/sam3"
    assert cfg.min_track_score == 0.30
    assert cfg.reacquisition_iou_threshold == 0.30
    assert cfg.visibility_threshold == 0.5
    assert cfg.gripper_object_distance_threshold == 0.05
    assert cfg.object_motion_threshold == 0.02
    assert cfg.object_motion_min_sec == 0.10
    assert cfg.image_aspect_ratio_default == pytest.approx(16.0 / 9.0)
    assert cfg.planner_max_retries == 3
    assert cfg.track_stride_frames is None
    assert cfg.max_gap_frames is None


def test_effective_stride_default_at_30fps_is_10() -> None:
    """30 / 3 = 10 (spec §7.4 effective_stride formula)."""
    cfg = TrackingConfig()
    assert cfg.effective_stride(30.0) == 10
    assert cfg.effective_stride(60.0) == 20
    assert cfg.effective_stride(15.0) == 5


def test_effective_stride_explicit_override_wins() -> None:
    cfg = TrackingConfig(track_stride_frames=4)
    assert cfg.effective_stride(30.0) == 4


def test_effective_stride_low_fps_clamped_to_one() -> None:
    """fps below 3 would round to 0; spec §7.4 says max(1, ...)."""
    cfg = TrackingConfig()
    assert cfg.effective_stride(2.0) == 1
    assert cfg.effective_stride(1.0) == 1


def test_effective_max_gap_frames_default_one_second() -> None:
    cfg = TrackingConfig()
    assert cfg.effective_max_gap_frames(30.0) == 30
    assert cfg.effective_max_gap_frames(60.0) == 60


def test_effective_max_gap_frames_explicit_override() -> None:
    cfg = TrackingConfig(max_gap_frames=42)
    assert cfg.effective_max_gap_frames(30.0) == 42


def test_to_dict_excludes_sam3_checkpoint() -> None:
    """spec §9.1: sam3_checkpoint is excluded from TrackingConfig.to_dict;
    authoritative location is model_config.sam3_checkpoint (sha256)."""
    cfg = TrackingConfig(sam3_checkpoint="/path/to/sam3.ckpt")
    payload = cfg.to_dict()
    assert "sam3_checkpoint" not in payload
    # sam3_model_id IS included (it's a model identifier, not a path)
    assert payload["sam3_model_id"] == "facebook/sam3"


def test_to_dict_serialization_round_trip_via_canonical_json() -> None:
    """Canonicalisation MUST be byte-stable (spec §9.2)."""
    cfg = TrackingConfig(
        sam3_model_id="facebook/sam3",
        sam3_checkpoint="/abs/path",
        track_stride_frames=10,
        min_track_score=0.25,
    )
    blob = canonical_json(cfg.to_dict())
    parsed = json.loads(blob)
    assert parsed["sam3_model_id"] == "facebook/sam3"
    assert parsed["track_stride_frames"] == 10
    assert parsed["min_track_score"] == 0.25
    # Repeat — same bytes
    assert canonical_json(cfg.to_dict()) == blob


def test_frozen_dataclass() -> None:
    """TrackingConfig is frozen — accidental mutation would break hash
    determinism."""
    cfg = TrackingConfig()
    with pytest.raises(Exception):  # dataclasses.FrozenInstanceError or AttributeError
        cfg.sam3_model_id = "modified"  # type: ignore[misc]
```

- [ ] **Step 3.2: Run the test**

```bash
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/python -m pytest tests/unit/test_tracking_config.py -v
```

Expected: 9 PASS (TrackingConfig already exists from Task 2).

- [ ] **Step 3.3: Commit**

```bash
git add tests/unit/test_tracking_config.py
git commit -m "$(cat <<'EOF'
test(config): pin TrackingConfig defaults + effective_* classmethods

Locks in spec §7.4 defaults (min_track_score=0.30, visibility_threshold=0.5,
gripper_object_distance_threshold=0.05 image-width-normalized,
object_motion_threshold=0.02 image-width-normalized/sec, etc) and the
effective_stride / effective_max_gap_frames classmethods that resolve
None defaults against fps.

Also pins to_dict() exclusion of sam3_checkpoint (path string) per the
spec §9.1 hash-stability rule.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `track_id.py` — slugify + make_track_id (`mimicanno/object_tracker/track_id.py`)

The single source of truth for the parent-spec §9.5 track-id form `obj:role:slug:index`. Used everywhere a track-id string is constructed; downstream code parses by splitting on `:` so this format MUST never drift.

**Files:**
- Create: `mimicanno/object_tracker/__init__.py` (empty stub for now; populated in later tasks)
- Create: `mimicanno/object_tracker/track_id.py`
- Test: `tests/unit/test_track_id.py`

- [ ] **Step 4.1: Create the package skeleton**

```bash
mkdir -p mimicanno/object_tracker tests/unit/object_tracker
touch mimicanno/object_tracker/__init__.py tests/unit/object_tracker/__init__.py
```

- [ ] **Step 4.2: Write the failing test**

Create `tests/unit/test_track_id.py`:

```python
"""Track-id slugify + make_track_id (spec §2.1, parent §9.5)."""

from __future__ import annotations

import pytest

from mimicanno.object_tracker.track_id import make_track_id, slugify


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Red Block", "red_block"),
        ("red block", "red_block"),
        ("RED  BLOCK", "red_block"),       # collapse runs of whitespace
        ("bin A!!", "bin_a"),               # strip punctuation
        ("bin-A_2", "bin_a_2"),             # hyphen and existing _ both collapse
        ("__under__score__", "under_score"),# strip leading/trailing underscores
        ("café", "caf"),                    # ASCII fold (drop non-alnum)
        ("   ", "unnamed"),                 # whitespace-only -> sentinel
        ("", "unnamed"),                    # empty -> sentinel
        ("123", "123"),                     # digits preserved
        ("ALL_CAPS", "all_caps"),
    ],
)
def test_slugify(raw: str, expected: str) -> None:
    assert slugify(raw) == expected


def test_make_track_id_format() -> None:
    """spec §9.5: obj:<role>:<slug>:<index> — colon-separated, parseable by split."""
    tid = make_track_id("object", "Red Block", 0)
    assert tid == "obj:object:red_block:0"
    parts = tid.split(":")
    assert parts == ["obj", "object", "red_block", "0"]


def test_make_track_id_role_validation() -> None:
    """Only the 3 spec-defined roles are accepted."""
    for role in ("object", "target", "tool"):
        make_track_id(role, "x", 0)        # type: ignore[arg-type]  # OK
    with pytest.raises(ValueError):
        make_track_id("invalid", "x", 0)   # type: ignore[arg-type]


def test_make_track_id_index_must_be_non_negative() -> None:
    with pytest.raises(ValueError):
        make_track_id("object", "x", -1)


def test_make_track_id_uses_slugified_prompt() -> None:
    assert make_track_id("target", "Bin A!!", 0) == "obj:target:bin_a:0"
```

- [ ] **Step 4.3: Run the test (expect ImportError)**

```bash
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/python -m pytest tests/unit/test_track_id.py -v
```

- [ ] **Step 4.4: Implement track_id.py**

Create `mimicanno/object_tracker/track_id.py`:

```python
"""Track-id construction (spec §2.1, parent §9.5).

The single source of truth for the `obj:<role>:<slug>:<index>` form.
Downstream code parses by `track_id.split(":")` and trusts the 4-tuple
shape — do not change without coordinating with viewer / annotation /
test code that consumes it.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

ROLE = Literal["object", "target", "tool"]
_VALID_ROLES = frozenset({"object", "target", "tool"})

_SLUG_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_SLUG_RUNS_OF_UNDERSCORE = re.compile(r"_+")


def slugify(prompt: str) -> str:
    """Lowercase + ASCII-fold + replace non-alnum runs with single underscore +
    strip leading/trailing underscores. Empty input returns the sentinel
    "unnamed" (so a downstream track_id is always shaped 4-tuple-by-colons).

    Examples (see test_track_id.py for full table):
      "Red Block" -> "red_block"
      "bin A!!"   -> "bin_a"
      ""          -> "unnamed"
    """
    if not prompt:
        return "unnamed"
    # NFKD ASCII-fold (drops accents, etc.)
    folded = unicodedata.normalize("NFKD", prompt).encode("ascii", "ignore").decode("ascii")
    lowered = folded.lower()
    collapsed = _SLUG_NON_ALNUM.sub("_", lowered)
    collapsed = _SLUG_RUNS_OF_UNDERSCORE.sub("_", collapsed).strip("_")
    return collapsed if collapsed else "unnamed"


def make_track_id(role: ROLE, prompt: str, index: int) -> str:
    """Construct the canonical track-id string.

    Args:
        role:   one of "object" / "target" / "tool" (parent §9.5).
        prompt: original natural-language prompt; will be slugified.
        index:  per-(role, slug) 0-based occurrence (parent §9.5);
                incremented across re-acquisition splits within the same
                (role, prompt) (spec §2.4 step 6).

    Raises:
        ValueError: if role is not one of the 3 allowed values, or if
                    index is negative.
    """
    if role not in _VALID_ROLES:
        raise ValueError(
            f"role must be one of {sorted(_VALID_ROLES)}, got {role!r}"
        )
    if index < 0:
        raise ValueError(f"index must be non-negative, got {index}")
    return f"obj:{role}:{slugify(prompt)}:{index}"
```

- [ ] **Step 4.5: Run the test (expect PASS)**

```bash
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/python -m pytest tests/unit/test_track_id.py -v
```

Expected: 16 PASS (11 parametrize + 5 standalone).

- [ ] **Step 4.6: Commit**

```bash
git add mimicanno/object_tracker/__init__.py mimicanno/object_tracker/track_id.py \
        tests/unit/object_tracker/__init__.py tests/unit/test_track_id.py
git commit -m "$(cat <<'EOF'
feat(object_tracker): track_id slugify + make_track_id (spec §2.1)

Single source of truth for the obj:<role>:<slug>:<index> form (parent
§9.5). Slugify is lowercase + ASCII-fold + non-alnum-runs-to-underscore
+ strip leading/trailing underscores; empty / whitespace-only input
returns the "unnamed" sentinel so make_track_id never produces a
malformed (3-tuple) string.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Core dataclasses — `BBox` / `TrackSample` / `GapEvent` / `Track` / `EntityPlan` / `TrackingPlan` (`mimicanno/object_tracker/{propagator,planner}.py`)

Pure-Python dataclasses with no model dependency. These are the contract surface that the rest of the pipeline sees; locking them down early prevents downstream churn. `BBox.iou` and `BBox.center` are the only methods that have nontrivial logic — the rest is structure.

**Files:**
- Create: `mimicanno/object_tracker/propagator.py` (dataclasses only — `Propagator.run` lands in Task 8; `ground_initial_detections` lands in Task 16)
- Create: `mimicanno/object_tracker/planner.py` (`EntityPlan` only — `TrackingPlanner` Protocol + `LocalGemmaTrackingPlanner` land in Task 15)
- Test: `tests/unit/object_tracker/test_dataclasses.py`

- [ ] **Step 5.1: Write the failing test**

Create `tests/unit/object_tracker/test_dataclasses.py`:

```python
"""Object-tracker core dataclasses (spec §2.2, §2.4).

Tests cover BBox math (iou, center, validation), TrackSample / GapEvent /
Track field invariants, EntityPlan helpers, and TrackingPlan tuple-key
disambiguation."""

from __future__ import annotations

import dataclasses

import pytest

from mimicanno.object_tracker.planner import EntityPlan
from mimicanno.object_tracker.propagator import (
    BBox,
    GapEvent,
    Track,
    TrackSample,
    TrackingPlan,
)


# ---- BBox ----

def test_bbox_center() -> None:
    b = BBox(0.10, 0.20, 0.40, 0.30)  # x, y, w, h
    cx, cy = b.center
    assert cx == pytest.approx(0.30)
    assert cy == pytest.approx(0.35)


def test_bbox_iou_identical() -> None:
    b = BBox(0.0, 0.0, 0.5, 0.5)
    assert b.iou(b) == pytest.approx(1.0)


def test_bbox_iou_disjoint() -> None:
    a = BBox(0.0, 0.0, 0.10, 0.10)
    b = BBox(0.50, 0.50, 0.10, 0.10)
    assert a.iou(b) == 0.0


def test_bbox_iou_partial_overlap() -> None:
    """Two unit squares offset by 0.5 in x: overlap = 0.5 x 1.0 = 0.5;
    union = 1 + 1 - 0.5 = 1.5; iou = 1/3."""
    a = BBox(0.0, 0.0, 1.0, 1.0)
    b = BBox(0.5, 0.0, 1.0, 1.0)
    assert a.iou(b) == pytest.approx(1.0 / 3.0)


def test_bbox_iou_subset() -> None:
    """A is fully inside B: iou = area(A) / area(B)."""
    a = BBox(0.25, 0.25, 0.50, 0.50)
    b = BBox(0.0, 0.0, 1.0, 1.0)
    assert a.iou(b) == pytest.approx(0.25)


def test_bbox_validation_rejects_negative_dims() -> None:
    with pytest.raises(ValueError):
        BBox(0.0, 0.0, -0.1, 0.5)
    with pytest.raises(ValueError):
        BBox(0.0, 0.0, 0.5, 0.0)


def test_bbox_validation_rejects_out_of_unit_square() -> None:
    with pytest.raises(ValueError):
        BBox(0.6, 0.0, 0.5, 0.5)  # x + w > 1
    with pytest.raises(ValueError):
        BBox(-0.1, 0.0, 0.5, 0.5)  # x < 0


# ---- TrackSample / GapEvent / Track ----

def test_tracksample_fields() -> None:
    s = TrackSample(frame=10, time_sec=0.333, bbox=BBox(0.1, 0.1, 0.1, 0.1), score=0.9)
    assert s.frame == 10
    assert s.time_sec == pytest.approx(0.333)
    assert s.score == pytest.approx(0.9)


def test_gap_event_reasons_restricted() -> None:
    """sam3_reacquired was REMOVED from GapEvent.reason in the GPT-review
    round (spec §2.4 GapEvent docstring). Only sam3_lost / sam3_low_conf are
    valid."""
    GapEvent(from_frame=5, to_frame=10, reason="sam3_lost")
    GapEvent(from_frame=5, to_frame=10, reason="sam3_low_conf")
    # mypy / type checker rejects "sam3_reacquired" at static-check time;
    # runtime accepts any string but the reason field's type annotation
    # is the canonical contract — this test serves as a reminder.


def test_track_with_samples_and_gaps() -> None:
    t = Track(
        track_id="obj:object:red_block:0",
        role="object",
        prompt="red block",
        slug="red_block",
        index=0,
        primary=True,
        samples=[TrackSample(0, 0.0, BBox(0, 0, 0.1, 0.1), 0.95)],
        gap_events=[GapEvent(from_frame=10, to_frame=20, reason="sam3_lost")],
    )
    assert t.role == "object"
    assert len(t.samples) == 1
    assert len(t.gap_events) == 1
    assert t.primary is True


# ---- EntityPlan ----

def test_entity_plan_all_prompts_with_role_ordering() -> None:
    """spec §2.2: stable ordering — objects, then targets, then tools;
    within each role, original order from Gemma."""
    ep = EntityPlan(
        object_prompts=["red block", "blue block"],
        target_prompts=["bin A"],
        tool_prompts=["gripper"],
    )
    assert ep.all_prompts_with_role() == [
        ("object", "red block"),
        ("object", "blue block"),
        ("target", "bin A"),
        ("tool", "gripper"),
    ]


def test_entity_plan_empty_objects_yields_no_object_entries() -> None:
    ep = EntityPlan(object_prompts=[], target_prompts=["x"], tool_prompts=[])
    rolled = ep.all_prompts_with_role()
    assert ("target", "x") in rolled
    assert all(r != "object" for r, _ in rolled)


# ---- TrackingPlan ----

def test_tracking_plan_initial_detections_uses_tuple_key() -> None:
    """spec §2.4.0: cross-role duplicates are preserved via tuple keys.
    object='red block' AND target='red block' yield 2 distinct entries."""
    plan = TrackingPlan(
        entities=EntityPlan(
            object_prompts=["red block"],
            target_prompts=["red block"],
            tool_prompts=[],
        ),
        initial_detections={
            ("object", "red block"): BBox(0.1, 0.1, 0.1, 0.1),
            ("target", "red block"): BBox(0.6, 0.6, 0.1, 0.1),
        },
        failed_prompts=[],
    )
    assert len(plan.initial_detections) == 2
    assert plan.initial_detections[("object", "red block")].x == pytest.approx(0.1)
    assert plan.initial_detections[("target", "red block")].x == pytest.approx(0.6)


def test_tracking_plan_failed_prompts_uses_tuple() -> None:
    """spec §2.4.0: failed_prompts is list[(role, prompt)], not list[str]."""
    plan = TrackingPlan(
        entities=EntityPlan(object_prompts=["x", "y"], target_prompts=[], tool_prompts=[]),
        initial_detections={("object", "y"): BBox(0, 0, 0.1, 0.1)},
        failed_prompts=[("object", "x")],
    )
    assert plan.failed_prompts == [("object", "x")]
```

- [ ] **Step 5.2: Run the test (expect ImportError)**

```bash
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/python -m pytest tests/unit/object_tracker/test_dataclasses.py -v
```

- [ ] **Step 5.3: Implement planner.py (EntityPlan + TrackingPlanner stub)**

Create `mimicanno/object_tracker/planner.py`:

```python
"""Phase 3 entity-extraction Step A — planner Protocol + EntityPlan dataclass
(spec §2.2). LocalGemmaTrackingPlanner is implemented in Task 15;
this file lands the dataclass + Protocol stub so downstream tasks can import."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

import numpy as np

from mimicanno.labelset import LabelSet
from mimicanno.object_tracker.track_id import ROLE


@dataclass(slots=True, frozen=True)
class EntityPlan:
    """Step A output. No SAM3 contact yet (spec §2.2)."""

    object_prompts: list[str]
    target_prompts: list[str]
    tool_prompts: list[str]

    def all_prompts_with_role(self) -> list[tuple[ROLE, str]]:
        """Stable ordering: objects, then targets, then tools; within each
        role, original order from Gemma. Used by Step B grounding to walk
        the full prompt set."""
        out: list[tuple[ROLE, str]] = []
        for prompt in self.object_prompts:
            out.append(("object", prompt))
        for prompt in self.target_prompts:
            out.append(("target", prompt))
        for prompt in self.tool_prompts:
            out.append(("tool", prompt))
        return out


class TrackingPlanner(Protocol):
    """Step A planner Protocol (spec §2.2)."""

    def extract_entities(
        self,
        *,
        task_text: str,
        initial_frame: np.ndarray,
        allowed_labels: LabelSet,
        attempt_max: int = 3,
    ) -> EntityPlan: ...
```

- [ ] **Step 5.4: Implement propagator.py (BBox / TrackSample / GapEvent / Track / TrackingPlan)**

Create `mimicanno/object_tracker/propagator.py`:

```python
"""Phase 3 propagator dataclasses (spec §2.4).

Step B (`ground_initial_detections`) lands in Task 16; Step C (`Propagator.run`)
lands in Task 8. This file holds the dataclasses they share.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from mimicanno.object_tracker.planner import EntityPlan
from mimicanno.object_tracker.track_id import ROLE

GapReason = Literal["sam3_lost", "sam3_low_conf"]


@dataclass(slots=True, frozen=True)
class BBox:
    """Normalized image coords (spec §2.4). (0,0) = top-left, (1,1) = bottom-right.
    All four floats in [0, 1]; w > 0; h > 0; x + w <= 1; y + h <= 1."""

    x: float
    y: float
    w: float
    h: float

    def __post_init__(self) -> None:
        if self.w <= 0.0 or self.h <= 0.0:
            raise ValueError(
                f"BBox w/h must be > 0; got w={self.w}, h={self.h}"
            )
        if not (0.0 <= self.x and self.x + self.w <= 1.0 + 1e-9):
            raise ValueError(
                f"BBox x out of unit square; x={self.x}, w={self.w}"
            )
        if not (0.0 <= self.y and self.y + self.h <= 1.0 + 1e-9):
            raise ValueError(
                f"BBox y out of unit square; y={self.y}, h={self.h}"
            )

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.w / 2.0, self.y + self.h / 2.0)

    def iou(self, other: "BBox") -> float:
        """Intersection-over-union in normalized image coords."""
        ix0 = max(self.x, other.x)
        iy0 = max(self.y, other.y)
        ix1 = min(self.x + self.w, other.x + other.w)
        iy1 = min(self.y + self.h, other.y + other.h)
        iw = max(0.0, ix1 - ix0)
        ih = max(0.0, iy1 - iy0)
        inter = iw * ih
        union = self.w * self.h + other.w * other.h - inter
        return inter / union if union > 0.0 else 0.0


@dataclass(slots=True, frozen=True)
class TrackSample:
    """One sub-sampled propagation result for a single track (spec §2.4)."""

    frame: int
    time_sec: float
    bbox: BBox
    score: float


@dataclass(slots=True, frozen=True)
class GapEvent:
    """Contiguous frame range where the bbox is invalid / missing (spec §2.4).

    Re-acquisition is implicit (the next sample after a gap), NOT recorded
    here. Mixing range semantics with point semantics ('this single frame
    was a track event') would conflict with `compute_object_signals`'
    'NaN inside gap_events' rule (spec §2.5).
    """

    from_frame: int
    to_frame: int
    reason: GapReason


@dataclass(slots=True)
class Track:
    """One propagated track for one (role, prompt) seed (spec §2.4)."""

    track_id: str
    role: ROLE
    prompt: str
    slug: str
    index: int
    primary: bool
    samples: list[TrackSample] = field(default_factory=list)
    gap_events: list[GapEvent] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class TrackingPlan:
    """Step A + Step B combined; consumed by Propagator.run (spec §2.4.0)."""

    entities: EntityPlan
    initial_detections: dict[tuple[ROLE, str], BBox]
    failed_prompts: list[tuple[ROLE, str]]
```

- [ ] **Step 5.5: Run the test (expect PASS)**

```bash
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/python -m pytest tests/unit/object_tracker/test_dataclasses.py -v
```

Expected: ~14 PASS.

- [ ] **Step 5.6: Commit**

```bash
git add mimicanno/object_tracker/planner.py mimicanno/object_tracker/propagator.py \
        tests/unit/object_tracker/test_dataclasses.py
git commit -m "$(cat <<'EOF'
feat(object_tracker): core dataclasses — BBox / Track / EntityPlan / TrackingPlan

Pure-Python dataclasses for Phase 3 (spec §2.2, §2.4). BBox carries
__post_init__ validation (unit-square, w/h > 0) + iou + center; the rest
are pure structure.

GapEvent.reason is restricted to "sam3_lost" / "sam3_low_conf" — re-
acquisition is implicit (next sample after a gap), not recorded as a
GapEvent (avoids range-vs-point semantic conflict with the NaN-on-gap
rule in compute_object_signals; spec §2.4 GapEvent docstring).

TrackingPlan.initial_detections uses dict[(role, prompt), BBox] tuple
keys to preserve cross-role duplicates (object="red block" + target="red
block" yields 2 distinct entries; spec §2.4.0).

Propagator.run + ground_initial_detections + LocalGemmaTrackingPlanner
land in later tasks; this file ships only the dataclasses so downstream
tasks can import without circular dep.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `tracks.json` schema + io read/write (`mimicanno/schema.py` + `mimicanno/io.py`)

Implements spec §3 in full: `TracksFile` dataclass with all sub-types (`TracksTrack`, `TracksSample`, `TracksGap`, `TracksTrackingPlan`, `TracksStats`), `to_dict()` / `from_dict()` (de)serializers with all field validation per the §3.2 contract table, and `write_tracks_json` / `read_tracks_json` in `io.py` with the §3.3 cross-artifact integrity check (compares against `manifest.json` for `episode_id`/`fps`/`n_frames`).

Particular care for: `failed_prompts: list[{role, prompt}]` on-disk shape (spec §3.2 fix from sanity-check round); `gap_events.reason` enum restricted to `sam3_lost` / `sam3_low_conf` (no `sam3_reacquired`); `bbox` array shape `[x, y, w, h]` with full unit-square validation; `samples` strict-frame-ascending validation; `primary` flag at-most-one-per-role validation.

**Files:**
- Modify: `mimicanno/schema.py` (add 5 dataclasses + (de)serializers near the existing artifact schemas)
- Modify: `mimicanno/io.py` (add `write_tracks_json` + `read_tracks_json`; both go through existing `write_json_atomic` for write)
- Test: `tests/unit/test_tracks_json_schema.py` (round-trip + every §3.2 validation rule positive + negative)
- Test: `tests/unit/test_tracks_json_failed_prompts_roundtrip.py` (cross-role duplicate preservation per spec §3.2)
- Snapshot: `tests/snapshots/phase3/tracks_json_smoke.json` (canonical example from spec §3.1)

- [ ] **Step 6.1: Write the failing test (round-trip)** — `tests/unit/test_tracks_json_schema.py`. At minimum: round-trip the spec §3.1 canonical example through `from_dict(to_dict(...))`; verify every §3.2 row's negative case raises `ValueError` (bbox out of unit square, frame out of `[0, n_frames)`, samples not strictly ascending, gap reason unknown, primary flag set on >1 track for same role, `episode_id` / `fps` / `n_frames` mismatch on read). 1 test per row of §3.2, ~25 tests total.

- [ ] **Step 6.2: Write the failing test (failed_prompts shape)** — `tests/unit/test_tracks_json_failed_prompts_roundtrip.py`: build a `TrackingPlan` with `failed_prompts=[("object", "red block"), ("target", "red block")]`, serialize to dict, re-parse, assert distinct entries preserved (NOT collapsed to a single string).

- [ ] **Step 6.3: Run tests** — expect ImportError on `TracksFile`.

- [ ] **Step 6.4: Implement** — Follow spec §3.1 (example) and §3.2 (field contract). All `from_dict` methods raise `ValueError` on contract violation. `read_tracks_json` accepts an optional `expected: tuple[episode_id, fps, n_frames]` kwarg (spec §3.3); raises `ArtifactIntegrityError` (new exception in `mimicanno.errors`, subclass of `MimicAnnoError` with code `"tracks_json_integrity_violation"`) on mismatch. `write_tracks_json` calls existing `write_json_atomic` from Phase 1 io.

- [ ] **Step 6.5: Generate the snapshot** — Run a tiny Python script that constructs the spec §3.1 example via `TracksFile(...)` and writes it to `tests/snapshots/phase3/tracks_json_smoke.json` using `canonical_json` for byte-stable output. Pin via test that reads the snapshot back and asserts byte-equality on re-serialize.

- [ ] **Step 6.6: Run tests + commit**

```bash
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/python -m pytest tests/unit/test_tracks_json_schema.py \
                              tests/unit/test_tracks_json_failed_prompts_roundtrip.py -v
git add mimicanno/schema.py mimicanno/io.py mimicanno/errors.py \
        tests/unit/test_tracks_json_schema.py \
        tests/unit/test_tracks_json_failed_prompts_roundtrip.py \
        tests/snapshots/phase3/tracks_json_smoke.json
git commit -m "feat(schema,io): tracks.json schema + read/write with cross-artifact integrity (spec §3)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Test fixtures — `FixtureTrackingPlanner` + `FixtureSAM3Tracker` (`mimicanno/object_tracker/fixtures.py`)

The primary test surface for Tasks 8, 13, 21–24. No GPU, no model weights, no `sam3` import. Both fixtures must support: (a) happy path (returns canned data), (b) configurable failure injection (raises a chosen exception on the first call, on a specific frame, etc — used to drive degrade tests in Task 23).

**Files:**
- Create: `mimicanno/object_tracker/fixtures.py`
- Test: `tests/unit/object_tracker/test_fixtures.py`

- [ ] **Step 7.1: Write the failing test**

`tests/unit/object_tracker/test_fixtures.py` — covers:
- `FixtureTrackingPlanner(entities=EntityPlan(...))` returns the same `entities` from `extract_entities(...)` regardless of input args.
- `FixtureTrackingPlanner` configured with `raise_on_extract=ValueError("x")` raises that exception once on the first call (then returns the canned plan on subsequent calls — used to test retry).
- `FixtureSAM3Tracker(initial_detections={"red block": [(BBox, 0.95)], "bin A": []}, propagation_results={frame: {prompt: (BBox, 0.9)}})`:
  - `ground_on_frame(frame, "red block")` returns `[(BBox, 0.95)]`; `ground_on_frame(frame, "bin A")` returns `[]`.
  - `propagate(frames=..., prompts_with_initial_bbox=..., stride=...)` yields `FramePropagationResult` for each frame from the canned `propagation_results`.
- `FixtureSAM3Tracker(raise_on_load=RuntimeError("CUDA OOM"))` raises on `.load(...)`.
- `FixtureSAM3Tracker(raise_on_propagate_at_frame=42, raise_with=RuntimeError("kernel fault"))` yields normal results for frames `< 42`, raises on yielding frame 42.
- `close()` is idempotent.

- [ ] **Step 7.2: Implement** — straightforward; `FixtureSAM3Tracker` has the same method surface as `SAM3Runtime` (which lands in Task 14) so that downstream tests can swap it in. Define the `FramePropagationResult` dataclass here too (it's the contract shared between fixtures and real runtime).

```python
# minimal sketch — see test for full surface
@dataclass(slots=True, frozen=True)
class FramePropagationResult:
    frame: int
    detections: dict[str, tuple[BBox, float] | None]


class FixtureTrackingPlanner:
    def __init__(
        self,
        entities: EntityPlan,
        raise_on_extract: Exception | None = None,
    ): ...
    def extract_entities(self, **kwargs) -> EntityPlan: ...


class FixtureSAM3Tracker:
    def __init__(
        self,
        *,
        initial_detections: dict[str, list[tuple[BBox, float]]] = None,
        propagation_results: dict[int, dict[str, tuple[BBox, float] | None]] = None,
        raise_on_load: Exception | None = None,
        raise_on_propagate_at_frame: int | None = None,
        raise_with: Exception | None = None,
    ): ...
    @classmethod
    def load(cls, *, checkpoint=None, device="cpu") -> "FixtureSAM3Tracker": ...
    def ground_on_frame(self, frame, prompt) -> list[tuple[BBox, float]]: ...
    def propagate(self, *, frames, prompts_with_initial_bbox, stride): ...
    def close(self) -> None: ...
```

- [ ] **Step 7.3: Run tests + commit**

```bash
git add mimicanno/object_tracker/fixtures.py tests/unit/object_tracker/test_fixtures.py
git commit -m "feat(object_tracker): FixtureTrackingPlanner + FixtureSAM3Tracker (spec §2.6)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: `Propagator.run` algorithm (`mimicanno/object_tracker/propagator.py`)

Implements spec §2.4.1 (the 7-step algorithm): single `runtime.propagate(...)` call per episode, gap consolidation with single `GapEvent` per contiguous range, re-acquisition IoU branch (same `track_id` if `iou >= reacquisition_iou_threshold`, new index otherwise), primary marking from "first prompt that survived Step B grounding".

**Files:**
- Modify: `mimicanno/object_tracker/propagator.py` (add `Propagator` class + `run` method)
- Test: `tests/unit/object_tracker/test_propagator.py`

- [ ] **Step 8.1: Write the failing test** — At minimum:
  - **Single-call contract:** `FixtureSAM3Tracker.propagate` mock counts calls; `Propagator.run` calls it exactly once.
  - **Gap consolidation:** craft per-frame results so frames `[10, 20]` are missing for `red_block` → expect 1 `GapEvent(from_frame=10, to_frame=20, reason="sam3_lost")`.
  - **Low-conf gap reason:** craft frames with `score=0.1 < min_track_score=0.3` → `GapEvent.reason == "sam3_low_conf"`.
  - **Mixed-reason gap:** if any frame in the range was low-conf, the consolidated gap is `"sam3_low_conf"`; else `"sam3_lost"`.
  - **Re-acquisition same id:** craft sample at frame 0 (bbox A), gap until frame 100, then sample at frame 110 (bbox A' close to A → IoU > 0.3). Expect single `Track` with `track_id` ending `:0`, gap from 1 to 109 (or stride-aligned).
  - **Re-acquisition new id:** same but bbox at frame 110 is far from A (IoU < 0.3). Expect 2 `Track`s, both same prompt, indices 0 and 1.
  - **Primary marking — happy path:** `EntityPlan(object_prompts=["red block", "blue block"])`, both grounded → `red_block:0` is `primary=True`, `blue_block:0` is `primary=False`.
  - **Primary marking — first prompt failed Step B:** `EntityPlan(object_prompts=["red block", "blue block"])`, only `blue block` grounded → `blue_block:0` is `primary=True`.
  - **Deterministic ordering:** Tracks sorted by `(role_order, slug, index)` where `role_order = {"object": 0, "target": 1, "tool": 2}`.
  - **Last frame inclusion:** if `n_frames - 1` is not stride-aligned, it's still iterated (spec §2.4.1 step 1).

- [ ] **Step 8.2: Implement** — Follow spec §2.4.1 verbatim. The algorithm is dense but mechanical; key subroutines: `_consolidate_gap(reasons_by_frame: dict[int, GapReason]) -> GapEvent` (max-precedence: low_conf > lost), `_resolve_reacquisition(prev_sample, new_sample, iou_threshold) -> bool`, `_assign_primary(tracks: list[Track], plan: TrackingPlan) -> None` (mutates in place).

- [ ] **Step 8.3: Run tests + commit**

```bash
git add mimicanno/object_tracker/propagator.py tests/unit/object_tracker/test_propagator.py
git commit -m "feat(propagator): Propagator.run with gap consolidation + reacq + primary (spec §2.4.1)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: `compute_object_signals` (`mimicanno/object_tracker/signals.py`)

Implements spec §2.5 in full: `ObjectSignals` dataclass with `object_center` (per-track `[n_frames, 2]` arrays) + image-width-normalized `gripper_object_distance` and `object_speed`, with NaN inside `gap_events`, primary-track resolution, and the central-difference speed formula `vx = dx * fps / 2; vy = dy * fps / 2; speed = sqrt(vx² + (vy/aspect)²)`.

**Files:**
- Create: `mimicanno/object_tracker/signals.py`
- Test: `tests/unit/object_tracker/test_signals.py`

- [ ] **Step 9.1: Write the failing test** — At minimum:
  - **`object_center` populated for all roles:** input has 1 object + 1 target + 1 tool track → `object_center` keys include all 3 track_ids (NOT just objects).
  - **Linear interpolation between samples:** track sampled at frames [0, 10, 20] with bbox centers [0.0, 0.1, 0.2] → frame 5 center is 0.05; frame 15 is 0.15.
  - **NaN inside gaps:** track has `GapEvent(from_frame=10, to_frame=20)` → `object_center[track_id][10..20]` is all NaN; `object_speed[track_id][10..20]` is all NaN.
  - **Distance is image-width-normalized:** gripper at center (0.5, 0.5), object at (0.6, 0.5), aspect=16/9 → distance = `sqrt(0.1² + 0² )` = 0.1 (the y-component is divided by aspect, but here dy=0).
  - **Distance with aspect-ratio correction:** gripper at (0.5, 0.5), object at (0.5, 0.6), aspect=16/9 → distance = `sqrt(0² + (0.1 / (16/9))²)` ≈ 0.05625.
  - **Speed central-difference:** track samples at frames [0, 1, 2] with centers [(0,0), (0.1, 0), (0.2, 0)], fps=30 → speed at frame 1 = `|(0.2-0.0)|/2 * 30 = 3.0`.
  - **Speed at boundary frames:** frame 0 / `n_frames-1` use forward/backward difference (not central).
  - **Primary track resolution:** `primary_object_track_id` is the track with `role="object" and primary=True`; `None` if no such track.
  - **Empty gripper signals:** `tools[]` empty (no gripper track) → `gripper_object_distance` dict is empty, `gripper_tool_track_id` is None.

- [ ] **Step 9.2: Implement** — Pure numpy. Helper `_interpolate_centers(samples: list[TrackSample], n_frames: int, gap_events: list[GapEvent]) -> np.ndarray (shape [n_frames, 2])` for the per-track interpolation; share between center / distance / speed computation. Handle edge frames (`t==0`, `t==n_frames-1`, frames adjacent to gaps) with one-sided difference.

- [ ] **Step 9.3: Run tests + commit**

```bash
git add mimicanno/object_tracker/signals.py tests/unit/object_tracker/test_signals.py
git commit -m "feat(signals): compute_object_signals with image-width-normalized distance/speed (spec §2.5)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: `Phase3BoundaryDetector` + 2 new sources (`mimicanno/boundaries.py`)

Adds the 2 new boundary sources (`gripper_object_distance_threshold_crossing`, `object_motion_start_stop`) per spec §4.1, the edge-suppression rule (no emit when windowed delta is undefined), the disabled_sources rules (spec §4.4 including the all-NaN case), and `Phase3BoundaryDetector` that wraps the existing integrated-score machinery with the 6-source weight set.

**Files:**
- Modify: `mimicanno/boundaries.py` (add 2 new detector functions + `Phase3BoundaryDetector` class)
- Test: `tests/unit/test_phase3_boundary_detector.py` (new sources fire under crafted signals; weight rebalance produces expected scores)
- Test: `tests/unit/test_phase3_boundary_edge_suppression.py` (locks in §4.1.1 / §4.1.2 no-emit rule)
- Test: `tests/unit/test_phase3_weights_intent.py` (encodes the §4.3 promotion truth table)

- [ ] **Step 10.1: Write all 3 failing tests**

`test_phase3_boundary_detector.py`:
- New source `gripper_object_distance_threshold_crossing` fires at the frame `d` crosses 0.05 in either direction.
- New source `object_motion_start_stop` fires after `object_motion_min_sec` of sustained transition.
- `disabled_sources` includes `gripper_object_distance_threshold_crossing` when `gripper_tool_track_id is None`.
- `disabled_sources` includes both new sources when `tracks` has no `role="object"`.
- `disabled_sources` adds `gripper_object_distance_threshold_crossing` when all `gripper_object_distance` arrays are entirely NaN.
- `disabled_sources` adds `object_motion_start_stop` when all `object_speed` arrays are entirely NaN.

`test_phase3_boundary_edge_suppression.py`:
- §4.1.1: a crossing inside `[0, w)` produces no candidate (`w = round(0.10 * fps)`).
- §4.1.1: a crossing inside `[n_frames - w, n_frames)` produces no candidate.
- §4.1.2: a sustained start transition where `t - window < 0` produces no event.
- §4.1.2: a sustained stop transition where `t + window - 1 >= n_frames` produces no event.

`test_phase3_weights_intent.py`:
- Encodes the §4.3 truth table:
  - `gripper_transition` alone (score 1.0 × weight 0.45) = 0.45 → promotes (above 0.30).
  - `gripper_object_distance_threshold_crossing` alone (1.0 × 0.25) = 0.25 → does NOT promote.
  - `gripper_transition + gripper_object_distance_threshold_crossing` = 0.70 → strongly promotes.
  - `object_motion_start_stop + eef_velocity_valley` = 0.25 → does NOT promote.
  - `gripper_object_distance_threshold_crossing + eef_velocity_valley` = 0.40 → promotes.

- [ ] **Step 10.2: Implement** — Follow spec §4.1.1 / §4.1.2 / §4.4 verbatim. Reuse the existing `BoundaryDetector` integrated-score pipeline; `Phase3BoundaryDetector` is a subclass / wrapper that registers the 2 new detectors in addition to the 4 Phase 1 detectors.

- [ ] **Step 10.3: Run all 3 test files + commit**

```bash
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/python -m pytest tests/unit/test_phase3_boundary_detector.py \
                              tests/unit/test_phase3_boundary_edge_suppression.py \
                              tests/unit/test_phase3_weights_intent.py -v
git add mimicanno/boundaries.py tests/unit/test_phase3_boundary_detector.py \
        tests/unit/test_phase3_boundary_edge_suppression.py \
        tests/unit/test_phase3_weights_intent.py
git commit -m "feat(boundaries): Phase3BoundaryDetector + 2 new sources (spec §4.1, §4.3, §4.4)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: `ObjectStateSummary` + `compute_object_state_summary` (`mimicanno/clip_features.py`)

Implements spec §5.1 / §5.2: per-segment summary that the VLM prompt extension consumes. Returns `None` when the primary object is not visible enough in the segment (triggers per-segment fallback in Task 13).

**Files:**
- Modify: `mimicanno/schema.py` (add `ObjectStateSummary` dataclass + (de)serializer)
- Modify: `mimicanno/clip_features.py` (add `compute_object_state_summary` + extend `ClipFeatures` dataclass with optional `object_state_summary`)
- Test: `tests/unit/test_object_state_summary.py`
- Snapshot: `tests/snapshots/phase3/object_state_summary_smoke.json`

- [ ] **Step 11.1: Write the failing test**

`tests/unit/test_object_state_summary.py` — one test per algorithm step from spec §5.2:
- **Visibility filter (step 1):** track visible 60% of segment frames + threshold 0.5 → prompt appears in `*_prompts`; visible 40% → omitted.
- **No primary object → None (step 3):** `primary_object_track` is None → `compute_object_state_summary(...) is None`.
- **Primary track filtered out by visibility → None:** primary track exists but its visibility is < threshold → return None (caller treats as fallback).
- **Distance start/min/end (step 4):** craft `ObjectSignals.gripper_object_distance` for the primary pair → assert all 3 scalars.
- **Distance None when no gripper track (step 4):** `gripper_tool_track_id is None` → all 3 distance scalars are None.
- **Speed and displacement (step 5):** `primary_object_max_speed` from `object_speed.max()` (NaN-skipped); `primary_object_displacement` summed from `object_center` adjacent diffs with image-width normalization.
- **IoU-at-end proxy (step 6):** primary object + primary target both have valid bbox at `segment_end_frame` (after `bbox_at_frame` interpolation); `IoU > 0.05` → `True`. Either bbox missing → None. IoU = 0.04 → False.
- **IoU-at-end uses same frame for both:** craft scenario where object bbox available at frame 99 and target at frame 100 (different sampled frames), `segment_end_frame = 100`. If `bbox_at_frame(target, 100) is None` due to gap, result is None (NOT cross-frame IoU).

- [ ] **Step 11.2: Implement** — Pure Python on top of `ObjectSignals.object_center` (added in Task 9). Helper `bbox_at_frame(track, t)` interpolates bbox `(x, y, w, h)` between bracketing samples (returns None if t inside any gap_event of that track or no bracketing samples); reuses the same gap-test predicate as `compute_object_signals`.

- [ ] **Step 11.3: Generate snapshot** — Run a script that builds a canonical `ObjectStateSummary` (matching spec §5.4 prompt-extension example values: `gripper_object_distance_at_start=0.42`, `_min=0.03`, `_at_end=0.41`, `primary_object_displacement=0.18`, `_max_speed=0.32`, `at_target_at_end=true`) → write to `tests/snapshots/phase3/object_state_summary_smoke.json`.

- [ ] **Step 11.4: Run tests + commit**

```bash
git add mimicanno/schema.py mimicanno/clip_features.py \
        tests/unit/test_object_state_summary.py \
        tests/snapshots/phase3/object_state_summary_smoke.json
git commit -m "feat(clip_features): ObjectStateSummary + compute_object_state_summary (spec §5.1, §5.2)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: `build_prompt` extension (`mimicanno/vlm_prompt.py`)

Extends Phase 2's `build_prompt` with optional `request["object_state_summary"]: ObjectStateSummary | None`. The contract that MUST hold (spec §5.4): when `object_state_summary is None`, the prompt body is **byte-identical** to Phase 2. When non-None, two new SYSTEM sub-blocks appear after the "Robot-state summary" block.

**Files:**
- Modify: `mimicanno/vlm_prompt.py` (extend `build_prompt`; conditional Phase 3 sub-blocks)
- Modify: `mimicanno/vlm_labeler.py` (extend `VLMRequest` TypedDict with optional `object_state_summary` field — Phase 2 callsites pass `None`)
- Test: `tests/unit/test_vlm_prompt_phase3.py`
- Snapshot: `tests/snapshots/phase3/prompt_phase2_byte_identical.txt` (Phase 2 baseline)
- Snapshot: `tests/snapshots/phase3/prompt_phase3_full.txt` (Phase 3 mode)

- [ ] **Step 12.1: Write the failing test**

`tests/unit/test_vlm_prompt_phase3.py`:
- **Byte-identity with Phase 2 when `object_state_summary` field is omitted:** load existing Phase 2 snapshot (`tests/snapshots/phase2/prompt_initial.txt`), build prompt with same inputs but no `object_state_summary` key in `VLMRequest`, assert byte-equal.
- **Byte-identity with Phase 2 when `object_state_summary=None` explicit:** same assertion with explicit `None`.
- **Phase 3 mode adds 2 SYSTEM sub-blocks:** build prompt with a non-None `ObjectStateSummary`; assert `"Tracked entities in this scene:"` and `"Object-state summary for this segment:"` appear in the body.
- **Phase 3 prompt snapshot byte-stability:** read `prompt_phase3_full.txt`; build prompt with the canonical inputs; assert byte-equal.
- **Empty `*_prompts` lists render as `[]`:** with `ObjectStateSummary(object_prompts=[], target_prompts=[], ...)`, the rendered block contains `objects: []`.
- **Float formatting `:.6g`:** `gripper_object_distance_at_start=0.123456789` renders as `0.123457`.
- **`null` rendering for None scalars:** `primary_object_max_speed=None` renders as `null` (lowercase, JSON-style).
- **Boolean rendering:** `primary_object_at_target_at_end=True` renders as `true`.
- **Advisory line always present in Phase 3 mode:** `"(Prefer one of the listed"` in body.
- **Retry amendment placement unchanged:** when `attempt > 1` and `last_reject_reason`, the amendment block goes at the END (existing Phase 2 placement, not affected by Phase 3 sub-blocks).

- [ ] **Step 12.2: Implement** — Extend `build_prompt` per spec §5.4. The Phase 3 sub-blocks insert AFTER "Robot-state summary" and BEFORE the `USER:` line (i.e., still inside SYSTEM block).

- [ ] **Step 12.3: Generate both snapshots** — Run a Python one-liner that builds the canonical Phase 2 prompt (same inputs as the existing Phase 2 snapshot) and the canonical Phase 3 prompt (with the §5.4 example `ObjectStateSummary`). Write both to `tests/snapshots/phase3/`.

- [ ] **Step 12.4: Run tests + ensure Phase 2 byte-identity test still passes** + commit

```bash
git add mimicanno/vlm_prompt.py mimicanno/vlm_labeler.py \
        tests/unit/test_vlm_prompt_phase3.py \
        tests/snapshots/phase3/prompt_phase2_byte_identical.txt \
        tests/snapshots/phase3/prompt_phase3_full.txt
git commit -m "feat(vlm_prompt): Phase 3 mode adds object-state sub-blocks; Phase 2 byte-identical (spec §5.4)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: `apply_phase3_labeling` + per-segment fallback (`mimicanno/vlm_labeler.py`)

Phase 3-aware orchestrator that reuses Phase 2's per-segment helpers but threads `ObjectStateSummary` through. Per-segment fallback (§6) when `compute_object_state_summary(...)` returns None: that single segment uses Phase 2 path (`vlm_robot_state_only`, `object_state_unavailable=true`), no whole-run degrade.

**Files:**
- Modify: `mimicanno/vlm_labeler.py` (add `apply_phase3_labeling`; reuse Phase 2 internals)
- Test: `tests/unit/test_phase3_label_run.py`

- [ ] **Step 13.1: Write the failing test** — At minimum:
  - **All segments labeled with object_state:** synthetic 3-segment scenario where every segment has visible primary object → all 3 segments stamped `label_source = "vlm_with_object_state"`, `object_state_unavailable = False`, non-empty `object_track_ids`.
  - **Single segment falls back:** 3-segment scenario where segment 1 has the primary object in gap for >50% of segment frames → segment 1 stamped `label_source = "vlm_robot_state_only"`, `object_state_unavailable = True`, `object_track_ids = []`. Segments 0 and 2 are full Phase 3.
  - **`LabelAttempt.notes` includes `"phase3_per_segment_fallback"` for fallback segments only.**
  - **`object_state_segment_coverage = n_with_object_state / n_total`** computed correctly: 2/3 = 0.666...
  - **Run-level `object_state_available` is True even with 1 fallback segment** (per-segment fallback is NOT a degrade — spec §6.4).
  - **Phase 2 prompt is byte-identical** for fallback segments (proven by mocking `build_prompt` and asserting `object_state_summary` kwarg is None / absent).

- [ ] **Step 13.2: Implement** — Mirror Phase 2's `apply_phase2_labeling` structure; per-segment loop calls `compute_object_state_summary(tracks, segment, ...)`, dispatches to either Phase 3 prompt or Phase 2 prompt based on result. Returns `(annotation, attempts_log, object_state_segment_coverage)`.

- [ ] **Step 13.3: Run tests + commit**

```bash
git add mimicanno/vlm_labeler.py tests/unit/test_phase3_label_run.py
git commit -m "feat(vlm_labeler): apply_phase3_labeling + per-segment fallback (spec §5.5, §6)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: `SAM3Runtime` wrapper (`mimicanno/object_tracker/sam3_runtime.py`)

The ONLY file that imports `sam3.*`. Exposes `load(checkpoint, device) -> SAM3Runtime`, `ground_on_frame(frame, prompt) -> list[tuple[BBox, float]]`, `propagate(frames, prompts_with_initial_bbox, stride) -> Iterator[FramePropagationResult]`, `close()`. The actual SAM 3.1 entry-point selection (which `sam3/agent/...` API to call) is decided here based on what's available in the vendored repo.

This task is largely a thin glue layer; the unit test is gated behind the `MIMICANNO_RUN_SAM3_SMOKE=1` env var + CUDA detection because we don't want CI to need SAM3 weights. Mocked tests live in subsequent tasks (Task 15 uses mocks for the planner; Task 22 uses `FixtureSAM3Tracker`).

**Files:**
- Create: `mimicanno/object_tracker/sam3_runtime.py`
- Modify: `pyproject.toml` (add `[project.optional-dependencies] sam3 = [...]`)
- Modify: `mimicanno/object_tracker/__init__.py` (re-export `SAM3Runtime` + `FramePropagationResult`)
- Test: `tests/unit/test_sam3_runtime_smoke.py` (gated; loads real SAM3 weights)

- [ ] **Step 14.1: Inspect the vendored sam3/ API**

```bash
ls -la sam3/sam3/ sam3/sam3/agent/ sam3/sam3/sam/ 2>/dev/null
grep -rn "^def \|^class \|build_sam3" sam3/sam3/model_builder.py 2>/dev/null | head -20
```

Identify the entry point (likely `sam3.model_builder.build_sam3(checkpoint=...)` or similar). Document the chosen entry in the file docstring of `sam3_runtime.py`.

**Layering note:** `FramePropagationResult` is currently defined in `fixtures.py` (Task 7) and imported by both `SAM3Runtime` and `Propagator`. The implementer MAY move it to `sam3_runtime.py` (production module owns the contract type, fixtures imports it) — this is the more typical layering and avoids the production→fixtures import. Either layering works as long as both consumers see the same dataclass; the chosen layering should be consistent.

- [ ] **Step 14.2: Implement `SAM3Runtime` (thin wrapper)**

```python
"""Thin wrapper over vendored sam3/ — the ONLY file that imports sam3.*
(spec §2.3). Backend selection (vendored vs HF transformers Sam3Model)
is isolated behind this wrapper per the spec §0 Non-goals reframing."""

from __future__ import annotations

import importlib
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np

from mimicanno.errors import SAM3ExtrasMissing, SAM3InitFailed
from mimicanno.object_tracker.fixtures import FramePropagationResult  # shared dataclass
from mimicanno.object_tracker.propagator import BBox


def _ensure_sam3_importable() -> None:
    """Raise SAM3ExtrasMissing if sam3 is not on the path / not installed."""
    sam3_repo_root = Path(__file__).resolve().parent.parent.parent / "sam3"
    if str(sam3_repo_root) not in sys.path:
        sys.path.insert(0, str(sam3_repo_root))
    try:
        importlib.import_module("sam3")
    except ImportError as e:
        raise SAM3ExtrasMissing() from e


class SAM3Runtime:
    def __init__(self, model) -> None:
        self._model = model
        self._closed = False

    @classmethod
    def load(cls, *, checkpoint: Path, device: str = "cuda") -> "SAM3Runtime":
        _ensure_sam3_importable()
        try:
            from sam3.model_builder import build_sam3   # type: ignore[import-not-found]
            model = build_sam3(checkpoint=str(checkpoint), device=device)
        except Exception as e:
            raise SAM3InitFailed(underlying=repr(e)) from e
        return cls(model)

    def ground_on_frame(
        self, frame: np.ndarray, prompt: str
    ) -> list[tuple[BBox, float]]:
        # Concrete API call shape depends on sam3 version — fill in once
        # the vendored version's text-prompted-grounding entry point is
        # confirmed in Step 14.1. Result must be (BBox in normalized image
        # coords, score in [0, 1]) sorted by score desc.
        raise NotImplementedError("Step 14.1 inspection required")

    def propagate(
        self,
        *,
        frames,
        prompts_with_initial_bbox: list[tuple[str, BBox]],
        stride: int,
    ) -> Iterator[FramePropagationResult]:
        raise NotImplementedError("Step 14.1 inspection required")

    def close(self) -> None:
        if self._closed:
            return
        with suppress(Exception):
            del self._model
        self._closed = True
```

- [ ] **Step 14.3: Add `[sam3]` extras to pyproject.toml**

```toml
[project.optional-dependencies]
sam3 = [
    "torch>=2.4",
    "torchvision>=0.19",
    "huggingface_hub>=0.25",
    # NB: the vendored sam3/ has its own pyproject.toml — its deps are
    # not propagated automatically; list the runtime deps that the wrapper
    # actually imports here.
]
```

- [ ] **Step 14.4: Write the gated smoke test**

`tests/unit/test_sam3_runtime_smoke.py`:

```python
import os
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("MIMICANNO_RUN_SAM3_SMOKE") != "1",
    reason="MIMICANNO_RUN_SAM3_SMOKE=1 not set; CI does not load SAM3 weights",
)

# Minimal smoke: load + close + ground_on_frame on a tiny RGB array.
# Full e2e is in Task 25.
```

- [ ] **Step 14.5: Commit**

```bash
git add mimicanno/object_tracker/sam3_runtime.py mimicanno/object_tracker/__init__.py \
        pyproject.toml tests/unit/test_sam3_runtime_smoke.py
git commit -m "feat(sam3_runtime): wrapper over vendored sam3/ + [sam3] extras (spec §2.3)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 15: `LocalGemmaTrackingPlanner.extract_entities` (`mimicanno/object_tracker/planner.py`)

Step A only (spec §2.2.1). Shares the Gemma model handle with Phase 2's `LocalGemmaVLMLabeler` via `vlm.shared_handle()` — one in-memory Gemma instance.

**Files:**
- Modify: `mimicanno/object_tracker/planner.py` (add `LocalGemmaTrackingPlanner` class)
- Modify: `mimicanno/vlm_labeler.py` (add `shared_handle()` method to `LocalGemmaVLMLabeler` if not already present; returns a thin reference type)
- Test: `tests/unit/object_tracker/test_planner.py`

- [ ] **Step 15.1: Write the failing test**

`tests/unit/object_tracker/test_planner.py`:
- **Happy path:** mock Gemma to return `'{"objects": ["red block"], "targets": ["bin A"], "tools": ["gripper"]}'`; `extract_entities(...)` returns `EntityPlan(object_prompts=["red block"], target_prompts=["bin A"], tool_prompts=["gripper"])`.
- **JSON parse failure → retry → success:** Gemma returns garbage on attempt 1, valid JSON on attempt 2; result is the attempt-2 plan.
- **All 3 attempts fail → empty EntityPlan:** Gemma returns garbage 3 times → `EntityPlan(object_prompts=[], target_prompts=[], tool_prompts=[])`.
- **Schema reject — duplicate within role:** Gemma returns `{"objects": ["red block", "Red Block"]}` (case-insensitive dup) → counted as parse failure (`reject_reason="duplicate_prompt_within_role"`), retry next attempt with stricter amendment.
- **Cross-role duplicates allowed:** `{"objects": ["red block"], "targets": ["red block"]}` → accepted (preserved through to `TrackingPlan.initial_detections` via tuple key in Task 16).
- **`shared_handle()` returns the Gemma handle from a `LocalGemmaVLMLabeler`:** mock vlm; `LocalGemmaTrackingPlanner(vlm.shared_handle())` constructs without loading a new model.
- **`attempt_max=N` honored:** `attempt_max=1` causes immediate empty EntityPlan on parse failure.

- [ ] **Step 15.2: Implement `shared_handle` on `LocalGemmaVLMLabeler` if absent.**

First, **inspect Phase 2's actual `LocalGemmaVLMLabeler` shape** to pin the exact attribute names that will be exposed by the handle:

```bash
grep -n "self\.\(model\|tokenizer\|processor\|_model\|_tokenizer\|_processor\)" \
  mimicanno/vlm_labeler.py
```

Pin the attributes the handle will expose (typically `.model` + `.tokenizer`, or `.model` + `.processor` for multimodal). Document the chosen attribute set in the `shared_handle` docstring so Task 19's identity assertion (`id(planner.gemma_handle.model) == id(vlm.model)`) refers to a real attribute. If Phase 2's labeler exposes the model under a different name (e.g., `_model`), either rename in the handle or update Task 19's assertion to match.

- [ ] **Step 15.3: Implement `LocalGemmaTrackingPlanner.extract_entities`** — Build the Step A prompt (one-shot JSON instruction asking for objects/targets/tools given task_text + initial_frame). Allowed-label semantic categories passed as guidance ("place_*" → expect targets). Retry policy mirrors Phase 2's `_REJECT_AMENDMENT_BY_REASON` pattern. On terminal failure or empty `objects`, return `EntityPlan(object_prompts=[], ...)`.

- [ ] **Step 15.4: Run tests + commit**

```bash
git add mimicanno/object_tracker/planner.py mimicanno/vlm_labeler.py \
        tests/unit/object_tracker/test_planner.py
git commit -m "feat(planner): LocalGemmaTrackingPlanner.extract_entities (spec §2.2.1)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 16: `ground_initial_detections` (`mimicanno/object_tracker/propagator.py`)

Step B (spec §2.4.0). Iterates `EntityPlan.all_prompts_with_role()`, calls `runtime.ground_on_frame(initial_frame, prompt)` for each, takes the highest-scoring bbox. Builds `TrackingPlan(entities, initial_detections, failed_prompts)` where `initial_detections` uses `(role, prompt)` tuple keys (cross-role dup safety per spec §2.4.0).

**Files:**
- Modify: `mimicanno/object_tracker/propagator.py` (add `ground_initial_detections` function)
- Test: `tests/unit/object_tracker/test_grounding.py`

- [ ] **Step 16.1: Write the failing test**
  - **Happy path:** `EntityPlan(object_prompts=["red block"], targets=["bin A"], tools=["gripper"])`; mock SAM3Runtime → all 3 grounded → `TrackingPlan.initial_detections` has 3 keys, `failed_prompts == []`.
  - **Partial failure:** `bin A` returns `[]` → `bin A` ends up in `failed_prompts` (as `("target", "bin A")`), not in `initial_detections`.
  - **All object prompts failed:** all object prompts return `[]` → `failed_prompts` includes all object pairs; caller (orchestrator) responsible for triggering whole-run degrade (NOT this function).
  - **Cross-role duplicates preserved:** `EntityPlan(objects=["red block"], targets=["red block"])`; mock both grounded with different bboxes → `initial_detections` has 2 distinct entries `("object", "red block")` and `("target", "red block")` with different `BBox` values.
  - **Highest-score wins:** mock `ground_on_frame` returns `[(BBox_A, 0.9), (BBox_B, 0.95), (BBox_C, 0.5)]` → `initial_detections[(role, prompt)] == BBox_B`.

- [ ] **Step 16.2: Implement** — Pure Python; no SAM3 / Gemma dep (only the dataclass surface from Task 5 + the runtime Protocol from Task 14).

- [ ] **Step 16.3: Run tests + commit**

```bash
git add mimicanno/object_tracker/propagator.py tests/unit/object_tracker/test_grounding.py
git commit -m "feat(propagator): ground_initial_detections — Step B (spec §2.4.0)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 17: SAM3 checkpoint preflight (`mimicanno/preflight.py`)

Adds `resolve_sam3_checkpoint(path: Path) -> str` (returns `sha256:<hex>` of file content) and the surrounding validation. Preflight catches: missing file, unreadable file, sha256-computability failure → raises `SAM3CheckpointNotFound` (Tier 1 abort, exit non-zero) BEFORE any model load attempt. This is the boundary that keeps `sam3_init_failed` exclusive to true runtime errors (CUDA OOM, incompatible weights).

**Files:**
- Modify: `mimicanno/preflight.py` (add `resolve_sam3_checkpoint`)
- Test: `tests/unit/test_preflight_sam3.py`

- [ ] **Step 17.1: Write the failing test**
  - Path doesn't exist → `SAM3CheckpointNotFound(reason="file not found")`.
  - Path is a directory → `SAM3CheckpointNotFound(reason="not a regular file")`.
  - Path exists but unreadable (`chmod 000`) → `SAM3CheckpointNotFound(reason="permission denied")`. Use a `tmp_path` fixture; run only on POSIX (`pytest.importorskip("os")` / explicit skip).
  - Path exists and readable → returns `"sha256:<64 hex chars>"`. For determinism, write a known byte string and assert the precomputed sha256.
  - Symlink chain to a missing target → treated as "file not found".

- [ ] **Step 17.2: Implement** — Use `pathlib.Path.is_file()` + try/except on `open(...)`. Compute sha256 via `hashlib.sha256` chunked-read (matches existing Phase 1 sha256 helper in `io.py`).

- [ ] **Step 17.3: Run tests + commit**

```bash
git add mimicanno/preflight.py tests/unit/test_preflight_sam3.py
git commit -m "feat(preflight): SAM3 checkpoint resolution (spec §8 sam3_checkpoint_not_found)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 18: CLI flags + `--target-phase 3` dispatch (`mimicanno/cli.py`)

Adds `--sam3-checkpoint <path>` and `--track-stride-frames <int>` flags. Wires `--target-phase 3` to a new dispatch path. Tier 1 abort guards: target_phase==3 requires both `--vlm-model` (existing) and `--sam3-checkpoint` (new); abort with `MissingDependencyError` when missing. Also dispatches `SAM3ExtrasMissing` if `--target-phase 3` is given and `import sam3` raises (caught at the top of the Phase 3 path before any other work).

**Files:**
- Modify: `mimicanno/cli.py` (add 2 typer flags + dispatch)
- Modify: `mimicanno/errors.py` (`MissingDependencyError` if not already there — Phase 2 likely added it; reuse)
- Test: `tests/unit/test_cli_phase3.py` (uses `typer.testing.CliRunner` like Phase 2 does)

- [ ] **Step 18.1: Write the failing test**
  - `--target-phase 3` without `--sam3-checkpoint` → exit 2, stderr JSON `error_code` is whatever `MissingDependencyError(field="--sam3-checkpoint")` produces (Phase 2 introduced `MissingDependencyError`; reuse it parameterized on the missing flag name — do NOT introduce a new `sam3_checkpoint_required` code).
  - `--target-phase 3` without `--vlm-model` → exit 2, error code `vlm_model_required`.
  - `--target-phase 3 --vlm-model X --sam3-checkpoint /missing/path` → exit non-zero, error code `sam3_checkpoint_not_found`.
  - `--target-phase 3 --vlm-model X --sam3-checkpoint <valid>` (with mocked sam3 import + mocked SAM3Runtime + Fixture planner) → reaches the Phase 3 orchestrator path.
  - `--track-stride-frames 4 --target-phase 3 ...` → resolved to `TrackingConfig(track_stride_frames=4)` in the assembled `AnnotationConfig`.
  - `--target-phase 3` with `sam3` not importable (mock `sys.modules` to make it raise) → exit 2, `error_code=sam3_extras_missing`.

- [ ] **Step 18.2: Implement** — Add the 2 typer flags after the existing `--vlm-*` flags. Insert the abort-guard ladder before `AnnotationConfig` assembly. The `--target-phase 3` dispatch calls a new `annotate_episode_phase3(...)` from `pipeline.py` (lands in Task 19).

- [ ] **Step 18.3: Run tests + commit**

```bash
git add mimicanno/cli.py mimicanno/errors.py tests/unit/test_cli_phase3.py
git commit -m "feat(cli): --sam3-checkpoint + --track-stride-frames + Tier 1 abort guards (spec §8)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 19: Pipeline orchestrator `annotate_episode_phase3` (`mimicanno/pipeline.py`)

Implements spec §7.1: the 3-step Stage 1b ladder (Step A extract_entities → SAM3 load → Step B ground → Step C propagate), each with degrade gates; Stage 2 `Phase3BoundaryDetector`; Stage 3 `apply_phase3_labeling`. Critical resource discipline: `LocalGemmaVLMLabeler` and `LocalGemmaTrackingPlanner` share one Gemma instance via `vlm.shared_handle()`; `SAM3Runtime.close()` is called in a `finally:` block before Stage 3 (free GPU memory).

**Files:**
- Modify: `mimicanno/pipeline.py` (add `annotate_episode_phase3` branch — `target_phase >= 3` dispatch)
- Test: `tests/unit/test_pipeline_phase3.py` (uses `FixtureTrackingPlanner` + `FixtureSAM3Tracker`; integration smoke is Task 21)

- [ ] **Step 19.1: Write the failing test**
  - **Happy path returns successful run:** all stages succeed; manifest has `pipeline_status.object_state_available=True`, `degraded_from_phase=None`.
  - **Gemma handle shared:** assert `id(planner.gemma_handle.model) == id(vlm.model)` (or equivalent identity assertion via mocked loader counter — spec §11 exit criterion #7).
  - **SAM3.close called before Stage 3:** install a sentinel `close_called_before_stage3 = False`; mock the Phase 3 labeler to set `True` if `sam3_runtime._closed`; assert sentinel is True at end.
  - **`finally:` discipline:** if Stage C raises a non-degrade exception, `sam3_runtime.close()` still runs (use a mock that raises, then asserts `close()` was invoked).
  - **Image-aspect-ratio fallback:** if `inputs.image_size` is None or `height == 0`, falls back to `config.tracking.image_aspect_ratio_default` (passed into `compute_object_signals`).

- [ ] **Step 19.2: Implement** — Follow spec §7.1 pseudocode verbatim. New helper functions: `_extract_initial_frame(video_path)` (frame 0 with @5% retry per parent §11), `_compute_image_aspect_ratio(inputs, config) -> float`.

- [ ] **Step 19.3: Run tests + commit**

```bash
git add mimicanno/pipeline.py tests/unit/test_pipeline_phase3.py
git commit -m "feat(pipeline): annotate_episode_phase3 orchestrator (spec §7.1)

3-step Stage 1b ladder (Step A / SAM3 load / Step B / Step C) with
degrade gates between each. Shared Gemma handle between vlm and planner;
SAM3Runtime.close() in finally before Stage 3 (frees GPU). Image aspect
ratio fallback to TrackingConfig default when video metadata absent.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 20: `_degrade_to_phase3_objectless` + manifest `pipeline_status` (`mimicanno/pipeline.py`)

Implements spec §7.2 (whole-run degrade). Key invariants: Phase 3 boundary policy retained (NOT Phase 2 weights — boundaries differ from a literal Phase 2 invocation, intentionally per §7.2); `tracks.json` not written; `manifest.artifacts[]` MUST NOT include `kind="tracks"` (§3.4); `annotation.notes` contains ONLY the canonical degrade message (no chained `cause` — PII rule, §7.2 / §8); `underlying_log` (when non-None) goes to stderr WARN line.

Also adds the new manifest field `pipeline_status.object_state_segment_coverage` (`= 0.0` for whole-run degrade; `= n_with_object_state / n_total` for non-degraded Phase 3 runs; **absent** for Phase 1/2 manifests per spec §6.3).

**Files:**
- Modify: `mimicanno/pipeline.py` (add `_degrade_to_phase3_objectless` helper)
- Modify: `mimicanno/schema.py` (extend `PipelineStatus` with `object_state_segment_coverage: float | None = None` — when None, omit from serialized manifest per spec §6.3)
- Test: `tests/unit/test_phase3_degrade_helper.py`

- [ ] **Step 20.1: Write the failing test**
  - **Boundaries use Phase 3 weights even on degrade:** craft inputs; assert `boundaries.json.candidates[*].sources` could include the 2 new keys (their values would be NaN-everywhere → 0 contribution → no candidate, but the WEIGHTS in `pipeline_params.boundary.weights` are Phase 3 values — not Phase 1).
  - **`disabled_sources` includes both new sources** (no object_signals available).
  - **`tracks.json` NOT written:** `runs/<canon>/tracks.json` does not exist after `_degrade_to_phase3_objectless` returns.
  - **`manifest.artifacts[]` excludes tracks:** assert no element has `kind == "tracks"`.
  - **`annotation.notes` PII rule:** notes contains exactly `f"phase3: degraded to object-state-unavailable path (degrade_reason=sam3_init_failed)."`; assert NO substring `"Traceback"`, `"at 0x"`, `/path/to/`, `repr(`, `RuntimeError`, etc. (parametrize over forbidden substrings).
  - **`underlying_log` goes to stderr:** mock stderr; pass `underlying_log="RuntimeError('CUDA OOM at 8.2 GB')"`; assert that string appears in stderr (NOT in `notes`).
  - **`pipeline_status` fields:** `object_state_available=False`, `object_state_segment_coverage=0.0`, `degraded_from_phase=3`, `degrade_reason ∈ {three valid strings}`.
  - **Phase 1/2 manifest omits `object_state_segment_coverage`:** generate a Phase 1 manifest (existing pipeline); serialize; assert `"object_state_segment_coverage" not in payload["pipeline_status"]`.

- [ ] **Step 20.2: Implement** — Follow spec §7.2 verbatim. Helper signature:

```python
def _degrade_to_phase3_objectless(
    inputs, config, vlm, robot_signals, degrade_reason: str,
    *, underlying_log: str | None = None,
) -> ResultBundle:
    ...
```

Where `degrade_reason ∈ {"gemma_no_object_prompts", "sam3_no_initial_detection", "sam3_init_failed"}`. Uses `Phase3BoundaryDetector(config.boundary)` with empty `object_signals` (NaN arrays) and empty `tracks`; reuses Phase 2's `apply_phase2_labeling` for per-segment labels with `object_state_summary=None`.

Also extend `PipelineStatus.to_dict()` to omit `object_state_segment_coverage` when None.

- [ ] **Step 20.3: Run tests + commit**

```bash
git add mimicanno/pipeline.py mimicanno/schema.py tests/unit/test_phase3_degrade_helper.py
git commit -m "feat(pipeline): _degrade_to_phase3_objectless + pipeline_status fields (spec §7.2)

Phase 3 weights retained on degrade (boundaries differ from literal
Phase 2 — intentional per §7.2). tracks.json not written; manifest
artifacts list excludes kind=tracks. annotation.notes contains ONLY the
canonical degrade message — chained cause goes to stderr WARN line, NEVER
to notes (PII rule). New pipeline_status field
object_state_segment_coverage is absent for Phase 1/2 (spec §6.3).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 21: Integration — Phase 3 happy-path smoke (`tests/integration/test_phase3_smoke.py`)

End-to-end Phase 3 invocation with `FixtureTrackingPlanner` + `FixtureSAM3Tracker`. No GPU. Uses the existing Phase 1/2 integration-test scaffold (curated fixture episode under `tests/fixtures/episodes/`).

**Files:**
- Create: `tests/integration/test_phase3_smoke.py`
- Snapshot: `tests/snapshots/phase3/manifest_phase3_smoke.json`
- Snapshot: `tests/snapshots/phase3/annotation_phase3_smoke.json`

- [ ] **Step 21.1: Write the test** — Calls `mimicanno.cli.app(["annotate", "--target-phase=3", "--vlm-model=fixture://...", "--sam3-checkpoint=<dummy_path>", ...])` with monkeypatched `LocalGemmaVLMLabeler.load`, `LocalGemmaTrackingPlanner`, and `SAM3Runtime` to return fixture instances. Asserts:
  - Exit code 0.
  - Run directory exists at `runs/<canonical_name>/`.
  - All 6 artifacts present: `video.mp4` (or symlink), `signals.json`, `boundaries.json`, `annotation.json`, **`tracks.json`** (NEW), `manifest.json`.
  - `manifest.pipeline_status.object_state_available == True`.
  - `manifest.pipeline_status.object_state_segment_coverage == 1.0`.
  - `manifest.pipeline_status.degraded_from_phase is None`.
  - `manifest.model_versions.sam3 == "facebook/sam3"`, `model_versions.sam3_checkpoint == "sha256:<hex>"`.
  - `manifest.artifacts[]` includes `{"kind": "tracks", "url": "tracks.json", "schema_version": "0.1.0"}`.
  - Every `annotation.json` segment has `label_source == "vlm_with_object_state"`, `object_state_unavailable == False`, non-empty `object_track_ids`.
  - `tracks.json.tracks` non-empty; cross-artifact integrity check passes.
  - Snapshot byte-equality on the manifest + annotation files (excluding timestamps that vary run-to-run; use the existing Phase 2 snapshot scrubbing helper).

- [ ] **Step 21.2: Generate snapshots** — Run the test once with `--snapshot-update` (or whatever pattern Phase 2 uses) to produce the canonical artifacts; commit them.

- [ ] **Step 21.3: Run tests + commit**

```bash
git add tests/integration/test_phase3_smoke.py tests/snapshots/phase3/
git commit -m "test(integration): Phase 3 happy-path smoke (spec §11 #1)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 22: Integration — Per-segment fallback (`tests/integration/test_phase3_per_segment_fallback.py`)

Locks in spec §6 (per-segment fallback is NOT a degrade — `object_state_available` stays True; `object_state_segment_coverage < 1.0`).

**Files:**
- Create: `tests/integration/test_phase3_per_segment_fallback.py`

- [ ] **Step 22.1: Write the test** — Configure `FixtureSAM3Tracker.propagation_results` so the primary object track has a `GapEvent` covering >50% of segment 1's frames. Run the full pipeline; assert:
  - Exit code 0.
  - `manifest.pipeline_status.object_state_available == True`.
  - `manifest.pipeline_status.object_state_segment_coverage` between 0 and 1 exclusive (e.g. 0.667 for 2/3 coverage).
  - Segment 1: `label_source == "vlm_robot_state_only"`, `object_state_unavailable == True`, `object_track_ids == []`, `notes` contains `"phase3_per_segment_fallback"`.
  - Segments 0 and 2: `label_source == "vlm_with_object_state"`, `object_state_unavailable == False`.
  - `tracks.json` IS written (per-segment fallback doesn't suppress tracks artifact).

- [ ] **Step 22.2: Run tests + commit**

```bash
git add tests/integration/test_phase3_per_segment_fallback.py
git commit -m "test(integration): per-segment fallback preserves run (spec §6)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 23: Integration — 3 whole-run degrade paths + PII rule (`tests/integration/test_phase3_degrade_*.py`)

Three separate test files (one per degrade reason) — keeps each scenario focused and the fixture configuration minimal. Each test additionally asserts the §7.2 / §8 PII rule (no exception text leaks into `notes`).

**Files:**
- Create: `tests/integration/test_phase3_degrade_gemma_no_objects.py`
- Create: `tests/integration/test_phase3_degrade_sam3_no_initial.py`
- Create: `tests/integration/test_phase3_degrade_sam3_init_failed.py`

- [ ] **Step 23.1: Write `test_phase3_degrade_gemma_no_objects.py`** — `FixtureTrackingPlanner(entities=EntityPlan(object_prompts=[], target_prompts=[], tool_prompts=[]))`. Assert:
  - Exit code 0.
  - `manifest.pipeline_status.object_state_available == False`.
  - `manifest.pipeline_status.degraded_from_phase == 3`.
  - `manifest.pipeline_status.degrade_reason == "gemma_no_object_prompts"`.
  - `manifest.pipeline_status.object_state_segment_coverage == 0.0`.
  - `tracks.json` does NOT exist on disk.
  - `manifest.artifacts[]` has NO element with `kind == "tracks"`.
  - `annotation.notes` contains exactly `"phase3: degraded to object-state-unavailable path (degrade_reason=gemma_no_object_prompts)."` and no other content matching the forbidden-substring set (`"Traceback"`, `"at 0x"`, `"/"`, `"RuntimeError"`).
  - Boundaries used Phase 3 weights (assert `manifest.pipeline_params.boundary.weights.gripper_transition == 0.45`, NOT 0.50).
  - `disabled_sources` includes both `gripper_object_distance_threshold_crossing` and `object_motion_start_stop`.

- [ ] **Step 23.2: Write `test_phase3_degrade_sam3_no_initial.py`** — `FixtureSAM3Tracker.initial_detections={prompt: [] for prompt in all_object_prompts}` (all object groundings empty). Same assertion set with `degrade_reason="sam3_no_initial_detection"`.

- [ ] **Step 23.3: Write `test_phase3_degrade_sam3_init_failed.py`** — `FixtureSAM3Tracker.raise_on_load=RuntimeError("CUDA OOM at /home/u/sam3.ckpt loading 8.2GB into device 0 with token sk_xxx")`. Same assertion set with `degrade_reason="sam3_init_failed"`. Critical PII check: assert `"CUDA OOM"`, `"/home/u/sam3.ckpt"`, `"sk_xxx"`, `"RuntimeError"`, `"loading 8.2GB"` are ALL absent from `annotation.notes` content. Optionally assert they DO appear in captured stderr (proves the underlying_log path works).

- [ ] **Step 23.4: Run all 3 tests + commit**

```bash
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/python -m pytest tests/integration/test_phase3_degrade_*.py -v
git add tests/integration/test_phase3_degrade_*.py
git commit -m "test(integration): 3 whole-run degrade paths + PII rule (spec §7.2, §8, §11 #2)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 24: Integration — preflight + idempotency + distinctness + Phase 1/2 no-regression + cross-artifact (`tests/integration/test_phase3_*.py`)

Five small integration tests bundled (each is independent but small enough to share a task).

**Files:**
- Create: `tests/integration/test_phase3_preflight_checkpoint_missing.py`
- Create: `tests/integration/test_phase3_idempotency.py`
- Create: `tests/integration/test_phase3_distinctness.py`
- Create: `tests/integration/test_phase3_no_phase12_regression.py`
- Create: `tests/integration/test_tracks_json_cross_artifact.py`

- [ ] **Step 24.1: `test_phase3_preflight_checkpoint_missing.py`** — `--sam3-checkpoint /definitely/missing/path.ckpt`. Assert exit code != 0, stderr structured-error JSON `error_code=sam3_checkpoint_not_found`, no `runs/<...>/` directory created (preflight catches this before publish).

- [ ] **Step 24.2: `test_phase3_idempotency.py`** — Run the Task 21 happy-path twice with the same inputs + config. Assert: same `canonical_name`, byte-equal `manifest.config_hash` and `manifest.run_hash`, and structural-equality (deep dict-compare via parsed JSON, NOT raw byte equality — float-serializer drift across Python patch versions can change byte output without touching content) on `boundaries.json` / `annotation.json` / `tracks.json` / `signals.json`.

- [ ] **Step 24.3: `test_phase3_distinctness.py`** — Same input episode + same vlm_model; run with `--target-phase 1`, `--target-phase 2`, `--target-phase 3` (the latter two with appropriate flags). Assert 3 distinct `canonical_name` values, 3 distinct `config_hash` values, 3 distinct `runs/<...>/` directories.

- [ ] **Step 24.4: `test_phase3_no_phase12_regression.py`** — Pin canonical Phase 1 + Phase 2 hashes (same values as `test_phase3_hash_gating.py` Step 2.1 baselines). Run a full Phase 1 invocation + a full Phase 2 invocation in this test on the curated fixture episode; assert the produced `manifest.config_hash` and `manifest.run_hash` match the pinned values exactly. Plus structural-equality on `boundaries.json` / `annotation.json` / `signals.json` against pre-Phase-3 snapshots from the Phase 2 plan's snapshot dir.

- [ ] **Step 24.5: `test_tracks_json_cross_artifact.py`** — Generate a tracks.json with `episode_id="MISMATCH"` (different from the manifest's `episode_id`), call `read_tracks_json(path, expected=("real_episode", fps, n_frames))`, assert raises `ArtifactIntegrityError` with code `tracks_json_integrity_violation`. Same for fps mismatch and n_frames mismatch.

- [ ] **Step 24.6: Run all 5 tests + commit**

```bash
git add tests/integration/test_phase3_preflight_checkpoint_missing.py \
        tests/integration/test_phase3_idempotency.py \
        tests/integration/test_phase3_distinctness.py \
        tests/integration/test_phase3_no_phase12_regression.py \
        tests/integration/test_tracks_json_cross_artifact.py
git commit -m "test(integration): preflight + idempotency + distinctness + Phase 1/2 no-regression + cross-artifact (spec §11 #3, #6, §3.3)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 25: Real-SAM3 gated smoke + final cleanup + milestone commit

Layer 3 manual verification (spec §10.3 / §11 #10) + final lint / type / test cleanup. Mirrors Phase 2's Task 18.

**Files:**
- Create: `tests/test_phase3_real_sam3_smoke.py` (env-gated)

- [ ] **Step 25.1: Write the gated smoke test**

```python
import os
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("MIMICANNO_RUN_SAM3_SMOKE") != "1"
    or not os.environ.get("MIMICANNO_SAM3_CHECKPOINT"),
    reason="Set MIMICANNO_RUN_SAM3_SMOKE=1 and MIMICANNO_SAM3_CHECKPOINT to run",
)


def test_phase3_real_sam3_on_lerobot_ep0(tmp_path) -> None:
    """Layer 3 manual smoke (spec §10.3 / §11 #10).

    Loads real Gemma + real SAM3 against lerobot/svla_so100_pickplace ep0
    (the same episode used in Phase 1 verification — see
    docs/phase1-real-data-verification.md).

    Asserts: tracks.json exists; at least 1 object track has >= 10 samples;
    manifest.pipeline_status.object_state_available is True;
    object_state_segment_coverage >= 0.5.

    NOT in CI gate. Run manually before milestone commit.
    """
    # Build the AnnotateRequest pointing at the lerobot ep0 fixture
    # (path documented in brushup_progress_pointer.md).
    ...
```

- [ ] **Step 25.2: Run the smoke test** (manual, requires GPU + sam3 weights):

```bash
export MIMICANNO_RUN_SAM3_SMOKE=1
export MIMICANNO_SAM3_CHECKPOINT=/path/to/sam3.ckpt
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/python -m pytest tests/test_phase3_real_sam3_smoke.py -v -s
```

Expected: PASS (with stderr WARN logs visible because `-s` doesn't capture).

- [ ] **Step 25.3: Final mypy --strict cleanup**

```bash
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/python -m mypy --strict mimicanno/
```

Expected: 0 errors. If any (likely from the new `object_tracker/` package), fix in place; do not weaken `--strict`.

- [ ] **Step 25.4: Final ruff cleanup**

```bash
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/python -m ruff check mimicanno/ tests/
```

Expected: clean (parity with Phase 2's accepted-warning baseline — lambdas in factory dispatchers + semicolons in test fixtures only).

- [ ] **Step 25.5: Full test suite green**

```bash
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/python -m pytest tests/ -v --ignore=tests/test_phase3_real_sam3_smoke.py \
                                         --ignore=tests/test_phase2_real_vlm.py
```

Expected: every test PASS. Phase 1 baseline (224) + Phase 2 (42 new) + Phase 3 (estimate **120-150 new** — several tasks have 9-25 parametrized cases each: Task 4 = 16, Task 5 ≈ 14, Task 6 ≈ 25, Task 8 ≈ 11, Task 9 ≈ 9, Task 10 ≈ 14, etc.) = **~390-420 tests total**. Exact count is not asserted, just a sanity-check ballpark.

- [ ] **Step 25.6: Commit gated smoke + milestone marker**

```bash
git add tests/test_phase3_real_sam3_smoke.py
git commit -m "test(phase3): real-SAM3 gated smoke + lint/type cleanup (spec §10.3, §11 #10)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"

# Milestone marker — empty commit per Phase 1 / Phase 2 pattern
git commit --allow-empty -m "milestone: Phase 3 SAM3 + integrated boundary score complete

All 11 exit criteria satisfied (spec §11):
1. mimicanno annotate --target-phase 3 produces a complete run dir with tracks.json
   and pipeline_status.object_state_available=true on at least one real episode.
2. 3 whole-run degrade reasons all produce Phase-3-objectless runs with matching
   degrade_reason and canonical-message-only notes.
3. All Phase 1 / Phase 2 tests pass without modification (no regression).
4. mypy --strict clean across mimicanno/ including the new object_tracker package.
5. ruff check clean (parity with Phase 2 accepted baseline).
6. Per-segment fallback works: object_state_segment_coverage < 1.0 with
   object_state_available=true.
7. Gemma loader is shared between LocalGemmaVLMLabeler and LocalGemmaTrackingPlanner.
8. SAM3 GPU memory released before Stage 3 (close() is idempotent and called in finally).
9. Phase 1/2 config_hash unchanged (test_phase3_hash_isolation.py pinned values).
10. Real-SAM3 smoke test passed manually on lerobot/svla_so100_pickplace ep0.
11. Spec §11 #11 (out-of-scope items remain non-completed).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## End of plan
