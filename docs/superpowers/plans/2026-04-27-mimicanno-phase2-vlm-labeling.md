# MimicAnno Phase 2 — VLM Labeling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `mimicanno annotate` so that `--target-phase 2 --vlm-model <id>` runs the existing Phase 1 pipeline and then labels every Phase 1 segment via a pluggable VLM. Output is a self-contained run directory whose `annotation.json` carries `phase ∈ allowed_labels ∪ {"unknown"}`, `label_source="vlm_robot_state_only"`, and `vlm_confidence ∈ [0.0, 1.0]` per segment. The Plan 2 viewer renders the result with no viewer-side changes.

**Architecture:** Phase 2 is a purely additive layer on top of Phase 1. A pre-flight resolves the VLM model identifier (HF API lookup, or sha-pinned `<id>@<sha>`, or fixture URI) into a stable `(model_id, resolved_checkpoint)` pair *before* `config_hash` is computed — so `__init__` failures cannot diverge the hash from the actually-loaded model. The orchestrator (`vlm_labeler.label_run`) calls a `VLMLabeler` factory (catching constructor failures as `vlm_init_failed` degrade), iterates segments, runs `parse_and_validate` on every response, retries up to `max_retries` on `LabelerError`, fall-back-to-`"unknown"` on exhaustion, and degrades the whole run on threshold-exceeding `LabelerRuntimeError`. Two `VLMLabeler` impls ship: `FixtureVLMLabeler` (CI-grade deterministic) and `LocalGemmaVLMLabeler` (default real adapter; concrete `model_id` pinned in Task 11).

**Tech Stack:** Python 3.11+ (existing venv), `huggingface_hub` for model lookup, `transformers>=5.5` for the Gemma 4 multimodal IT load, `Pillow` for image resize, `pyav` (already a Phase 1 dep) for keyframe extraction, `pytest` for tests. POSIX semantics inherited from Phase 1; no new I/O or atomicity contracts.

**Spec source of truth:** `docs/superpowers/specs/2026-04-27-mimicanno-phase2-vlm-labeling-design.md`. Every section reference (`§3.1`, `§4.3`, etc.) below is **into that document**, not the parent design brushup. Parent spec references are explicitly marked `parent §...`.

---

## File structure (locked in before tasks)

**New files:**

```
mimicanno/
  preflight.py                            # NEW: HF API lookup, fixture URI parsing, --offline gate
  clip_features.py                        # NEW: ClipFeatureExtractor, RobotStateSummary computation
  vlm_labeler.py                          # NEW: protocol + types + FixtureVLMLabeler
                                          #      + LocalGemmaVLMLabeler + label_run orchestrator
  vlm_prompt.py                           # NEW: prompt template assembly (separate file to keep
                                          #      vlm_labeler.py focused on protocol + orchestration)

tests/
  fixtures/
    vlm/
      ok_first_try.json                   # NEW: §5.5 sample fixture, all-ok scenarios
      retry_then_ok.json                  # NEW: ok_after_2_retries scenario
      fallback_unknown.json               # NEW: 3-retry exhaustion → "unknown"
      runtime_oom.json                    # NEW: cuda_oom each attempt (Tier 2 trigger)
      init_should_raise.json              # NEW: __init__ raises (vlm_init_failed)
  snapshots/
    phase2/
      prompt_initial.txt                  # NEW: initial prompt snapshot
      prompt_retry_invalid_label.txt      # NEW: retry prompt snapshot (invalid_label)
      label_attempt_ok.json               # NEW: LabelAttempt JSON snapshot
      label_attempt_retried.json          # NEW: retried + ok
      label_attempt_unknown.json          # NEW: fallback
      annotation_phase2_smoke.json        # NEW: Phase 2 annotation.json excerpt
      manifest_phase2_smoke.json          # NEW: Phase 2 manifest.json excerpt
  unit/
    test_preflight.py                     # NEW
    test_clip_features.py                 # NEW
    test_vlm_types.py                     # NEW (Labeler errors, dataclasses, enum exhaustiveness)
    test_vlm_validation.py                # NEW (parse_and_validate paths)
    test_vlm_prompt.py                    # NEW (prompt assembly snapshot)
    test_fixture_labeler.py               # NEW (FixtureVLMLabeler scenario replay)
    test_label_run_success.py             # NEW (orchestrator happy + retry + segment fallback)
    test_label_run_degrade.py             # NEW (vlm_init_failed / vlm_unreachable / vlm_runtime_failed)
    test_local_gemma_skeleton.py          # NEW (mock-based LocalGemmaVLMLabeler tests)
  integration/
    test_phase2_smoke_fixture.py          # NEW
    test_phase2_degrade_paths.py          # NEW
    test_phase2_cli_abort.py              # NEW
    test_phase2_hash_distinctness.py      # NEW
    test_phase2_idempotency.py            # NEW
  test_phase2_real_vlm.py                 # NEW (env-gated; Layer 3 manual smoke)
```

**Modified files:**

```
mimicanno/
  config.py            # ADD ClipFeatureConfig, VLMConfig dataclasses; extend AnnotationConfig
                       # with .vlm field; ModelConfig.vlm_model / vlm_checkpoint populated from
                       # VLMConfig at construction time.
  schema.py            # extend ModelVersions serialization to project model_id:checkpoint string;
                       # extend SubtaskSegment serialization for vlm_confidence/label_source values.
                       # (Most fields already exist — only re-test required.)
  pipeline.py          # branch when target_phase >= 2 → call vlm_labeler.label_run; populate
                       # manifest.pipeline_status / model_versions / pipeline_params.vlm and
                       # annotation.notes from RunOutcome + attempts_log.
  cli.py               # add --vlm-model, --vlm-keyframes, --vlm-max-retries, --offline,
                       # --target-phase. Invoke pre-flight before AnnotationConfig assembly.
                       # Tier 1 abort path for missing required flags.
  errors.py            # add MimicAnnoError subclasses for new error_codes:
                       #   vlm_model_required, vlm_config_invalid, vlm_model_not_found.
  schema_versions.py   # NO CHANGE — Phase 2 introduces no schema_version bumps (spec §1.3).
  labelset.py          # NO CHANGE — already rejects "unknown"/"unlabeled" reserved ids
                       # at load time per parent §8.4 (verified in Task 5).
```

**Decomposition rules followed:**
- **One file = one responsibility.** `preflight.py`, `clip_features.py`, `vlm_prompt.py`, and `vlm_labeler.py` are kept separate so each can be reasoned about independently. The orchestrator (`label_run`) lives with the protocol because it owns the labeler-factory lifecycle.
- **Files that change together live together.** `vlm_prompt.py` and `vlm_labeler.py` change for prompt evolution but are split because the prompt is snapshot-tested independently of orchestration.
- **Test-to-source 1:1 where possible.** Every `mimicanno/<x>.py` has at least one `tests/unit/test_<x>.py`.
- **CI vs gated split.** `tests/unit/` and `tests/integration/` use `FixtureVLMLabeler` only; `tests/test_phase2_real_vlm.py` is the env-gated Layer 3 smoke that loads real weights (Task 18).

---

## Task ordering rationale

The order minimizes blockage and lets reviewer / CI catch contract violations early:

1. **Foundation (Tasks 1–2):** config dataclasses + error codes. Everything else imports these.
2. **Pre-flight + ClipFeatures (Tasks 3–4):** pure-function modules with no labeler dependency. CLI parser depends on pre-flight (Task 14); pipeline orchestration depends on ClipFeatureExtractor (Task 13).
3. **Labeler types + protocol (Task 5):** TypedDicts, exception classes, dataclasses. Imported by everything in `vlm_labeler.py` and tests.
4. **Validator + prompt (Tasks 6–7):** `parse_and_validate` and `build_prompt` are pure functions, validated by snapshot tests. The validator is the contract-locking core of Phase 2.
5. **FixtureVLMLabeler (Task 8):** the testing labeler. Required by all subsequent orchestrator tests.
6. **Orchestrator (Tasks 9–10):** `label_run` happy path then degrade paths. Both use FixtureVLMLabeler exclusively.
7. **LocalGemmaVLMLabeler (Tasks 11–12):** the production labeler. Mock-based unit tests for the skeleton and the exception classifier; real model load is gated to Task 18.
8. **Pipeline + CLI integration (Tasks 13–14):** wire the new modules into the existing pipeline / CLI.
9. **Integration tests (Tasks 15–17):** end-to-end CLI smoke, degrade paths, hash distinctness / idempotency, CLI abort.
10. **Real-VLM smoke + final cleanup (Task 18):** env-gated real-model run + full suite green + lint + types.

---

## Task 1: VLMConfig + ClipFeatureConfig dataclasses

**Spec refs:** §2.4, §2.6, §1.3.

**Files:**
- Modify: `mimicanno/config.py`
- Create: `tests/unit/test_vlm_config.py`

- [ ] **Step 1: Read existing AnnotationConfig and confirm field placement.**

Run: `sed -n '195,210p' mimicanno/config.py` and confirm that `AnnotationConfig` currently has `boundary`, `target_phase`, `model_config` fields, and that `to_dict` serializes them under `"annotation_config"`, `"target_phase"`, `"model_config"`. We add `vlm: VLMConfig | None` alongside.

- [ ] **Step 2: Write failing test for ClipFeatureConfig defaults.**

Create `tests/unit/test_vlm_config.py`:

```python
"""Phase 2: VLMConfig and ClipFeatureConfig dataclasses (spec §2.4, §2.6)."""
from __future__ import annotations

import pytest

from mimicanno.config import (
    AnnotationConfig,
    BoundaryConfig,
    ClipFeatureConfig,
    ModelConfig,
    VLMConfig,
    compute_config_hash,
)


def test_clip_feature_config_defaults() -> None:
    cfg = ClipFeatureConfig()
    assert cfg.gripper_open_threshold == pytest.approx(0.5)
    assert cfg.dwell_speed_threshold_mps == pytest.approx(0.01)


def test_vlm_config_defaults_and_required() -> None:
    cfg = VLMConfig(model_id="dummy-model", resolved_checkpoint="abc")
    assert cfg.keyframes_per_segment == 4
    assert cfg.image_size_px == 224
    assert cfg.max_retries == 3
    assert cfg.temperature == pytest.approx(0.0)
    assert cfg.timeout_sec == pytest.approx(30.0)
    assert cfg.runtime_failure_threshold == 3
    assert cfg.dtype == "bfloat16"
    assert cfg.clip_features.gripper_open_threshold == pytest.approx(0.5)


def test_vlm_config_to_dict_canonical_field_set() -> None:
    cfg = VLMConfig(model_id="m", resolved_checkpoint="c")
    d = cfg.to_dict()
    assert set(d) == {
        "clip_features", "device", "dtype", "image_size_px",
        "keyframe_strategy", "keyframes_per_segment", "max_output_tokens",
        "max_retries", "model_id", "resolved_checkpoint",
        "runtime_failure_threshold", "temperature", "timeout_sec",
    }


def test_annotation_config_with_vlm_changes_hash() -> None:
    boundary = BoundaryConfig.with_defaults()
    model = ModelConfig(vlm_model=None, vlm_checkpoint=None,
                        sam3_model=None, sam3_checkpoint=None)

    cfg_p1 = AnnotationConfig(
        boundary=boundary, target_phase=1, model_config=model, vlm=None
    )
    h_p1 = compute_config_hash(cfg_p1)

    vlm = VLMConfig(model_id="m1", resolved_checkpoint="abc")
    model_p2 = ModelConfig(
        vlm_model="m1", vlm_checkpoint="abc", sam3_model=None, sam3_checkpoint=None,
    )
    cfg_p2 = AnnotationConfig(
        boundary=boundary, target_phase=2, model_config=model_p2, vlm=vlm
    )
    h_p2 = compute_config_hash(cfg_p2)

    assert h_p1 != h_p2

    # Changing keyframes_per_segment also yields a different hash.
    vlm2 = VLMConfig(model_id="m1", resolved_checkpoint="abc",
                     keyframes_per_segment=6)
    cfg_p2b = AnnotationConfig(
        boundary=boundary, target_phase=2, model_config=model_p2, vlm=vlm2
    )
    assert compute_config_hash(cfg_p2b) != h_p2


def test_annotation_config_to_dict_omits_vlm_when_none() -> None:
    """Phase 1 manifest byte-equivalence (spec §2.6)."""
    boundary = BoundaryConfig.with_defaults()
    model = ModelConfig(vlm_model=None, vlm_checkpoint=None,
                        sam3_model=None, sam3_checkpoint=None)
    cfg = AnnotationConfig(
        boundary=boundary, target_phase=1, model_config=model, vlm=None
    )
    d = cfg.to_dict()
    assert "vlm" not in d["annotation_config"]
```

- [ ] **Step 3: Run test to verify it fails.**

```
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/pytest tests/unit/test_vlm_config.py -v
```

Expected: FAIL with `ImportError: cannot import name 'VLMConfig'` or `'ClipFeatureConfig'`.

- [ ] **Step 4: Add ClipFeatureConfig and VLMConfig to mimicanno/config.py.**

Insert immediately after `BoundaryConfig` definition (≈ line 76):

```python
@dataclass(slots=True, frozen=True)
class ClipFeatureConfig:
    """Thresholds used by clip_features.py (spec §2.4)."""
    gripper_open_threshold: float = 0.5
    dwell_speed_threshold_mps: float = 0.01

    def to_dict(self) -> dict[str, Any]:
        return {
            "gripper_open_threshold": self.gripper_open_threshold,
            "dwell_speed_threshold_mps": self.dwell_speed_threshold_mps,
        }


@dataclass(slots=True, frozen=True)
class VLMConfig:
    """Phase 2 VLM-pipeline configuration (spec §2.4).

    `resolved_checkpoint` MUST be populated by pre-flight (§2.5) before this
    config is fed into AnnotationConfig and hashed. It is `None` only during
    construction-time defaults; at hash-time of a target_phase >= 2 run, a
    None value is a producer bug.
    """
    model_id: str
    keyframes_per_segment: int = 4
    keyframe_strategy: str = "uniform"  # extension point; only "uniform" supported in Phase 2
    image_size_px: int = 224
    max_retries: int = 3
    temperature: float = 0.0
    max_output_tokens: int = 256
    timeout_sec: float = 30.0
    runtime_failure_threshold: int = 3
    device: str = "cuda"
    dtype: str = "bfloat16"
    clip_features: ClipFeatureConfig = ClipFeatureConfig()
    resolved_checkpoint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "clip_features": self.clip_features.to_dict(),
            "device": self.device,
            "dtype": self.dtype,
            "image_size_px": self.image_size_px,
            "keyframe_strategy": self.keyframe_strategy,
            "keyframes_per_segment": self.keyframes_per_segment,
            "max_output_tokens": self.max_output_tokens,
            "max_retries": self.max_retries,
            "model_id": self.model_id,
            "resolved_checkpoint": self.resolved_checkpoint,
            "runtime_failure_threshold": self.runtime_failure_threshold,
            "temperature": self.temperature,
            "timeout_sec": self.timeout_sec,
        }
```

Then extend `AnnotationConfig` (≈ line 196):

```python
@dataclass(slots=True)
class AnnotationConfig:
    boundary: BoundaryConfig
    target_phase: int
    model_config: ModelConfig
    vlm: VLMConfig | None = None  # required iff target_phase >= 2

    def to_dict(self) -> dict[str, Any]:
        ann_inner: dict[str, Any] = {"boundary": self.boundary.to_dict()}
        if self.vlm is not None:
            ann_inner["vlm"] = self.vlm.to_dict()
        return {
            "annotation_config": ann_inner,
            "target_phase": self.target_phase,
            "model_config": self.model_config.to_dict(),
        }
```

- [ ] **Step 5: Run test to verify it passes.**

```
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/pytest tests/unit/test_vlm_config.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Sanity-check existing Phase 1 tests still pass.**

```
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/pytest tests/unit/test_config_hash.py -v
```

Expected: existing test count unchanged, all green. (`AnnotationConfig.vlm = None` is default so existing tests construct unchanged.)

- [ ] **Step 7: Commit.**

```bash
git add mimicanno/config.py tests/unit/test_vlm_config.py
git commit -m "feat(config): add VLMConfig and ClipFeatureConfig dataclasses (Phase 2 §2.4)"
```

---

## Task 2: Phase 2 error codes

**Spec refs:** §4.2.

**Files:**
- Modify: `mimicanno/errors.py`
- Modify: `tests/unit/test_errors.py`

- [ ] **Step 1: Read existing errors.py to find the convention.**

Run: `cat mimicanno/errors.py | head -60` and identify the existing error-class pattern (`MimicAnnoError` subclasses with `code` attribute). New Phase 2 codes (`vlm_model_required`, `vlm_config_invalid`, `vlm_model_not_found`) follow the same pattern.

- [ ] **Step 2: Write failing test.**

Add to `tests/unit/test_errors.py`:

```python
def test_phase2_vlm_model_required_error() -> None:
    from mimicanno.errors import VLMModelRequired
    e = VLMModelRequired(target_phase=2)
    assert e.code == "vlm_model_required"
    assert e.context == {"target_phase": 2}


def test_phase2_vlm_config_invalid_error() -> None:
    from mimicanno.errors import VLMConfigInvalid
    e = VLMConfigInvalid(reason="keyframes_per_segment must be >= 1")
    assert e.code == "vlm_config_invalid"
    assert "must be >= 1" in e.message


def test_phase2_vlm_model_not_found_error() -> None:
    from mimicanno.errors import VLMModelNotFound
    e = VLMModelNotFound(model_id="google/foo", reason="404")
    assert e.code == "vlm_model_not_found"
    assert e.context["model_id"] == "google/foo"
```

- [ ] **Step 3: Run failing test.**

```
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/pytest tests/unit/test_errors.py -k phase2 -v
```

Expected: ImportError on the three new classes.

- [ ] **Step 4: Add the three new error classes to mimicanno/errors.py.**

Append (preserve existing patterns):

```python
class VLMModelRequired(MimicAnnoError):
    """`--target-phase >= 2` invoked without `--vlm-model` (spec §4.2)."""
    code = "vlm_model_required"

    def __init__(self, target_phase: int) -> None:
        super().__init__(
            message=f"target_phase={target_phase} requires --vlm-model",
            context={"target_phase": target_phase},
        )


class VLMConfigInvalid(MimicAnnoError):
    """VLMConfig has an out-of-range or contradictory field (spec §4.2)."""
    code = "vlm_config_invalid"

    def __init__(self, reason: str) -> None:
        super().__init__(message=reason, context={})


class VLMModelNotFound(MimicAnnoError):
    """Pre-flight could not resolve --vlm-model (HF 404, network, fixture file
    missing, --offline gating). Spec §4.2."""
    code = "vlm_model_not_found"

    def __init__(self, model_id: str, reason: str) -> None:
        super().__init__(
            message=f"could not resolve vlm_model={model_id!r}: {reason}",
            context={"model_id": model_id, "reason": reason},
        )
```

- [ ] **Step 5: Run test to verify it passes.**

```
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/pytest tests/unit/test_errors.py -v
```

Expected: existing tests + 3 new = all green.

- [ ] **Step 6: Commit.**

```bash
git add mimicanno/errors.py tests/unit/test_errors.py
git commit -m "feat(errors): add Phase 2 vlm error codes (spec §4.2)"
```

---

## Task 3: Pre-flight model resolution (`mimicanno/preflight.py`)

**Spec refs:** §2.5.

**Files:**
- Create: `mimicanno/preflight.py`
- Create: `tests/unit/test_preflight.py`

This module owns the contract: parse `--vlm-model`, route to the correct resolution path, return a frozen `(model_id, resolved_checkpoint)` tuple. It is the **only** module that calls `huggingface_hub`; everything else trusts the resolved string.

- [ ] **Step 1: Write failing tests covering the four routing cases.**

Create `tests/unit/test_preflight.py`:

```python
"""Pre-flight model resolution (spec §2.5)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from mimicanno.errors import VLMModelNotFound
from mimicanno.preflight import (
    PreflightResult,
    SHA40_REGEX,
    resolve_vlm_model,
)


def _make_fixture(tmp_path: Path, body: dict) -> Path:
    p = tmp_path / "fixt.json"
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


# ---- 40-hex sha path (Case A) ---------------------------------------------

def test_sha40_regex_recognizes_40_hex_only() -> None:
    assert SHA40_REGEX.match("a" * 40)
    assert SHA40_REGEX.match("0123456789abcdef0123456789abcdef01234567")
    assert not SHA40_REGEX.match("a" * 39)
    assert not SHA40_REGEX.match("a" * 41)
    assert not SHA40_REGEX.match("Z" * 40)


def test_resolve_explicit_sha_does_not_call_hf(monkeypatch: pytest.MonkeyPatch) -> None:
    sha = "a" * 40
    called: list[str] = []

    def fake_model_info(*args, **kwargs):  # type: ignore[no-untyped-def]
        called.append("hf")
        raise AssertionError("HF API must not be called when sha is explicit")

    monkeypatch.setattr("mimicanno.preflight._hf_model_info", fake_model_info)
    r = resolve_vlm_model(f"google/gemma-x@{sha}", offline=False)
    assert r == PreflightResult(model_id="google/gemma-x", resolved_checkpoint=sha)
    assert called == []


# ---- HF API path (Case B) -------------------------------------------------

def test_resolve_branch_name_calls_hf_and_returns_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    sha = "b" * 40

    def fake_model_info(model_id: str, revision: str | None) -> str:
        assert model_id == "google/gemma-x"
        assert revision == "main"
        return sha

    monkeypatch.setattr("mimicanno.preflight._hf_model_info", fake_model_info)
    r = resolve_vlm_model("google/gemma-x@main", offline=False)
    assert r.resolved_checkpoint == sha


def test_resolve_no_revision_calls_hf(monkeypatch: pytest.MonkeyPatch) -> None:
    sha = "c" * 40

    def fake_model_info(model_id: str, revision: str | None) -> str:
        assert revision is None
        return sha

    monkeypatch.setattr("mimicanno.preflight._hf_model_info", fake_model_info)
    r = resolve_vlm_model("google/gemma-x", offline=False)
    assert r.resolved_checkpoint == sha


def test_resolve_offline_without_explicit_sha_aborts() -> None:
    with pytest.raises(VLMModelNotFound) as ei:
        resolve_vlm_model("google/gemma-x", offline=True)
    assert "explicit 40-hex commit sha required" in ei.value.message


def test_resolve_offline_with_branch_aborts() -> None:
    with pytest.raises(VLMModelNotFound) as ei:
        resolve_vlm_model("google/gemma-x@main", offline=True)
    assert "explicit 40-hex" in ei.value.message


def test_resolve_hf_lookup_failure_aborts(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_model_info(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise OSError("network unreachable")

    monkeypatch.setattr("mimicanno.preflight._hf_model_info", fake_model_info)
    with pytest.raises(VLMModelNotFound) as ei:
        resolve_vlm_model("google/gemma-x", offline=False)
    assert "network unreachable" in ei.value.message


# ---- Fixture URI path (Case C) --------------------------------------------

def test_resolve_fixture_uri(tmp_path: Path) -> None:
    p = _make_fixture(tmp_path, {"model_identity": {}, "segments": {}})
    expected_sha = hashlib.sha256(p.read_bytes()).hexdigest()
    r = resolve_vlm_model(f"fixture://{p}", offline=True)
    assert r.model_id == "fixture"
    assert r.resolved_checkpoint == expected_sha


def test_resolve_fixture_uri_missing_file_aborts(tmp_path: Path) -> None:
    nope = tmp_path / "nope.json"
    with pytest.raises(VLMModelNotFound) as ei:
        resolve_vlm_model(f"fixture://{nope}", offline=False)
    assert "fixture file" in ei.value.message
```

- [ ] **Step 2: Run failing tests.**

```
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/pytest tests/unit/test_preflight.py -v
```

Expected: ImportError on `mimicanno.preflight`.

- [ ] **Step 3: Implement mimicanno/preflight.py.**

```python
"""Pre-flight VLM model resolution (spec §2.5).

Single responsibility: parse `--vlm-model` argument, route to one of three
resolution cases, return a frozen (model_id, resolved_checkpoint) tuple that
the rest of the system trusts.

This module is the ONLY caller of huggingface_hub. Everything else accepts
the resolved string verbatim.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from mimicanno.errors import VLMModelNotFound

SHA40_REGEX = re.compile(r"^[0-9a-f]{40}$")
FIXTURE_URI_PREFIX = "fixture://"


@dataclass(slots=True, frozen=True)
class PreflightResult:
    model_id: str
    resolved_checkpoint: str


def _hf_model_info(model_id: str, revision: Optional[str]) -> str:
    """Resolve a HuggingFace model_id+revision to a commit sha.
    Isolated for monkeypatching in tests; production import guarded so that
    test environments without `huggingface_hub` installed still pass."""
    from huggingface_hub import HfApi  # local import — only loaded on real path
    info = HfApi().model_info(model_id, revision=revision)
    sha = getattr(info, "sha", None) or getattr(info, "commit_hash", None)
    if not sha or not SHA40_REGEX.match(sha):
        raise OSError(f"HF returned non-sha revision: {sha!r}")
    return sha


def _split_model_at_revision(arg: str) -> tuple[str, Optional[str]]:
    if "@" in arg:
        model_id, _, revision = arg.partition("@")
        return model_id, revision
    return arg, None


def _resolve_fixture(path_str: str) -> PreflightResult:
    p = Path(path_str)
    if not p.is_file():
        raise VLMModelNotFound(
            model_id="fixture",
            reason=f"fixture file does not exist: {p}",
        )
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    return PreflightResult(model_id="fixture", resolved_checkpoint=sha)


def resolve_vlm_model(arg: str, *, offline: bool) -> PreflightResult:
    """Resolve a CLI --vlm-model argument to a stable (model_id, sha) tuple.

    Cases (spec §2.5):
      A. <id>@<40-hex-sha>  → accept directly, no HF lookup. Offline-safe.
      B. <id> or <id>@<branch_or_tag> → HF lookup. Forbidden when offline=True.
      C. fixture://<path>   → sha = sha256(file content).

    Raises VLMModelNotFound on any resolution failure (Tier 1 abort, spec §4.2).
    """
    if arg.startswith(FIXTURE_URI_PREFIX):
        return _resolve_fixture(arg[len(FIXTURE_URI_PREFIX):])

    model_id, revision = _split_model_at_revision(arg)

    # Case A: explicit 40-hex sha.
    if revision is not None and SHA40_REGEX.match(revision):
        return PreflightResult(model_id=model_id, resolved_checkpoint=revision)

    # Case B: needs HF API lookup.
    if offline:
        raise VLMModelNotFound(
            model_id=arg,
            reason=(
                "explicit 40-hex commit sha required after '@' for --offline runs "
                "(use '<id>@<40-hex-sha>')"
            ),
        )

    try:
        sha = _hf_model_info(model_id, revision)
    except Exception as e:  # network, 404, auth — all collapse into Tier 1.
        raise VLMModelNotFound(model_id=arg, reason=str(e)) from e
    return PreflightResult(model_id=model_id, resolved_checkpoint=sha)
```

- [ ] **Step 4: Run tests to verify all pass.**

```
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/pytest tests/unit/test_preflight.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit.**

```bash
git add mimicanno/preflight.py tests/unit/test_preflight.py
git commit -m "feat(preflight): VLM model resolution with fixture/sha/HF/offline paths (Phase 2 §2.5)"
```

---

## Task 4: ClipFeatureExtractor (`mimicanno/clip_features.py`)

**Spec refs:** §2.7, §3.1.

**Files:**
- Create: `mimicanno/clip_features.py`
- Create: `tests/unit/test_clip_features.py`

This module is **pure** (no I/O beyond what the existing video / signals modules already provide). It owns:
1. Keyframe selection (uniform K, K_effective branching).
2. The 5-scalar `RobotStateSummary` computation per spec §3.1.

- [ ] **Step 1: Write failing tests for keyframe offsets.**

Create `tests/unit/test_clip_features.py`:

```python
"""ClipFeatureExtractor (spec §2.7, §3.1)."""
from __future__ import annotations

import numpy as np
import pytest

from mimicanno.clip_features import (
    RobotStateSummary,
    compute_keyframe_offsets,
    compute_robot_state_summary,
)
from mimicanno.config import ClipFeatureConfig


# ---- compute_keyframe_offsets ---------------------------------------------

def test_keyframe_offsets_K4_long_segment() -> None:
    # 30 fps, 90 frames spanning [0, 90), K=4 → start, +30, +60, +89
    offs = compute_keyframe_offsets(start_frame=0, end_frame=89, k=4)
    assert offs == [0, 30, 59, 89]


def test_keyframe_offsets_K2_returns_endpoints() -> None:
    offs = compute_keyframe_offsets(start_frame=10, end_frame=20, k=2)
    assert offs == [10, 20]


def test_keyframe_offsets_K1_branch() -> None:
    """K_effective == 1 must NOT divide by zero (spec §2.7)."""
    offs = compute_keyframe_offsets(start_frame=5, end_frame=5, k=1)
    assert offs == [5]


def test_keyframe_offsets_short_segment_reduces_K() -> None:
    # 2-frame segment [0, 1] requested with K=4 → K_effective = 2.
    offs = compute_keyframe_offsets(start_frame=0, end_frame=1, k=4)
    assert offs == [0, 1]


# ---- compute_robot_state_summary ------------------------------------------

def test_summary_no_eef_returns_null_speed_and_dwell() -> None:
    """When EEF velocity is unavailable, both mean_eef_speed_mps and
    dwell_fraction MUST be None (spec §2.4 ClipFeatureConfig note)."""
    fps = 30.0
    duration = 1.0  # 30 frames
    gripper = np.linspace(0.0, 1.0, num=30, dtype=np.float64)
    cfg = ClipFeatureConfig()
    summ = compute_robot_state_summary(
        start_frame=0, end_frame=29, fps=fps,
        gripper=gripper, eef_velocity=None, cfg=cfg,
    )
    assert summ["mean_eef_speed_mps"] is None
    assert summ["dwell_fraction"] is None
    assert summ["duration_sec"] == pytest.approx(1.0)


def test_summary_gripper_open_fraction_threshold() -> None:
    """gripper_open_fraction is the time-weighted average of (g >= threshold)."""
    fps = 30.0
    # First half closed (0.0), second half open (1.0). Threshold default 0.5.
    gripper = np.concatenate([np.zeros(15), np.ones(15)]).astype(np.float64)
    cfg = ClipFeatureConfig(gripper_open_threshold=0.5)
    summ = compute_robot_state_summary(
        start_frame=0, end_frame=29, fps=fps,
        gripper=gripper, eef_velocity=None, cfg=cfg,
    )
    assert summ["gripper_open_fraction"] == pytest.approx(0.5)


def test_summary_gripper_transitions_count() -> None:
    """gripper_transitions counts threshold crossings."""
    fps = 30.0
    gripper = np.array([0.0, 1.0, 0.0, 1.0, 0.0])  # 4 crossings
    cfg = ClipFeatureConfig(gripper_open_threshold=0.5)
    summ = compute_robot_state_summary(
        start_frame=0, end_frame=4, fps=fps,
        gripper=gripper, eef_velocity=None, cfg=cfg,
    )
    assert summ["gripper_transitions"] == 4


def test_summary_dwell_fraction_with_eef() -> None:
    """dwell_fraction is the fraction of time |eef_velocity| < threshold."""
    fps = 30.0
    gripper = np.zeros(30)
    # First 10 frames "fast" (>= 0.1), next 20 frames "dwell" (< 0.01).
    eef_vel = np.zeros((30, 3), dtype=np.float64)
    eef_vel[:10, 0] = 0.1
    eef_vel[10:, 0] = 0.005
    cfg = ClipFeatureConfig(dwell_speed_threshold_mps=0.01)
    summ = compute_robot_state_summary(
        start_frame=0, end_frame=29, fps=fps,
        gripper=gripper, eef_velocity=eef_vel, cfg=cfg,
    )
    assert summ["dwell_fraction"] == pytest.approx(20 / 30)
    assert summ["mean_eef_speed_mps"] is not None
```

- [ ] **Step 2: Run failing tests.**

```
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/pytest tests/unit/test_clip_features.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement mimicanno/clip_features.py.**

```python
"""Phase 2 clip-feature extraction (spec §2.7, §3.1).

Pure functions over (segment indices, signal arrays, config). No I/O —
the keyframe images are extracted by the caller using existing io_video
helpers; this module decides WHICH frame indices to extract.

Returns the 5-scalar RobotStateSummary used in the VLM prompt:
  duration_sec, mean_eef_speed_mps, gripper_open_fraction,
  gripper_transitions, dwell_fraction.
"""
from __future__ import annotations

from typing import Optional, TypedDict

import numpy as np

from mimicanno.config import ClipFeatureConfig


class RobotStateSummary(TypedDict):
    duration_sec: float
    mean_eef_speed_mps: Optional[float]
    gripper_open_fraction: float
    gripper_transitions: int
    dwell_fraction: Optional[float]


def compute_keyframe_offsets(start_frame: int, end_frame: int, k: int) -> list[int]:
    """Return K_effective frame indices in temporal order, evenly spaced
    between start_frame and end_frame inclusive (spec §2.7).

    K_effective = min(k, end_frame - start_frame + 1). The K_effective == 1
    branch returns [start_frame] explicitly because the formula is undefined
    (denominator 0) in that case.
    """
    if k < 1:
        raise ValueError(f"keyframes_per_segment must be >= 1, got {k}")
    span = end_frame - start_frame + 1
    if span < 1:
        raise ValueError(f"end_frame {end_frame} must be >= start_frame {start_frame}")
    k_eff = min(k, span)
    if k_eff == 1:
        return [start_frame]
    return [
        start_frame + round(i * (end_frame - start_frame) / (k_eff - 1))
        for i in range(k_eff)
    ]


def _count_crossings(values: np.ndarray, threshold: float) -> int:
    """Count threshold crossings (state flips). For values [0, 1, 0, 1, 0]
    with threshold 0.5, returns 4."""
    above = values >= threshold
    flips = np.diff(above.astype(np.int8))
    return int(np.sum(flips != 0))


def compute_robot_state_summary(
    *,
    start_frame: int,
    end_frame: int,
    fps: float,
    gripper: np.ndarray,
    eef_velocity: Optional[np.ndarray],
    cfg: ClipFeatureConfig,
) -> RobotStateSummary:
    """5-scalar robot-state summary for one segment (spec §3.1).

    `gripper`: (N,) array, [0, 1]-normalized robot adapter output covering the
        entire episode. We slice [start_frame:end_frame+1].
    `eef_velocity`: (N, 3) array of m/s velocities OR None when the adapter
        does not expose EEF data. When None, mean_eef_speed_mps and
        dwell_fraction are both None (spec §2.4 note).
    """
    seg = slice(start_frame, end_frame + 1)
    g = gripper[seg]
    duration_sec = (end_frame - start_frame + 1) / fps if fps > 0 else 0.0

    open_mask = g >= cfg.gripper_open_threshold
    gripper_open_fraction = float(np.mean(open_mask)) if g.size > 0 else 0.0
    gripper_transitions = _count_crossings(g, cfg.gripper_open_threshold)

    mean_speed: Optional[float]
    dwell_fraction: Optional[float]
    if eef_velocity is None:
        mean_speed = None
        dwell_fraction = None
    else:
        v = eef_velocity[seg]
        speed = np.linalg.norm(v, axis=-1) if v.ndim > 1 else np.abs(v)
        mean_speed = float(np.mean(speed)) if speed.size > 0 else 0.0
        dwell_mask = speed < cfg.dwell_speed_threshold_mps
        dwell_fraction = float(np.mean(dwell_mask)) if speed.size > 0 else 0.0

    return RobotStateSummary(
        duration_sec=duration_sec,
        mean_eef_speed_mps=mean_speed,
        gripper_open_fraction=gripper_open_fraction,
        gripper_transitions=gripper_transitions,
        dwell_fraction=dwell_fraction,
    )
```

- [ ] **Step 4: Run tests.**

```
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/pytest tests/unit/test_clip_features.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit.**

```bash
git add mimicanno/clip_features.py tests/unit/test_clip_features.py
git commit -m "feat(clip_features): keyframe offsets + 5-scalar robot-state summary (Phase 2 §3.1)"
```

---

## Task 5: VLMLabeler types & exception classes

**Spec refs:** §2.1, §2.3.

**Files:**
- Create: `mimicanno/vlm_labeler.py` (initial scaffold; orchestrator + impls added in Tasks 8-10)
- Create: `tests/unit/test_vlm_types.py`

- [ ] **Step 1: Write failing tests for the type surface.**

Create `tests/unit/test_vlm_types.py`:

```python
"""VLMLabeler protocol surface — exception classes, enums, dataclasses.

We do NOT test the protocol class itself (it's structural); we test that
the concrete error/enum/dataclass surface matches spec §2.1 + §2.3.
"""
from __future__ import annotations

import pytest

from mimicanno.vlm_labeler import (
    LabelAttempt,
    LabelerError,
    LabelerRuntimeError,
    ModelIdentity,
    REJECT_REASONS,
    RUNTIME_FAULT_REASONS,
    RunOutcome,
    VLMResponse,
)


def test_reject_reasons_exhaustive() -> None:
    assert set(REJECT_REASONS) == {
        "json_parse_error",
        "schema_violation",
        "invalid_label",
        "out_of_range_confidence",
        "timeout",
    }


def test_runtime_fault_reasons_exhaustive() -> None:
    assert set(RUNTIME_FAULT_REASONS) == {
        "model_unreachable",
        "device_unavailable",
        "cuda_oom",
        "inference_timeout",
    }


def test_labeler_error_carries_reject_reason() -> None:
    e = LabelerError(reject_reason="invalid_label")
    assert e.reject_reason == "invalid_label"


def test_labeler_runtime_error_carries_reason() -> None:
    e = LabelerRuntimeError(reason="cuda_oom")
    assert e.reason == "cuda_oom"


def test_label_attempt_default_construction() -> None:
    resp = VLMResponse(phase="idle", verb=None, object=None, target=None,
                       vlm_confidence=0.5, evidence=None)
    a = LabelAttempt(
        segment_id="s_001",
        attempt_count=1,
        final_status="ok",
        reject_reasons=[],
        runtime_errors=[],
        response=resp,
    )
    assert a.final_status == "ok"


def test_run_outcome_ok_has_no_degrade_reason() -> None:
    o = RunOutcome(kind="ok", degrade_reason=None, underlying_error=None)
    assert o.kind == "ok"
    assert o.degrade_reason is None


def test_run_outcome_degraded_with_reason() -> None:
    o = RunOutcome(
        kind="degraded",
        degrade_reason="vlm_init_failed",
        underlying_error="OSError(...)",
    )
    assert o.kind == "degraded"


def test_model_identity_shape() -> None:
    m = ModelIdentity(vlm_model="x", vlm_checkpoint="y")
    assert m["vlm_model"] == "x"
    assert m["vlm_checkpoint"] == "y"
```

- [ ] **Step 2: Run failing tests.**

```
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/pytest tests/unit/test_vlm_types.py -v
```

Expected: ImportError.

- [ ] **Step 3: Create mimicanno/vlm_labeler.py with the type surface only.**

```python
"""Phase 2 VLMLabeler protocol, types, exception classes, and label_run
orchestrator (spec §2.1 + §2.3).

This file is the contract surface. Concrete implementations
(FixtureVLMLabeler, LocalGemmaVLMLabeler) and the orchestrator land in
later tasks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol, TypedDict, get_args

import numpy as np


# --- Reject / runtime-fault reason enums (kept as Literal for type-checkers,
#     and re-exported as concrete tuples for runtime exhaustiveness checks).

RejectReason = Literal[
    "json_parse_error",
    "schema_violation",
    "invalid_label",
    "out_of_range_confidence",
    "timeout",
]
REJECT_REASONS: tuple[str, ...] = get_args(RejectReason)

RuntimeFaultReason = Literal[
    "model_unreachable",
    "device_unavailable",
    "cuda_oom",
    "inference_timeout",
]
RUNTIME_FAULT_REASONS: tuple[str, ...] = get_args(RuntimeFaultReason)


# --- Exception classes ------------------------------------------------------

class LabelerError(Exception):
    """Raised on VLM-output rejection (parse / schema / range failures).
    Retry-eligible (spec §4.5)."""
    def __init__(self, reject_reason: RejectReason) -> None:
        super().__init__(f"VLM output rejected: {reject_reason}")
        self.reject_reason: RejectReason = reject_reason


class LabelerRuntimeError(Exception):
    """Raised on inference-infrastructure faults. Counted toward
    runtime_failure_threshold (§4.3). Generic Python RuntimeError is NOT
    caught by the orchestrator — implementations must classify and wrap
    underlying PyTorch / HF exceptions into this class."""
    def __init__(self, reason: RuntimeFaultReason) -> None:
        super().__init__(f"VLM runtime fault: {reason}")
        self.reason: RuntimeFaultReason = reason


# --- Type surface -----------------------------------------------------------

class ModelIdentity(TypedDict):
    vlm_model: str
    vlm_checkpoint: str


class VLMResponse(TypedDict):
    phase: str                  # ∈ allowed_labels ∪ {"unknown"}
    verb: str | None
    object: str | None
    target: str | None
    vlm_confidence: float       # ∈ [0.0, 1.0]
    evidence: str | None


class VLMRequest(TypedDict):
    task_text: str
    allowed_labels: list[str]
    label_version: str
    robot_type: str
    fps: float
    episode_duration_sec: float
    segment_index: int
    segment_total: int
    keyframes: list[np.ndarray]
    keyframe_offsets_sec: list[float]
    robot_state_summary: dict   # see clip_features.RobotStateSummary


@dataclass(slots=True)
class LabelAttempt:
    segment_id: str
    attempt_count: int
    final_status: Literal["ok", "unknown_fallback"]
    reject_reasons: list[RejectReason] = field(default_factory=list)
    runtime_errors: list[RuntimeFaultReason] = field(default_factory=list)
    response: VLMResponse = field(default_factory=lambda: VLMResponse(
        phase="unknown", verb=None, object=None, target=None,
        vlm_confidence=0.0, evidence=None,
    ))


@dataclass(slots=True)
class RunOutcome:
    kind: Literal["ok", "degraded"]
    degrade_reason: Literal[
        "vlm_init_failed", "vlm_unreachable", "vlm_runtime_failed"
    ] | None
    underlying_error: str | None  # exception repr — stderr-log-only, never artifact


# --- Protocol ---------------------------------------------------------------

class VLMLabeler(Protocol):
    def label_segment(self, request: VLMRequest, attempt: int) -> VLMResponse: ...
    def model_identity(self) -> ModelIdentity: ...
```

- [ ] **Step 4: Run tests.**

```
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/pytest tests/unit/test_vlm_types.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit.**

```bash
git add mimicanno/vlm_labeler.py tests/unit/test_vlm_types.py
git commit -m "feat(vlm_labeler): protocol + types + exception classes (Phase 2 §2.1)"
```

---

## Task 6: `parse_and_validate` validator (`mimicanno/vlm_labeler.py`)

**Spec refs:** §3.4.

**Files:**
- Modify: `mimicanno/vlm_labeler.py`
- Create: `tests/unit/test_vlm_validation.py`

The validator is the contract-locking core: it MUST run on every VLM response (regardless of model-side structured-output features). Each rejection path produces a `LabelerError` carrying the matching `RejectReason`.

- [ ] **Step 1: Write failing tests covering happy path + every reject path + evidence truncation.**

Create `tests/unit/test_vlm_validation.py`:

```python
"""parse_and_validate (spec §3.4)."""
from __future__ import annotations

import pytest

from mimicanno.vlm_labeler import (
    EVIDENCE_DISPLAY_HINT_CHARS,
    LabelerError,
    parse_and_validate,
)

ALLOWED = {"idle", "approach_object", "grasp_object"}


def _ok(extra: str = "") -> str:
    return (
        '{"phase": "grasp_object", "verb": "grasp", "object": "block", '
        '"target": null, "vlm_confidence": 0.7, "evidence": "g closing"' + extra + "}"
    )


def test_happy_path() -> None:
    r = parse_and_validate(_ok(), ALLOWED)
    assert r["phase"] == "grasp_object"
    assert r["verb"] == "grasp"
    assert r["target"] is None
    assert r["vlm_confidence"] == pytest.approx(0.7)
    assert r["evidence"] == "g closing"


def test_strips_markdown_fences() -> None:
    raw = "```json\n" + _ok() + "\n```"
    r = parse_and_validate(raw, ALLOWED)
    assert r["phase"] == "grasp_object"


def test_unknown_phase_accepted() -> None:
    raw = '{"phase": "unknown", "vlm_confidence": 0.0}'
    r = parse_and_validate(raw, ALLOWED)
    assert r["phase"] == "unknown"


def test_extra_fields_ignored() -> None:
    raw = '{"phase": "idle", "vlm_confidence": 0.5, "extra_future_field": 42}'
    r = parse_and_validate(raw, ALLOWED)
    assert r["phase"] == "idle"


# ---- reject paths ---------------------------------------------------------

def test_json_parse_error() -> None:
    with pytest.raises(LabelerError) as ei:
        parse_and_validate("not json", ALLOWED)
    assert ei.value.reject_reason == "json_parse_error"


def test_schema_violation_missing_phase() -> None:
    raw = '{"vlm_confidence": 0.5}'
    with pytest.raises(LabelerError) as ei:
        parse_and_validate(raw, ALLOWED)
    assert ei.value.reject_reason == "schema_violation"


def test_schema_violation_phase_wrong_type() -> None:
    raw = '{"phase": 42, "vlm_confidence": 0.5}'
    with pytest.raises(LabelerError) as ei:
        parse_and_validate(raw, ALLOWED)
    assert ei.value.reject_reason == "schema_violation"


def test_schema_violation_verb_wrong_type() -> None:
    raw = '{"phase": "idle", "verb": 42, "vlm_confidence": 0.5}'
    with pytest.raises(LabelerError) as ei:
        parse_and_validate(raw, ALLOWED)
    assert ei.value.reject_reason == "schema_violation"


def test_invalid_label() -> None:
    raw = '{"phase": "made_up", "vlm_confidence": 0.5}'
    with pytest.raises(LabelerError) as ei:
        parse_and_validate(raw, ALLOWED)
    assert ei.value.reject_reason == "invalid_label"


def test_unlabeled_is_invalid() -> None:
    """Reserved 'unlabeled' MUST never be a valid Phase 2 VLM output."""
    raw = '{"phase": "unlabeled", "vlm_confidence": 0.5}'
    with pytest.raises(LabelerError) as ei:
        parse_and_validate(raw, ALLOWED)
    assert ei.value.reject_reason == "invalid_label"


def test_out_of_range_confidence_high() -> None:
    raw = '{"phase": "idle", "vlm_confidence": 1.5}'
    with pytest.raises(LabelerError) as ei:
        parse_and_validate(raw, ALLOWED)
    assert ei.value.reject_reason == "out_of_range_confidence"


def test_out_of_range_confidence_low() -> None:
    raw = '{"phase": "idle", "vlm_confidence": -0.01}'
    with pytest.raises(LabelerError) as ei:
        parse_and_validate(raw, ALLOWED)
    assert ei.value.reject_reason == "out_of_range_confidence"


# ---- soft truncation ------------------------------------------------------

def test_evidence_over_length_truncated_not_rejected() -> None:
    long = "x" * (EVIDENCE_DISPLAY_HINT_CHARS + 50)
    raw = (
        '{"phase": "idle", "vlm_confidence": 0.5, "evidence": "' + long + '"}'
    )
    r = parse_and_validate(raw, ALLOWED)
    assert r["evidence"] is not None
    assert len(r["evidence"]) == EVIDENCE_DISPLAY_HINT_CHARS
```

- [ ] **Step 2: Run failing tests.**

```
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/pytest tests/unit/test_vlm_validation.py -v
```

Expected: ImportError on `parse_and_validate` and `EVIDENCE_DISPLAY_HINT_CHARS`.

- [ ] **Step 3: Append parse_and_validate to mimicanno/vlm_labeler.py (after the type surface added in Task 5).**

```python
import json
import re

EVIDENCE_DISPLAY_HINT_CHARS = 80

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n(.*?)\n\s*```\s*$", re.DOTALL)


def _strip_markdown_fences(text: str) -> str:
    m = _FENCE_RE.match(text)
    return m.group(1) if m else text


def parse_and_validate(raw_text: str, user_allowed_labels: set[str]) -> VLMResponse:
    """Validate a VLM response string against the spec §3.4 contract.

    On any failure raises LabelerError(reject_reason=...). On success returns
    a VLMResponse with optional fields coerced to None and evidence truncated
    to EVIDENCE_DISPLAY_HINT_CHARS (soft cap).

    `user_allowed_labels` MUST NOT include 'unknown' or 'unlabeled' (parent
    §8.4 — labels YAML loader rejects these). Validator internally accepts
    'unknown' as a valid VLM output; 'unlabeled' is always rejected.
    """
    text = _strip_markdown_fences(raw_text)

    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        raise LabelerError("json_parse_error") from e
    if not isinstance(obj, dict):
        raise LabelerError("schema_violation")

    if "phase" not in obj or not isinstance(obj["phase"], str):
        raise LabelerError("schema_violation")
    if "vlm_confidence" not in obj or not isinstance(obj["vlm_confidence"], (int, float)) \
            or isinstance(obj["vlm_confidence"], bool):
        raise LabelerError("schema_violation")
    for field in ("verb", "object", "target", "evidence"):
        if field in obj and obj[field] is not None and not isinstance(obj[field], str):
            raise LabelerError("schema_violation")

    if obj["phase"] not in user_allowed_labels | {"unknown"}:
        raise LabelerError("invalid_label")

    if not 0.0 <= float(obj["vlm_confidence"]) <= 1.0:
        raise LabelerError("out_of_range_confidence")

    evidence = obj.get("evidence")
    if isinstance(evidence, str) and len(evidence) > EVIDENCE_DISPLAY_HINT_CHARS:
        evidence = evidence[:EVIDENCE_DISPLAY_HINT_CHARS]

    return VLMResponse(
        phase=obj["phase"],
        verb=obj.get("verb"),
        object=obj.get("object"),
        target=obj.get("target"),
        vlm_confidence=float(obj["vlm_confidence"]),
        evidence=evidence,
    )
```

- [ ] **Step 4: Run tests.**

```
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/pytest tests/unit/test_vlm_validation.py -v
```

Expected: 13 passed.

- [ ] **Step 5: Commit.**

```bash
git add mimicanno/vlm_labeler.py tests/unit/test_vlm_validation.py
git commit -m "feat(vlm_labeler): parse_and_validate with full reject_reason coverage (§3.4)"
```

---

## Task 7: Prompt assembly (`mimicanno/vlm_prompt.py`)

**Spec refs:** §3.3.

**Files:**
- Create: `mimicanno/vlm_prompt.py`
- Create: `tests/unit/test_vlm_prompt.py`
- Create: `tests/snapshots/phase2/prompt_initial.txt`
- Create: `tests/snapshots/phase2/prompt_retry_invalid_label.txt`

Prompt construction is split out of `vlm_labeler.py` so the prompt body can be snapshot-tested without dragging in the orchestrator. The output is the **system + user** text portion only; image-token placement is the caller's responsibility (it differs between FixtureVLMLabeler and LocalGemmaVLMLabeler).

- [ ] **Step 1: Write failing snapshot tests.**

Create `tests/unit/test_vlm_prompt.py`:

```python
"""Prompt assembly snapshot tests (spec §3.3)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mimicanno.vlm_prompt import build_prompt
from mimicanno.vlm_labeler import VLMRequest

SNAPS = Path(__file__).resolve().parents[1] / "snapshots" / "phase2"


def _request() -> VLMRequest:
    return VLMRequest(
        task_text="Pick the red block and place it in the white bin.",
        allowed_labels=[
            "idle", "approach_object", "align_gripper", "grasp_object",
            "lift_object", "move_to_target", "align_to_target",
            "place_object", "release_object", "retreat",
        ],
        label_version="manipulation.v1",
        robot_type="aloha",
        fps=30.0,
        episode_duration_sec=15.13,
        segment_index=3,
        segment_total=8,
        keyframes=[np.zeros((4, 4, 3), dtype=np.uint8)],
        keyframe_offsets_sec=[0.0, 0.5, 1.0, 1.5],
        robot_state_summary={
            "duration_sec": 1.83,
            "mean_eef_speed_mps": 0.082,
            "gripper_open_fraction": 0.41,
            "gripper_transitions": 1,
            "dwell_fraction": 0.12,
        },
    )


def test_initial_prompt_matches_snapshot() -> None:
    got = build_prompt(_request(), attempt=1, last_reject_reason=None)
    expected = (SNAPS / "prompt_initial.txt").read_text(encoding="utf-8")
    assert got == expected


def test_retry_prompt_appends_strict_amendment() -> None:
    got = build_prompt(_request(), attempt=2, last_reject_reason="invalid_label")
    expected = (SNAPS / "prompt_retry_invalid_label.txt").read_text(encoding="utf-8")
    assert got == expected


def test_null_eef_data_rendered_as_null() -> None:
    req = _request()
    req["robot_state_summary"]["mean_eef_speed_mps"] = None
    req["robot_state_summary"]["dwell_fraction"] = None
    got = build_prompt(req, attempt=1, last_reject_reason=None)
    assert "mean_eef_speed_mps: null" in got
    assert "dwell_fraction: null" in got
```

- [ ] **Step 2: Run failing tests.**

```
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/pytest tests/unit/test_vlm_prompt.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement mimicanno/vlm_prompt.py.**

```python
"""Phase 2 VLM prompt assembly (spec §3.3).

Builds the system+user text portion of the prompt as a single string. The
caller (FixtureVLMLabeler / LocalGemmaVLMLabeler) is responsible for
splicing in image tokens at the [KEYFRAMES] marker.
"""
from __future__ import annotations

from typing import Optional

from mimicanno.vlm_labeler import RejectReason, VLMRequest

_REJECT_AMENDMENT_BY_REASON = {
    "json_parse_error": (
        "Re-emit the JSON object only. No prose, no markdown fences."
    ),
    "schema_violation": (
        "All required fields MUST be present with correct types: "
        "phase: string, vlm_confidence: float in [0.0, 1.0], "
        "verb/object/target/evidence: string or null."
    ),
    "invalid_label": (
        "The 'phase' field MUST be one of the allowed labels OR exactly 'unknown'."
    ),
    "out_of_range_confidence": (
        "The 'vlm_confidence' field MUST satisfy 0.0 <= value <= 1.0."
    ),
    "timeout": "",  # no copy change; just retry
}


def _fmt_optional_float(v: Optional[float]) -> str:
    if v is None:
        return "null"
    return f"{v:.6g}"


def build_prompt(
    request: VLMRequest,
    attempt: int,
    last_reject_reason: Optional[RejectReason],
) -> str:
    """Construct the prompt text for one VLM call.

    Output structure: SYSTEM block (task + allowed labels + robot state)
    + USER block ([KEYFRAMES] marker for the caller to splice images, plus
    output-format instruction). On retry attempts (attempt > 1), an
    amendment specific to last_reject_reason is appended verbatim.
    """
    rs = request["robot_state_summary"]
    allowed = ", ".join(request["allowed_labels"])
    body = (
        "SYSTEM:\n"
        f"You are labeling a segment of a robot manipulation episode.\n"
        f"Task instruction: \"{request['task_text']}\"\n"
        f"Robot type: {request['robot_type']}, FPS: {request['fps']:.6g},"
        f" Episode duration: {request['episode_duration_sec']:.6g}s.\n"
        f"This is segment {request['segment_index']} of {request['segment_total']}.\n"
        "\n"
        f"Allowed phase labels (label_version={request['label_version']}):\n"
        f"  {allowed}\n"
        "\n"
        "Robot-state summary for this segment:\n"
        f"  duration_sec: {rs['duration_sec']:.6g}\n"
        f"  mean_eef_speed_mps: {_fmt_optional_float(rs.get('mean_eef_speed_mps'))}\n"
        f"  gripper_open_fraction: {rs['gripper_open_fraction']:.6g}\n"
        f"  gripper_transitions: {rs['gripper_transitions']}\n"
        f"  dwell_fraction: {_fmt_optional_float(rs.get('dwell_fraction'))}\n"
        "\n"
        "USER:\n"
        "[KEYFRAMES]\n"
        "\n"
        "Respond with ONE JSON object, no prose, no markdown fences:\n"
        "{\n"
        "  \"phase\":          \"<one of allowed labels, or 'unknown'>\",\n"
        "  \"verb\":           \"<short verb or null>\",\n"
        "  \"object\":         \"<short noun or null>\",\n"
        "  \"target\":         \"<short noun or null>\",\n"
        "  \"vlm_confidence\": <float in [0.0, 1.0]>,\n"
        "  \"evidence\":       \"<<=80 chars, or null>\"\n"
        "}\n"
    )
    if attempt > 1 and last_reject_reason and _REJECT_AMENDMENT_BY_REASON[last_reject_reason]:
        body += (
            "\n"
            f"Your previous response was rejected: reject_reason={last_reject_reason}.\n"
            f"{_REJECT_AMENDMENT_BY_REASON[last_reject_reason]}\n"
            "Re-emit the JSON object exactly per the schema.\n"
        )
    return body
```

- [ ] **Step 4: Generate snapshot files.**

Run an interactive Python snippet to produce the two snapshot files:

```bash
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH .venv/bin/python <<'PY'
from pathlib import Path
import sys; sys.path.insert(0, ".")
from tests.unit.test_vlm_prompt import _request
from mimicanno.vlm_prompt import build_prompt

snaps = Path("tests/snapshots/phase2")
snaps.mkdir(parents=True, exist_ok=True)
(snaps / "prompt_initial.txt").write_text(
    build_prompt(_request(), attempt=1, last_reject_reason=None),
    encoding="utf-8",
)
(snaps / "prompt_retry_invalid_label.txt").write_text(
    build_prompt(_request(), attempt=2, last_reject_reason="invalid_label"),
    encoding="utf-8",
)
print("OK")
PY
```

Expected stdout: `OK`. Two files created.

- [ ] **Step 5: Inspect snapshot files for sanity.**

```bash
head -20 tests/snapshots/phase2/prompt_initial.txt
diff tests/snapshots/phase2/prompt_initial.txt tests/snapshots/phase2/prompt_retry_invalid_label.txt
```

Expected: initial file ends after the JSON-schema example; retry file has additional text beginning with `Your previous response was rejected: reject_reason=invalid_label.`

- [ ] **Step 6: Run tests.**

```
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/pytest tests/unit/test_vlm_prompt.py -v
```

Expected: 3 passed.

- [ ] **Step 7: Commit.**

```bash
git add mimicanno/vlm_prompt.py tests/unit/test_vlm_prompt.py tests/snapshots/phase2/prompt_initial.txt tests/snapshots/phase2/prompt_retry_invalid_label.txt
git commit -m "feat(vlm_prompt): build_prompt with retry-amendment + snapshot tests (§3.3)"
```

---

## Task 8: `FixtureVLMLabeler`

**Spec refs:** §2.2, §5.5.

**Files:**
- Modify: `mimicanno/vlm_labeler.py`
- Create: `tests/unit/test_fixture_labeler.py`
- Create: `tests/fixtures/vlm/ok_first_try.json`
- Create: `tests/fixtures/vlm/retry_then_ok.json`
- Create: `tests/fixtures/vlm/fallback_unknown.json`
- Create: `tests/fixtures/vlm/runtime_oom.json`
- Create: `tests/fixtures/vlm/init_should_raise.json`

The fixture format is fully specified in spec §5.5. We implement the `_emit_raw` / `_raise_each_attempt` / `init_should_raise` paths exactly as documented, with the exception classifiers we already have (LabelerError / LabelerRuntimeError).

- [ ] **Step 1: Create the five fixture JSONs.**

`tests/fixtures/vlm/ok_first_try.json`:

```json
{
  "model_identity": {"vlm_model": "fixture", "vlm_checkpoint": "<auto>"},
  "init_should_raise": null,
  "segments": {
    "*": {
      "scenario": "ok_first_try",
      "responses": [{
        "phase": "approach_object", "verb": "approach", "object": "block",
        "target": null, "vlm_confidence": 0.85,
        "evidence": "gripper open, EEF moving"
      }]
    }
  }
}
```

`tests/fixtures/vlm/retry_then_ok.json`:

```json
{
  "model_identity": {"vlm_model": "fixture", "vlm_checkpoint": "<auto>"},
  "init_should_raise": null,
  "segments": {
    "s_001": {
      "scenario": "ok_after_2_retries",
      "responses": [
        {"_emit_raw": "garbage not json"},
        {"_emit_raw": "{\"phase\":\"made_up_label\",\"vlm_confidence\":0.5}"},
        {
          "phase": "grasp_object", "verb": "grasp", "object": "block",
          "target": null, "vlm_confidence": 0.72, "evidence": "gripper closing"
        }
      ]
    },
    "*": {
      "scenario": "ok_first_try",
      "responses": [{
        "phase": "idle", "verb": null, "object": null, "target": null,
        "vlm_confidence": 0.6, "evidence": null
      }]
    }
  }
}
```

`tests/fixtures/vlm/fallback_unknown.json`:

```json
{
  "model_identity": {"vlm_model": "fixture", "vlm_checkpoint": "<auto>"},
  "init_should_raise": null,
  "segments": {
    "s_002": {
      "scenario": "fallback_to_unknown",
      "responses": [
        {"_emit_raw": "broken"},
        {"_emit_raw": "broken"},
        {"_emit_raw": "broken"}
      ]
    },
    "*": {
      "scenario": "ok_first_try",
      "responses": [{
        "phase": "idle", "verb": null, "object": null, "target": null,
        "vlm_confidence": 0.6, "evidence": null
      }]
    }
  }
}
```

`tests/fixtures/vlm/runtime_oom.json`:

```json
{
  "model_identity": {"vlm_model": "fixture", "vlm_checkpoint": "<auto>"},
  "init_should_raise": null,
  "segments": {
    "*": {
      "scenario": "runtime_error",
      "_raise_each_attempt": "LabelerRuntimeError(cuda_oom)"
    }
  }
}
```

`tests/fixtures/vlm/init_should_raise.json`:

```json
{
  "model_identity": {"vlm_model": "fixture", "vlm_checkpoint": "<auto>"},
  "init_should_raise": "RuntimeError(\"fake init failure\")",
  "segments": {}
}
```

- [ ] **Step 2: Write failing tests.**

Create `tests/unit/test_fixture_labeler.py`:

```python
"""FixtureVLMLabeler scenario replay tests (spec §5.5)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from mimicanno.vlm_labeler import (
    FixtureVLMLabeler,
    LabelerError,
    LabelerRuntimeError,
    VLMRequest,
)

FIXT = Path(__file__).resolve().parents[1] / "fixtures" / "vlm"


def _req(segment_index: int = 1) -> VLMRequest:
    return VLMRequest(
        task_text="t", allowed_labels=["idle", "approach_object", "grasp_object"],
        label_version="manipulation.v1", robot_type="aloha", fps=30.0,
        episode_duration_sec=10.0, segment_index=segment_index, segment_total=8,
        keyframes=[np.zeros((4, 4, 3), dtype=np.uint8)],
        keyframe_offsets_sec=[0.0],
        robot_state_summary={
            "duration_sec": 1.0, "mean_eef_speed_mps": None,
            "gripper_open_fraction": 0.5, "gripper_transitions": 0,
            "dwell_fraction": None,
        },
    )


def test_ok_first_try() -> None:
    lab = FixtureVLMLabeler(FIXT / "ok_first_try.json")
    req = _req()
    r = lab.label_segment(req, attempt=1, segment_id="s_000")
    assert r["phase"] == "approach_object"


def test_retry_then_ok_first_attempt_raises_then_succeeds() -> None:
    lab = FixtureVLMLabeler(FIXT / "retry_then_ok.json")
    req = _req()
    with pytest.raises(LabelerError) as ei:
        lab.label_segment(req, attempt=1, segment_id="s_001")
    assert ei.value.reject_reason == "json_parse_error"
    with pytest.raises(LabelerError) as ei:
        lab.label_segment(req, attempt=2, segment_id="s_001")
    assert ei.value.reject_reason == "invalid_label"
    r = lab.label_segment(req, attempt=3, segment_id="s_001")
    assert r["phase"] == "grasp_object"


def test_fallback_unknown_three_attempts_all_raise() -> None:
    lab = FixtureVLMLabeler(FIXT / "fallback_unknown.json")
    req = _req()
    for attempt in (1, 2, 3):
        with pytest.raises(LabelerError):
            lab.label_segment(req, attempt=attempt, segment_id="s_002")


def test_runtime_oom_raises_labeler_runtime_error() -> None:
    lab = FixtureVLMLabeler(FIXT / "runtime_oom.json")
    req = _req()
    with pytest.raises(LabelerRuntimeError) as ei:
        lab.label_segment(req, attempt=1, segment_id="s_007")
    assert ei.value.reason == "cuda_oom"


def test_init_should_raise_makes_constructor_fail() -> None:
    with pytest.raises(RuntimeError):
        FixtureVLMLabeler(FIXT / "init_should_raise.json")


def test_model_identity_uses_file_sha256() -> None:
    """Spec §5.5: vlm_checkpoint = sha256 of fixture file content."""
    import hashlib
    lab = FixtureVLMLabeler(FIXT / "ok_first_try.json")
    expected = hashlib.sha256((FIXT / "ok_first_try.json").read_bytes()).hexdigest()
    assert lab.model_identity()["vlm_checkpoint"] == expected
    assert lab.model_identity()["vlm_model"] == "fixture"


def test_wildcard_segment_match() -> None:
    """Star-key '*' applies to any segment_id not explicitly listed."""
    lab = FixtureVLMLabeler(FIXT / "ok_first_try.json")
    r = lab.label_segment(_req(), attempt=1, segment_id="any_segment_id_at_all")
    assert r["phase"] == "approach_object"
```

- [ ] **Step 3: Run failing tests.**

```
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/pytest tests/unit/test_fixture_labeler.py -v
```

Expected: ImportError on `FixtureVLMLabeler`.

- [ ] **Step 4: Append FixtureVLMLabeler to mimicanno/vlm_labeler.py.**

```python
import hashlib
import re as _re
from pathlib import Path

# Note: keep `Path` and `hashlib` imports at the module top in the final file;
# this code chunk shows them inline for clarity.

_FIXT_RUNTIME_PATTERN = _re.compile(
    r"^LabelerRuntimeError\((?P<reason>[a-z_]+)\)$"
)


class FixtureVLMLabeler:
    """Test/CI implementation that replays scenarios from a fixture JSON
    (spec §5.5). label_segment is signature-extended with `segment_id` so
    the fixture can route per segment; the protocol-level signature is
    backward-compatible because real impls take `**_` for extra kwargs."""

    def __init__(self, fixture_path: Path) -> None:
        self._fixture_path = Path(fixture_path)
        body = json.loads(self._fixture_path.read_text(encoding="utf-8"))
        init_raise = body.get("init_should_raise")
        if init_raise is not None:
            # The fixture asks the constructor to fail; we honor it BEFORE
            # any state is set so the failure is visible to the caller.
            raise RuntimeError(init_raise) if init_raise.startswith("RuntimeError") \
                else Exception(init_raise)
        self._segments: dict[str, dict] = body.get("segments", {})
        self._sha256 = hashlib.sha256(self._fixture_path.read_bytes()).hexdigest()
        # Per-segment, per-attempt cursor state when scenario uses _emit_raw lists.
        self._cursors: dict[str, int] = {}

    def model_identity(self) -> ModelIdentity:
        return ModelIdentity(vlm_model="fixture", vlm_checkpoint=self._sha256)

    def _route(self, segment_id: str) -> dict:
        if segment_id in self._segments:
            return self._segments[segment_id]
        if "*" in self._segments:
            return self._segments["*"]
        raise KeyError(f"fixture has no scenario for segment_id={segment_id!r} and no '*' wildcard")

    def label_segment(
        self, request: VLMRequest, attempt: int, segment_id: str
    ) -> VLMResponse:
        scen = self._route(segment_id)

        # runtime_error scenario: raise classified runtime fault on every call.
        raise_each = scen.get("_raise_each_attempt")
        if raise_each is not None:
            m = _FIXT_RUNTIME_PATTERN.match(raise_each)
            if m:
                reason = m.group("reason")
                raise LabelerRuntimeError(reason)  # type: ignore[arg-type]
            # Reject reason form: LabelerError(<reject_reason>)
            m2 = _re.match(r"^LabelerError\(([a-z_]+)\)$", raise_each)
            if m2:
                raise LabelerError(m2.group(1))  # type: ignore[arg-type]
            raise RuntimeError(f"unparseable _raise_each_attempt: {raise_each!r}")

        # Otherwise consume the responses list at index (attempt - 1).
        responses = scen.get("responses", [])
        idx = attempt - 1
        if idx >= len(responses):
            raise RuntimeError(
                f"fixture exhausted: segment_id={segment_id} attempt={attempt}"
            )
        spec = responses[idx]

        if "_emit_raw" in spec:
            # Pass through the validator so the LabelerError matches the
            # raw text's failure mode.
            return parse_and_validate(spec["_emit_raw"], set(request["allowed_labels"]))
        # Already a VLMResponse-shaped dict — round-trip through the validator
        # to keep the contract.
        as_text = json.dumps(spec)
        return parse_and_validate(as_text, set(request["allowed_labels"]))
```

(Also add `import hashlib`, `import re`, `from pathlib import Path` to the top of the file.)

- [ ] **Step 5: Run tests.**

```
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/pytest tests/unit/test_fixture_labeler.py -v
```

Expected: 7 passed.

- [ ] **Step 6: Commit.**

```bash
git add mimicanno/vlm_labeler.py tests/unit/test_fixture_labeler.py tests/fixtures/vlm/
git commit -m "feat(vlm_labeler): FixtureVLMLabeler with full scenario coverage (§5.5)"
```

---

## Task 9: `label_run` orchestrator — happy + retry + segment fallback paths

**Spec refs:** §2.3, §3.1, §4.4, §4.5.

**Files:**
- Modify: `mimicanno/vlm_labeler.py`
- Create: `tests/unit/test_label_run_success.py`

This task implements the orchestrator's success and segment-level paths only (no run-level degrade — that's Task 10). Constructor failure is converted to `vlm_init_failed` here too because it's part of the labeler-factory wrapping.

- [ ] **Step 1: Write failing tests.**

Create `tests/unit/test_label_run_success.py`:

```python
"""label_run — happy path, per-segment retry, segment-level fallback.
Run-level degrade triggers (vlm_init_failed / vlm_unreachable / vlm_runtime_failed)
are tested separately in test_label_run_degrade.py (spec §4.3)."""
from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
import pytest

from mimicanno.config import ClipFeatureConfig, VLMConfig
from mimicanno.vlm_labeler import (
    FixtureVLMLabeler,
    LabelAttempt,
    label_run,
)
from tests.unit.helpers_phase1 import (   # NEW thin helper, see Step 3
    make_synthetic_segments_aloha,
)

FIXT = Path(__file__).resolve().parents[1] / "fixtures" / "vlm"


def _vlm_config(model_id: str = "fixture") -> VLMConfig:
    return VLMConfig(
        model_id=model_id, resolved_checkpoint="abc",
        keyframes_per_segment=4, max_retries=3,
    )


def test_happy_path_all_segments_labeled() -> None:
    segs, signals, video, parquet = make_synthetic_segments_aloha(n_segments=4)
    cfg = _vlm_config()

    factory = lambda c: FixtureVLMLabeler(FIXT / "ok_first_try.json")
    labeled, attempts, outcome = label_run(
        segments=segs, signals=signals,
        video_path=video, parquet_path=parquet,
        config=cfg, labeler_factory=factory,
    )

    assert outcome.kind == "ok"
    assert outcome.degrade_reason is None
    assert all(s.phase == "approach_object" for s in labeled)
    assert all(s.label_source == "vlm_robot_state_only" for s in labeled)
    assert all(a.final_status == "ok" for a in attempts)
    assert all(a.attempt_count == 1 for a in attempts)


def test_retry_then_success() -> None:
    segs, signals, video, parquet = make_synthetic_segments_aloha(n_segments=2)
    # Force the second segment to be s_001 so it matches the fixture's
    # explicit per-segment scenario.
    segs[1].segment_id = "s_001"
    cfg = _vlm_config()
    factory = lambda c: FixtureVLMLabeler(FIXT / "retry_then_ok.json")
    labeled, attempts, outcome = label_run(
        segments=segs, signals=signals,
        video_path=video, parquet_path=parquet,
        config=cfg, labeler_factory=factory,
    )
    assert outcome.kind == "ok"
    a1 = next(a for a in attempts if a.segment_id == "s_001")
    assert a1.attempt_count == 3
    assert a1.reject_reasons == ["json_parse_error", "invalid_label"]
    assert labeled[1].phase == "grasp_object"


def test_segment_level_fallback_to_unknown() -> None:
    segs, signals, video, parquet = make_synthetic_segments_aloha(n_segments=3)
    segs[1].segment_id = "s_002"
    cfg = _vlm_config()
    factory = lambda c: FixtureVLMLabeler(FIXT / "fallback_unknown.json")
    labeled, attempts, outcome = label_run(
        segments=segs, signals=signals,
        video_path=video, parquet_path=parquet,
        config=cfg, labeler_factory=factory,
    )
    assert outcome.kind == "ok", "segment fallback must NOT trigger run-level degrade"
    a = next(a for a in attempts if a.segment_id == "s_002")
    assert a.final_status == "unknown_fallback"
    assert a.attempt_count == 3
    assert all(r == "json_parse_error" for r in a.reject_reasons)
    seg = next(s for s in labeled if s.segment_id == "s_002")
    assert seg.phase == "unknown"
    assert seg.vlm_confidence == 0.0
    assert seg.label_source == "vlm_robot_state_only"  # spec §4.4 invariant
    assert seg.overall_confidence == 0.0


def test_baseline_isolation_phase_does_not_leak_back() -> None:
    """Mutations on the working copy MUST NOT alter the caller's segments."""
    segs, signals, video, parquet = make_synthetic_segments_aloha(n_segments=2)
    snapshot = copy.deepcopy(segs)
    cfg = _vlm_config()
    factory = lambda c: FixtureVLMLabeler(FIXT / "ok_first_try.json")
    label_run(
        segments=segs, signals=signals,
        video_path=video, parquet_path=parquet,
        config=cfg, labeler_factory=factory,
    )
    for before, after in zip(snapshot, segs):
        assert before.phase == after.phase
        assert before.label_source == after.label_source
```

- [ ] **Step 2: Create the Phase 1 test helper module.**

Create `tests/unit/helpers_phase1.py`:

```python
"""Helpers for constructing Phase 1 SubtaskSegment fixtures + signal arrays
without invoking the full pipeline. Used by Phase 2 unit tests.
"""
from __future__ import annotations

from pathlib import Path
from typing import Tuple

import numpy as np

from mimicanno.schema import BoundaryRef, SubtaskSegment


def make_synthetic_segments_aloha(
    n_segments: int = 4, fps: float = 30.0, frames_per_seg: int = 30,
) -> Tuple[list[SubtaskSegment], dict, Path, Path]:
    """Produce n_segments unlabeled SubtaskSegments + a small SignalsBundle-like
    dict + dummy video/parquet paths. Phase 2 tests can use this without
    running boundary detection."""
    total_frames = n_segments * frames_per_seg
    gripper = np.tile(np.linspace(0.0, 1.0, frames_per_seg), n_segments).astype(np.float64)
    signals = {
        "gripper": gripper,
        "eef_velocity": np.zeros((total_frames, 3), dtype=np.float64),
        "fps": fps,
    }
    segments: list[SubtaskSegment] = []
    for i in range(n_segments):
        start = i * frames_per_seg
        end = start + frames_per_seg - 1
        segments.append(SubtaskSegment(
            segment_id=f"s_{i:03d}",
            episode_id="ep_synth",
            start_frame=start, end_frame=end,
            start_time=start / fps, end_time=(end + 1) / fps,
            phase="unlabeled",
            verb=None, object=None, target=None, failure_flags=[],
            label_source="signals_only",
            object_state_unavailable=True, object_track_ids=[],
            label_version="manipulation.v1",
            start_boundary=BoundaryRef(candidate_id=None, time=start / fps,
                                       sources=["episode_start"], score=1.0),
            end_boundary=BoundaryRef(candidate_id=None, time=(end + 1) / fps,
                                     sources=["episode_end"], score=1.0),
            boundary_confidence=1.0,
            vlm_confidence=None, overall_confidence=1.0,
            evidence=None, reviewed=False, reviewer_id=None,
        ))
    return segments, signals, Path("/tmp/_unused.mp4"), Path("/tmp/_unused.parquet")
```

- [ ] **Step 3: Run failing tests.**

```
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/pytest tests/unit/test_label_run_success.py -v
```

Expected: ImportError on `label_run` (also `helpers_phase1` if not yet created).

- [ ] **Step 4: Implement label_run in mimicanno/vlm_labeler.py.**

Append:

```python
import copy
from typing import Callable

from mimicanno.clip_features import (
    RobotStateSummary,
    compute_keyframe_offsets,
    compute_robot_state_summary,
)
from mimicanno.config import VLMConfig
from mimicanno.schema import SubtaskSegment


LabelerFactory = Callable[[VLMConfig], "VLMLabeler"]


def _build_request(
    segment: SubtaskSegment, segment_index: int, segment_total: int,
    signals: dict, video_path: Path, config: VLMConfig,
) -> VLMRequest:
    """Build a VLMRequest by extracting K_effective keyframes and computing
    the robot-state summary. Keyframe extraction itself happens in the
    pipeline (Task 13) — for orchestrator unit tests we attach an empty
    keyframes list when called via this helper without real video."""
    offs = compute_keyframe_offsets(
        segment.start_frame, segment.end_frame, config.keyframes_per_segment,
    )
    fps = signals.get("fps", 30.0)
    summary = compute_robot_state_summary(
        start_frame=segment.start_frame, end_frame=segment.end_frame, fps=fps,
        gripper=signals["gripper"],
        eef_velocity=signals.get("eef_velocity"),
        cfg=config.clip_features,
    )
    keyframes_offsets_sec = [(o - segment.start_frame) / fps for o in offs]
    keyframes = signals.get("_keyframes_for_segment", lambda _seg, _offs: [])(segment, offs)
    return VLMRequest(
        task_text=signals.get("task_text", ""),
        allowed_labels=list(signals.get("allowed_labels", [])),
        label_version=signals.get("label_version", "manipulation.v1"),
        robot_type=signals.get("robot_type", "aloha"),
        fps=fps,
        episode_duration_sec=signals.get("episode_duration_sec", 0.0),
        segment_index=segment_index, segment_total=segment_total,
        keyframes=keyframes,
        keyframe_offsets_sec=keyframes_offsets_sec,
        robot_state_summary=summary,  # type: ignore[typeddict-item]
    )


def _merge_response(
    seg: SubtaskSegment, resp: VLMResponse, fallback: bool,
) -> SubtaskSegment:
    import math
    seg.phase = resp["phase"]
    seg.verb = resp["verb"]
    seg.object = resp["object"]
    seg.target = resp["target"]
    seg.label_source = "vlm_robot_state_only"  # §4.4 invariant
    seg.vlm_confidence = resp["vlm_confidence"]
    seg.evidence = resp["evidence"]
    if seg.phase in ("unlabeled", "unknown"):
        seg.overall_confidence = 0.0
    else:
        seg.overall_confidence = math.sqrt(
            max(seg.boundary_confidence, 0.0) * max(seg.vlm_confidence, 0.0)
        )
    seg.object_state_unavailable = True
    seg.object_track_ids = []
    return seg


def label_run(
    *,
    segments: list[SubtaskSegment],
    signals: dict,
    video_path: Path,
    parquet_path: Path,
    config: VLMConfig,
    labeler_factory: LabelerFactory,
) -> tuple[list[SubtaskSegment], list[LabelAttempt], RunOutcome]:
    """Phase 2 labeling lifecycle owner — see spec §2.3 for the contract.

    Constructor failures, vlm_unreachable on first call, and
    runtime_failure_threshold escalation all return the Phase 1 baseline
    with a degraded RunOutcome; partial labels never leak."""
    baseline = copy.deepcopy(segments)
    working = copy.deepcopy(segments)
    attempts: list[LabelAttempt] = []

    # 1. Construct labeler, catching __init__ failures as vlm_init_failed.
    try:
        labeler = labeler_factory(config)
    except Exception as e:
        return baseline, [], RunOutcome(
            kind="degraded", degrade_reason="vlm_init_failed",
            underlying_error=repr(e),
        )

    consecutive_runtime_failures = 0
    n = len(working)
    for idx, seg in enumerate(working):
        attempt_log = LabelAttempt(
            segment_id=seg.segment_id, attempt_count=0, final_status="ok",
        )
        attempts.append(attempt_log)
        request = _build_request(seg, segment_index=idx + 1, segment_total=n,
                                  signals=signals, video_path=video_path, config=config)
        last_reject: RejectReason | None = None
        success = False
        for attempt in range(1, config.max_retries + 1):
            attempt_log.attempt_count = attempt
            try:
                resp = labeler.label_segment(request, attempt=attempt,
                                             segment_id=seg.segment_id)  # type: ignore[call-arg]
                consecutive_runtime_failures = 0
                _merge_response(seg, resp, fallback=False)
                attempt_log.final_status = "ok"
                attempt_log.response = resp
                success = True
                break
            except LabelerError as e:
                attempt_log.reject_reasons.append(e.reject_reason)
                last_reject = e.reject_reason
                continue
            except LabelerRuntimeError as e:
                attempt_log.runtime_errors.append(e.reason)
                # vlm_unreachable: first-ever call, fail-fast.
                if (idx == 0 and attempt == 1
                        and e.reason in ("model_unreachable", "device_unavailable")):
                    return baseline, attempts, RunOutcome(
                        kind="degraded", degrade_reason="vlm_unreachable",
                        underlying_error=repr(e),
                    )
                consecutive_runtime_failures += 1
                if consecutive_runtime_failures >= config.runtime_failure_threshold:
                    return baseline, attempts, RunOutcome(
                        kind="degraded", degrade_reason="vlm_runtime_failed",
                        underlying_error=repr(e),
                    )
                continue
        if not success:
            fallback_resp = VLMResponse(
                phase="unknown", verb=None, object=None, target=None,
                vlm_confidence=0.0, evidence=None,
            )
            _merge_response(seg, fallback_resp, fallback=True)
            attempt_log.final_status = "unknown_fallback"
            attempt_log.response = fallback_resp

    return working, attempts, RunOutcome(kind="ok", degrade_reason=None,
                                          underlying_error=None)
```

(Also: extend `VLMLabeler` Protocol with `segment_id: str` kwarg, since FixtureVLMLabeler/Local need it. Use `**_` for forward compatibility.)

- [ ] **Step 5: Run tests.**

```
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/pytest tests/unit/test_label_run_success.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Commit.**

```bash
git add mimicanno/vlm_labeler.py tests/unit/test_label_run_success.py tests/unit/helpers_phase1.py
git commit -m "feat(vlm_labeler): label_run orchestrator — success + retry + fallback (§2.3, §4.4)"
```

---

## Task 10: `label_run` — degrade paths

**Spec refs:** §4.3 (vlm_init_failed / vlm_unreachable / vlm_runtime_failed).

**Files:**
- Create: `tests/unit/test_label_run_degrade.py`

The orchestrator already has the degrade paths from Task 9; this task lock-tests them comprehensively, including the transactional-baseline invariant.

- [ ] **Step 1: Write tests covering all 3 run-level degrade triggers.**

```python
"""label_run — run-level degrade triggers (spec §4.3)."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from mimicanno.config import VLMConfig
from mimicanno.vlm_labeler import (
    FixtureVLMLabeler,
    LabelerRuntimeError,
    VLMLabeler,
    VLMRequest,
    VLMResponse,
    label_run,
    ModelIdentity,
)
from tests.unit.helpers_phase1 import make_synthetic_segments_aloha


FIXT = Path(__file__).resolve().parents[1] / "fixtures" / "vlm"


def _vlm_config(rt_thresh: int = 3) -> VLMConfig:
    return VLMConfig(model_id="fixture", resolved_checkpoint="x",
                     runtime_failure_threshold=rt_thresh, max_retries=3)


# ---- vlm_init_failed ------------------------------------------------------

def test_init_should_raise_returns_baseline_and_degrade() -> None:
    segs, signals, video, parquet = make_synthetic_segments_aloha(n_segments=3)
    snapshot = copy.deepcopy(segs)
    cfg = _vlm_config()
    factory = lambda c: FixtureVLMLabeler(FIXT / "init_should_raise.json")
    labeled, attempts, outcome = label_run(
        segments=segs, signals=signals, video_path=video,
        parquet_path=parquet, config=cfg, labeler_factory=factory,
    )
    assert outcome.kind == "degraded"
    assert outcome.degrade_reason == "vlm_init_failed"
    assert outcome.underlying_error is not None
    # Baseline preserved exactly.
    for before, after in zip(snapshot, labeled):
        assert (before.phase, before.label_source) == (after.phase, after.label_source)
    # No attempts because no segment was processed.
    assert attempts == []


# ---- vlm_unreachable (first-call fail-fast) ------------------------------

class _FirstCallUnreachable:
    """Minimal labeler that raises model_unreachable on every call."""
    def label_segment(self, request, attempt, segment_id, **_):
        raise LabelerRuntimeError("model_unreachable")
    def model_identity(self):
        return ModelIdentity(vlm_model="fake", vlm_checkpoint="x")


def test_first_call_unreachable_short_circuits() -> None:
    segs, signals, video, parquet = make_synthetic_segments_aloha(n_segments=5)
    snapshot = copy.deepcopy(segs)
    cfg = _vlm_config()
    labeled, attempts, outcome = label_run(
        segments=segs, signals=signals, video_path=video, parquet_path=parquet,
        config=cfg, labeler_factory=lambda c: _FirstCallUnreachable(),
    )
    assert outcome.degrade_reason == "vlm_unreachable"
    # Only segment 0 was attempted, and the very first call escalated.
    assert len(attempts) == 1
    assert attempts[0].runtime_errors == ["model_unreachable"]
    # Baseline preserved on all 5 segments.
    for before, after in zip(snapshot, labeled):
        assert (before.phase, before.label_source) == (after.phase, after.label_source)


# ---- vlm_runtime_failed (consecutive threshold) --------------------------

def test_consecutive_runtime_failures_trigger_degrade() -> None:
    segs, signals, video, parquet = make_synthetic_segments_aloha(n_segments=5)
    snapshot = copy.deepcopy(segs)
    cfg = _vlm_config(rt_thresh=3)
    factory = lambda c: FixtureVLMLabeler(FIXT / "runtime_oom.json")
    labeled, attempts, outcome = label_run(
        segments=segs, signals=signals, video_path=video, parquet_path=parquet,
        config=cfg, labeler_factory=factory,
    )
    assert outcome.degrade_reason == "vlm_runtime_failed"
    # Baseline preserved on every segment.
    for before, after in zip(snapshot, labeled):
        assert (before.phase, before.label_source) == (after.phase, after.label_source)


def test_runtime_failures_reset_on_success() -> None:
    """A successful call between two flaky ones resets the consecutive counter."""
    class _FlakyThenOK:
        def __init__(self) -> None:
            self.calls = 0
        def label_segment(self, request, attempt, segment_id, **_):
            self.calls += 1
            # Pattern: cuda_oom (segment 0 attempt 1)
            #          cuda_oom (segment 0 attempt 2)
            #          OK       (segment 0 attempt 3)
            #          cuda_oom (segment 1 attempt 1)
            #          OK       (segment 1 attempt 2)
            #          OK       (segment 2..)
            if self.calls in (1, 2, 4):
                raise LabelerRuntimeError("cuda_oom")
            return VLMResponse(phase="idle", verb=None, object=None,
                               target=None, vlm_confidence=0.5, evidence=None)
        def model_identity(self):
            return ModelIdentity(vlm_model="x", vlm_checkpoint="y")

    segs, signals, video, parquet = make_synthetic_segments_aloha(n_segments=3)
    cfg = _vlm_config(rt_thresh=3)
    labeled, attempts, outcome = label_run(
        segments=segs, signals=signals, video_path=video, parquet_path=parquet,
        config=cfg, labeler_factory=lambda c: _FlakyThenOK(),
    )
    assert outcome.kind == "ok", "non-consecutive faults must NOT degrade"
    assert all(s.phase == "idle" for s in labeled)
```

- [ ] **Step 2: Run tests.**

```
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/pytest tests/unit/test_label_run_degrade.py -v
```

Expected: 4 passed.

- [ ] **Step 3: Commit.**

```bash
git add tests/unit/test_label_run_degrade.py
git commit -m "test(vlm_labeler): label_run run-level degrade triggers (§4.3)"
```

---

## Task 11: `LocalGemmaVLMLabeler` skeleton (constructor + model_identity)

**Spec refs:** §2.2, §8 #1.

**Files:**
- Modify: `mimicanno/vlm_labeler.py`
- Create: `tests/unit/test_local_gemma_skeleton.py`

This task pins the **default** `LocalGemmaVLMLabeler` model_id and stubs the constructor to load via `transformers.AutoModelForVision2Seq` + `AutoProcessor`. The actual `label_segment` body (image preprocessing + tokenization + generation + decode + parse_and_validate) is implemented in Task 12 along with exception classification.

> **Implementer action required:** before writing this task's code, run:
> ```bash
> env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH .venv/bin/python -c \
>   "from huggingface_hub import HfApi; \
>    info = HfApi().list_models(filter='gemma', sort='downloads', direction=-1, limit=10); \
>    [print(m.modelId) for m in info]"
> ```
> Verify the latest published Gemma 4 multimodal IT variant. Common candidates as of 2026-04: `google/gemma-3n-E2B-it`, `google/gemma-4-2b-it`, `google/paligemma2-3b-mix-448`. **Pin one** as the documented default in this task's docstring and `tests/test_phase2_real_vlm.py` (Task 18).

- [ ] **Step 1: Write failing skeleton tests using mocks.**

Create `tests/unit/test_local_gemma_skeleton.py`:

```python
"""LocalGemmaVLMLabeler constructor + model_identity — mock-based unit tests.

The real model load is tested in tests/test_phase2_real_vlm.py (env-gated)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mimicanno.config import VLMConfig
from mimicanno.vlm_labeler import LocalGemmaVLMLabeler


def _cfg(**overrides) -> VLMConfig:
    return VLMConfig(
        model_id=overrides.get("model_id", "google/gemma-x"),
        resolved_checkpoint=overrides.get("resolved_checkpoint", "abc123" + "0" * 34),
        device=overrides.get("device", "cpu"),
        dtype=overrides.get("dtype", "bfloat16"),
    )


@patch("mimicanno.vlm_labeler._hf_load_model_and_processor")
def test_constructor_calls_loader_with_resolved_revision(load_mock: MagicMock) -> None:
    load_mock.return_value = (MagicMock(), MagicMock())
    cfg = _cfg(model_id="google/gemma-x", resolved_checkpoint="b" * 40)
    LocalGemmaVLMLabeler(cfg)
    load_mock.assert_called_once_with(
        model_id="google/gemma-x", revision="b" * 40,
        device="cpu", dtype="bfloat16",
    )


def test_model_identity_uses_pre_flight_resolved_pair() -> None:
    with patch("mimicanno.vlm_labeler._hf_load_model_and_processor",
               return_value=(MagicMock(), MagicMock())):
        cfg = _cfg(model_id="google/gemma-x", resolved_checkpoint="d" * 40)
        lab = LocalGemmaVLMLabeler(cfg)
    mi = lab.model_identity()
    assert mi == {"vlm_model": "google/gemma-x", "vlm_checkpoint": "d" * 40}


def test_constructor_propagates_loader_exception_unwrapped() -> None:
    """Constructor failures bubble unchanged; label_run wraps them as
    vlm_init_failed (§2.3)."""
    boom = OSError("weights file missing")
    with patch("mimicanno.vlm_labeler._hf_load_model_and_processor",
               side_effect=boom):
        with pytest.raises(OSError, match="weights file missing"):
            LocalGemmaVLMLabeler(_cfg())


def test_resolved_checkpoint_required() -> None:
    with pytest.raises(ValueError, match="resolved_checkpoint"):
        LocalGemmaVLMLabeler(VLMConfig(model_id="x", resolved_checkpoint=None))
```

- [ ] **Step 2: Run failing tests.**

Expected: ImportError on `LocalGemmaVLMLabeler`.

- [ ] **Step 3: Append the skeleton to mimicanno/vlm_labeler.py.**

```python
DEFAULT_LOCAL_GEMMA_MODEL_ID = "google/gemma-3n-E2B-it"  # ← VERIFY before merge


def _hf_load_model_and_processor(
    *, model_id: str, revision: str, device: str, dtype: str,
) -> tuple[object, object]:
    """Load the HF model + processor at the pre-flight-resolved revision.
    Isolated for monkeypatching in unit tests."""
    import torch
    from transformers import AutoModelForVision2Seq, AutoProcessor
    torch_dtype = {"bfloat16": torch.bfloat16, "float16": torch.float16,
                   "float32": torch.float32}[dtype]
    model = AutoModelForVision2Seq.from_pretrained(
        model_id, revision=revision, torch_dtype=torch_dtype,
    ).to(device).eval()
    processor = AutoProcessor.from_pretrained(model_id, revision=revision)
    return model, processor


class LocalGemmaVLMLabeler:
    """Default real implementation — Gemma 4-family multimodal IT loaded via
    HuggingFace transformers (spec §2.2). Documented default: `{DEFAULT_LOCAL_GEMMA_MODEL_ID}`.

    The constructor loads the model + processor against the pre-flight-resolved
    revision (§2.5); it never re-resolves. Failures propagate unwrapped — the
    label_run orchestrator catches them at the labeler-factory boundary and
    converts to vlm_init_failed degrade.
    """

    def __init__(self, config: VLMConfig) -> None:
        if config.resolved_checkpoint is None:
            raise ValueError("resolved_checkpoint must be set by pre-flight (§2.5)")
        self._config = config
        self._model, self._processor = _hf_load_model_and_processor(
            model_id=config.model_id,
            revision=config.resolved_checkpoint,
            device=config.device,
            dtype=config.dtype,
        )

    def model_identity(self) -> ModelIdentity:
        return ModelIdentity(
            vlm_model=self._config.model_id,
            vlm_checkpoint=self._config.resolved_checkpoint or "",
        )

    def label_segment(
        self, request: VLMRequest, attempt: int, segment_id: str
    ) -> VLMResponse:
        # Body added in Task 12 (with exception classification).
        raise NotImplementedError("LocalGemmaVLMLabeler.label_segment lands in Task 12")
```

- [ ] **Step 4: Run tests.**

Expected: 4 passed.

- [ ] **Step 5: Commit.**

```bash
git add mimicanno/vlm_labeler.py tests/unit/test_local_gemma_skeleton.py
git commit -m "feat(vlm_labeler): LocalGemmaVLMLabeler skeleton + identity + loader hook (§2.2)"
```

---

## Task 12: `LocalGemmaVLMLabeler.label_segment` body + exception classification

**Spec refs:** §2.2, §3.3, §3.4.

**Files:**
- Modify: `mimicanno/vlm_labeler.py`
- Modify: `tests/unit/test_local_gemma_skeleton.py`

The body wires together: prompt assembly (`vlm_prompt.build_prompt`), image preprocessing via processor, generation with deterministic settings, decode, and `parse_and_validate`. Exception classification wraps PyTorch / HF exceptions into `LabelerRuntimeError(reason=...)`.

- [ ] **Step 1: Add new tests to `tests/unit/test_local_gemma_skeleton.py`.**

```python
import torch  # type: ignore[import-untyped]


@patch("mimicanno.vlm_labeler._hf_load_model_and_processor")
def test_label_segment_classifies_cuda_oom(load_mock: MagicMock) -> None:
    model = MagicMock()
    processor = MagicMock()
    load_mock.return_value = (model, processor)
    model.generate.side_effect = torch.cuda.OutOfMemoryError("CUDA OOM")
    cfg = _cfg()
    lab = LocalGemmaVLMLabeler(cfg)
    request = _minimal_request()  # NEW helper, defined in this test file

    from mimicanno.vlm_labeler import LabelerRuntimeError
    with pytest.raises(LabelerRuntimeError) as ei:
        lab.label_segment(request, attempt=1, segment_id="s_000")
    assert ei.value.reason == "cuda_oom"


@patch("mimicanno.vlm_labeler._hf_load_model_and_processor")
def test_label_segment_classifies_timeout(load_mock: MagicMock) -> None:
    model = MagicMock()
    processor = MagicMock()
    load_mock.return_value = (model, processor)
    model.generate.side_effect = TimeoutError("inference > timeout_sec")
    cfg = _cfg()
    lab = LocalGemmaVLMLabeler(cfg)

    from mimicanno.vlm_labeler import LabelerRuntimeError
    with pytest.raises(LabelerRuntimeError) as ei:
        lab.label_segment(_minimal_request(), attempt=1, segment_id="s_000")
    assert ei.value.reason == "inference_timeout"


@patch("mimicanno.vlm_labeler._hf_load_model_and_processor")
def test_label_segment_returns_validated_response_on_clean_decode(
    load_mock: MagicMock,
) -> None:
    model = MagicMock()
    processor = MagicMock()
    load_mock.return_value = (model, processor)
    model.generate.return_value = MagicMock()  # token ids
    processor.batch_decode.return_value = [
        '{"phase": "idle", "vlm_confidence": 0.5}'
    ]
    cfg = _cfg()
    lab = LocalGemmaVLMLabeler(cfg)
    r = lab.label_segment(_minimal_request(), attempt=1, segment_id="s_000")
    assert r["phase"] == "idle"
```

Add `_minimal_request` helper in the same file.

- [ ] **Step 2: Run failing tests.**

Expected: NotImplementedError or AttributeError on the new tests.

- [ ] **Step 3: Replace the NotImplementedError stub with the real body.**

```python
    def label_segment(
        self, request: VLMRequest, attempt: int, segment_id: str
    ) -> VLMResponse:
        from mimicanno.vlm_prompt import build_prompt

        # Build prompt + assemble multimodal inputs via the processor.
        last_reject = None  # caller's responsibility; for v1 we keep prompt static per attempt
        prompt = build_prompt(request, attempt=attempt, last_reject_reason=last_reject)
        try:
            inputs = self._processor(
                text=prompt, images=request["keyframes"], return_tensors="pt"
            ).to(self._config.device)
            with self._timeout_guard():
                tokens = self._model.generate(
                    **inputs,
                    do_sample=False,
                    temperature=self._config.temperature,
                    max_new_tokens=self._config.max_output_tokens,
                )
            decoded = self._processor.batch_decode(
                tokens, skip_special_tokens=True
            )[0]
        except Exception as e:
            self._raise_classified(e)
            raise  # unreachable; helps static analysis

        # Strip prompt prefix if the model echoes input back.
        if decoded.startswith(prompt):
            decoded = decoded[len(prompt):]

        return parse_and_validate(decoded.strip(),
                                   set(request["allowed_labels"]))

    def _timeout_guard(self):  # context manager
        import contextlib, signal
        @contextlib.contextmanager
        def _gm():
            def _handler(signum, frame):  # type: ignore[no-untyped-def]
                raise TimeoutError(f"inference exceeded {self._config.timeout_sec}s")
            old = signal.signal(signal.SIGALRM, _handler)
            signal.setitimer(signal.ITIMER_REAL, self._config.timeout_sec)
            try:
                yield
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, old)
        return _gm()

    def _raise_classified(self, e: Exception) -> None:
        """Map low-level PyTorch / HF exceptions into LabelerRuntimeError(reason)."""
        import torch
        if isinstance(e, torch.cuda.OutOfMemoryError):
            raise LabelerRuntimeError("cuda_oom") from e
        if isinstance(e, TimeoutError):
            raise LabelerRuntimeError("inference_timeout") from e
        if isinstance(e, ConnectionError) or "connection" in str(e).lower():
            raise LabelerRuntimeError("model_unreachable") from e
        if isinstance(e, RuntimeError) and "device" in str(e).lower():
            raise LabelerRuntimeError("device_unavailable") from e
        # Anything else propagates — implementation bug, NOT a runtime fault.
        raise e
```

- [ ] **Step 4: Run tests.**

Expected: 7 passed (4 original + 3 new).

- [ ] **Step 5: Commit.**

```bash
git add mimicanno/vlm_labeler.py tests/unit/test_local_gemma_skeleton.py
git commit -m "feat(vlm_labeler): LocalGemmaVLMLabeler.label_segment + exception classifier (§2.2, §3.3)"
```

---

## Task 13: Pipeline integration (`mimicanno/pipeline.py`)

**Spec refs:** §1.1, §1.3, §3.5, §4.3.

**Files:**
- Modify: `mimicanno/pipeline.py`

Wire the orchestrator into the existing pipeline's run flow. Specifically:
1. After Phase 1 segment bracketing, branch on `target_phase >= 2`.
2. Compose a `signals` dict (existing `SignalsBundle` repackaged + episode-level extras like `task_text`, `allowed_labels`, `_keyframes_for_segment` callback that uses `io_video.extract_frames`).
3. Call `vlm_labeler.label_run(...)` with a labeler factory determined by `--vlm-model`.
4. Populate `manifest.model_versions.vlm`, `manifest.pipeline_status.degraded_from_phase / degrade_reason`, `manifest.pipeline_params.vlm`, `annotation.notes`.
5. Emit structured `vlm_attempt` / `vlm_segment_fallback` / `vlm_run_degrade` JSONL events to stderr.

- [ ] **Step 1: Read the existing pipeline.py to understand the structure.**

```bash
sed -n '1,80p' mimicanno/pipeline.py
```

Identify:
- The function that orchestrates Phase 1 (boundary → bracketing → SubtaskSegments).
- Where `manifest.model_versions`, `manifest.pipeline_params`, `annotation.notes`, `pipeline_status` are constructed.
- The control flow around `target_phase`.

- [ ] **Step 2: Write the integration shape.**

Append a new function `apply_phase2_labeling` to `pipeline.py`:

```python
import json as _json
import sys as _sys

from mimicanno.vlm_labeler import (
    FixtureVLMLabeler, LocalGemmaVLMLabeler, label_run, RunOutcome,
)


def _make_labeler_factory(vlm_config: VLMConfig):
    if vlm_config.model_id == "fixture":
        # Fixture URI was resolved by pre-flight; we recover the path from
        # resolved_checkpoint by storing the original path on the config
        # at CLI parse time (Task 14 wires this).
        # For now, accept VLMConfig.model_id == "fixture" + a fixture_path
        # smuggled in via `device` (a hack for test code paths only).
        ...   # see Task 14 for the proper implementation
    return lambda c: LocalGemmaVLMLabeler(c)


def _emit_vlm_log(event: dict) -> None:
    _sys.stderr.write(_json.dumps(event, ensure_ascii=False) + "\n")
    _sys.stderr.flush()


def apply_phase2_labeling(
    *,
    segments: list[SubtaskSegment],
    signals: dict,
    video_path: Path,
    parquet_path: Path,
    vlm_config: VLMConfig,
    labeler_factory_override: LabelerFactory | None = None,
) -> tuple[list[SubtaskSegment], RunOutcome, str | None]:
    """Phase 2 wrapper. Returns (labeled_segments, outcome, notes_aggregate)."""
    factory = labeler_factory_override or _make_labeler_factory(vlm_config)
    labeled, attempts, outcome = label_run(
        segments=segments, signals=signals, video_path=video_path,
        parquet_path=parquet_path, config=vlm_config, labeler_factory=factory,
    )
    # Emit per-attempt observation log.
    for a in attempts:
        for i, reason in enumerate(a.reject_reasons, start=1):
            _emit_vlm_log({
                "event": "vlm_attempt", "segment_id": a.segment_id,
                "attempt": i, "status": "rejected", "reject_reason": reason,
            })
        for i, reason in enumerate(a.runtime_errors, start=1):
            _emit_vlm_log({
                "event": "vlm_runtime_fault", "segment_id": a.segment_id,
                "attempt": i, "reason": reason,
            })
        if a.final_status == "ok":
            _emit_vlm_log({
                "event": "vlm_attempt", "segment_id": a.segment_id,
                "attempt": a.attempt_count, "status": "ok",
                "vlm_confidence": a.response["vlm_confidence"],
            })
        else:
            _emit_vlm_log({
                "event": "vlm_segment_fallback", "segment_id": a.segment_id,
                "attempts": a.attempt_count,
                "reject_reasons": list(a.reject_reasons),
            })

    if outcome.kind == "degraded":
        _emit_vlm_log({
            "event": "vlm_run_degrade",
            "degrade_reason": outcome.degrade_reason,
            "underlying_error": outcome.underlying_error,
        })
        notes = (
            f"vlm_labeler: degraded to Phase 1 output "
            f"(degrade_reason={outcome.degrade_reason}); 0/{len(segments)} segments labeled."
        )
        return labeled, outcome, notes

    n_ok = sum(1 for a in attempts if a.final_status == "ok")
    n_fallback = sum(1 for a in attempts if a.final_status == "unknown_fallback")
    n_retried = sum(1 for a in attempts if a.attempt_count > 1)
    notes = (
        f"vlm_labeler: {n_ok + n_fallback}/{len(segments)} segments labeled; "
        f"{n_retried} needed retry; {n_fallback} fell back to unknown."
    )
    return labeled, outcome, notes
```

Then wire `apply_phase2_labeling` into the existing run-builder. The exact insertion point depends on the existing pipeline.py layout (read it in Step 1); broadly: **after** the Phase 1 segments are produced and **before** the `AnnotationResult` is constructed.

Updates to manifest construction:
- `manifest.generator.pipeline_phase = config.target_phase`
- `manifest.model_versions.vlm = f"{vlm_config.model_id}:{vlm_config.resolved_checkpoint}"` if `target_phase >= 2`
- `manifest.pipeline_params["vlm"] = vlm_config.to_dict()` if `target_phase >= 2`
- `manifest.pipeline_status.degraded_from_phase = config.target_phase if outcome.kind == "degraded" else None`
- `manifest.pipeline_status.degrade_reason = outcome.degrade_reason`
- `manifest.pipeline_status.object_state_available = False`

- [ ] **Step 3: Run existing Phase 1 integration tests to confirm no regression.**

```
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/pytest tests/integration/ -k phase1 -v
```

Expected: all green (Phase 1 path is target_phase=1 with `vlm_config = None`).

- [ ] **Step 4: Add a small unit test for `apply_phase2_labeling`'s notes aggregation.**

Add to `tests/unit/test_label_run_success.py` or a new `test_pipeline_phase2.py`:

```python
def test_apply_phase2_labeling_aggregates_notes() -> None:
    segs, signals, video, parquet = make_synthetic_segments_aloha(n_segments=2)
    cfg = _vlm_config()
    factory = lambda c: FixtureVLMLabeler(FIXT / "ok_first_try.json")
    from mimicanno.pipeline import apply_phase2_labeling
    _, outcome, notes = apply_phase2_labeling(
        segments=segs, signals=signals, video_path=video, parquet_path=parquet,
        vlm_config=cfg, labeler_factory_override=factory,
    )
    assert outcome.kind == "ok"
    assert "2/2 segments labeled" in notes
```

- [ ] **Step 5: Run.**

```
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/pytest tests/unit/ -v
```

Expected: full unit suite green.

- [ ] **Step 6: Commit.**

```bash
git add mimicanno/pipeline.py tests/unit/
git commit -m "feat(pipeline): wire apply_phase2_labeling + structured stderr log (§3.5, §4.6)"
```

---

## Task 14: CLI integration (`mimicanno/cli.py`)

**Spec refs:** §1.3, §2.5, §4.2.

**Files:**
- Modify: `mimicanno/cli.py`
- Create: `tests/integration/test_phase2_cli_abort.py`

Add the new flags, invoke pre-flight, abort cleanly when prerequisites are missing.

- [ ] **Step 1: Read existing cli.py to identify the typer App + arg signatures.**

```bash
sed -n '1,100p' mimicanno/cli.py
```

- [ ] **Step 2: Add the new typer options.**

```python
@app.command()
def annotate(
    # ... existing args ...
    target_phase: int = typer.Option(1, "--target-phase", help="..."),
    vlm_model: str | None = typer.Option(
        None, "--vlm-model", help="HF model_id or '<id>@<sha>' or 'fixture://<path>'"
    ),
    vlm_keyframes: int = typer.Option(4, "--vlm-keyframes"),
    vlm_max_retries: int = typer.Option(3, "--vlm-max-retries"),
    offline: bool = typer.Option(False, "--offline"),
    # ...
) -> None:
    # ...
    if target_phase >= 2:
        if vlm_model is None:
            raise VLMModelRequired(target_phase=target_phase)
        # Pre-flight (§2.5)
        from mimicanno.preflight import resolve_vlm_model
        result = resolve_vlm_model(vlm_model, offline=offline)
        # Build VLMConfig
        from mimicanno.config import VLMConfig
        vlm_config: VLMConfig | None = VLMConfig(
            model_id=result.model_id,
            resolved_checkpoint=result.resolved_checkpoint,
            keyframes_per_segment=vlm_keyframes,
            max_retries=vlm_max_retries,
        )
        if vlm_config.keyframes_per_segment < 1:
            raise VLMConfigInvalid(reason="--vlm-keyframes must be >= 1")
    else:
        vlm_config = None

    # ModelConfig population (existing field) — projection of VLMConfig
    model_config = ModelConfig(
        vlm_model=(vlm_config.model_id if vlm_config else None),
        vlm_checkpoint=(vlm_config.resolved_checkpoint if vlm_config else None),
        sam3_model=None, sam3_checkpoint=None,
    )
    # ... rest of pipeline assembly ...
```

Plus: when `vlm_model` starts with `fixture://`, the labeler factory used in the pipeline MUST construct `FixtureVLMLabeler(<path>)` — extend `_make_labeler_factory` from Task 13 to inspect `vlm_config.model_id == "fixture"` and read the original path from a config field (add `_fixture_path: Path | None = None` to VLMConfig if needed, kept out of `to_dict` so it doesn't enter the hash).

> **Implementer note:** the fixture path needs to flow from CLI parse → `VLMConfig` → the pipeline → labeler factory. Two clean approaches:
> 1. Add `_fixture_path: Path | None = None` to `VLMConfig` (excluded from `to_dict`). Hash-clean.
> 2. Carry the path in a separate `RuntimeContext` object passed to the pipeline alongside `AnnotationConfig`.
>
> Pick (1) for simplicity unless the team has a `RuntimeContext` pattern already.

- [ ] **Step 3: Write CLI abort tests.**

```python
"""CLI Tier 1 abort paths (spec §4.2)."""
from __future__ import annotations

import json
import subprocess

import pytest


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["env", "-u", "PYTHONPATH", "-u", "ROS_DISTRO", "-u", "AMENT_PREFIX_PATH",
         ".venv/bin/python", "-m", "mimicanno.cli", "annotate", *args],
        capture_output=True, text=True,
    )


def test_target_phase_2_without_vlm_model_aborts() -> None:
    p = _run("--target-phase", "2",
            "--video", "/dev/null", "--parquet", "/dev/null",
            "--task", "x", "--robot", "aloha")
    assert p.returncode != 0
    err = p.stderr.strip().splitlines()[-1]
    obj = json.loads(err)
    assert obj["error_code"] == "vlm_model_required"


def test_offline_without_explicit_sha_aborts() -> None:
    p = _run("--target-phase", "2",
            "--vlm-model", "google/gemma-x", "--offline",
            "--video", "/dev/null", "--parquet", "/dev/null",
            "--task", "x", "--robot", "aloha")
    assert p.returncode != 0
    obj = json.loads(p.stderr.strip().splitlines()[-1])
    assert obj["error_code"] == "vlm_model_not_found"
```

- [ ] **Step 4: Run.**

```
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/pytest tests/integration/test_phase2_cli_abort.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit.**

```bash
git add mimicanno/cli.py tests/integration/test_phase2_cli_abort.py
git commit -m "feat(cli): --vlm-model / --vlm-keyframes / --offline + Tier 1 abort (§4.2)"
```

---

## Task 15: Phase 2 smoke (FixtureVLMLabeler end-to-end)

**Spec refs:** §5.3, parent §15.2 #12.

**Files:**
- Create: `tests/integration/test_phase2_smoke_fixture.py`
- Create: `tests/snapshots/phase2/manifest_phase2_smoke.json`
- Create: `tests/snapshots/phase2/annotation_phase2_smoke.json`

Run the CLI end-to-end against synthetic inputs + a fixture VLM, then assert that the run dir matches the spec's external surface.

- [ ] **Step 1: Write the integration test.**

```python
"""End-to-end Phase 2 smoke against FixtureVLMLabeler. Exit criterion #12."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def synth_episode(tmp_path: Path) -> dict:
    # Reuse Phase 1's existing synthesize.py helper.
    from tests.fixtures.synthesize import synthesize_aloha_episode
    return synthesize_aloha_episode(out_dir=tmp_path)


def test_phase2_smoke_with_fixture(synth_episode: dict, tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    fixt = Path("tests/fixtures/vlm/ok_first_try.json").resolve()
    p = subprocess.run([
        "env", "-u", "PYTHONPATH", "-u", "ROS_DISTRO", "-u", "AMENT_PREFIX_PATH",
        ".venv/bin/python", "-m", "mimicanno.cli", "annotate",
        "--video", str(synth_episode["video"]),
        "--parquet", str(synth_episode["parquet"]),
        "--task", "pick the red block and place in white bin",
        "--robot", "aloha",
        "--target-phase", "2",
        "--vlm-model", f"fixture://{fixt}",
        "--runs-root", str(runs),
        "--offline",
    ], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr

    # Find the run dir and inspect.
    [run_dir] = [d for d in runs.iterdir() if d.is_dir() and d.name.startswith("ep")]
    manifest = json.loads((run_dir / "manifest.json").read_text())
    annotation = json.loads((run_dir / "annotation.json").read_text())

    assert manifest["generator"]["pipeline_phase"] == 2
    assert manifest["model_versions"]["vlm"].startswith("fixture:")
    assert manifest["pipeline_status"]["degraded_from_phase"] is None
    assert manifest["pipeline_params"]["vlm"]["keyframes_per_segment"] == 4

    for seg in annotation["segments"]:
        assert seg["phase"] in (
            "idle", "approach_object", "align_gripper", "grasp_object",
            "lift_object", "move_to_target", "align_to_target",
            "place_object", "release_object", "retreat", "unknown",
        )
        assert seg["label_source"] == "vlm_robot_state_only"
        assert 0.0 <= seg["vlm_confidence"] <= 1.0
    assert annotation["notes"] is not None
    assert "/" in annotation["notes"]


def test_phase2_smoke_logs_vlm_attempt_events(synth_episode: dict, tmp_path: Path) -> None:
    """Exit criterion #12 — rejection retries observable in logs."""
    fixt = Path("tests/fixtures/vlm/retry_then_ok.json").resolve()
    p = subprocess.run([
        "env", "-u", "PYTHONPATH", "-u", "ROS_DISTRO", "-u", "AMENT_PREFIX_PATH",
        ".venv/bin/python", "-m", "mimicanno.cli", "annotate",
        "--video", str(synth_episode["video"]),
        "--parquet", str(synth_episode["parquet"]),
        "--task", "x", "--robot", "aloha",
        "--target-phase", "2",
        "--vlm-model", f"fixture://{fixt}",
        "--runs-root", str(tmp_path / "runs"),
        "--offline",
    ], capture_output=True, text=True)
    assert p.returncode == 0
    events = [json.loads(line) for line in p.stderr.strip().splitlines()
              if line.startswith("{") and '"event"' in line]
    rejected = [e for e in events
                if e.get("event") == "vlm_attempt" and e.get("status") == "rejected"]
    assert any(e.get("reject_reason") == "json_parse_error" for e in rejected)
    assert any(e.get("reject_reason") == "invalid_label" for e in rejected)
```

- [ ] **Step 2: Run.**

```
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/pytest tests/integration/test_phase2_smoke_fixture.py -v
```

Expected: 2 passed.

- [ ] **Step 3: Commit.**

```bash
git add tests/integration/test_phase2_smoke_fixture.py
git commit -m "test(integration): Phase 2 smoke + log observability (§5.3, parent §15.2 #12)"
```

---

## Task 16: Degrade-path integration tests

**Spec refs:** §4.3.

**Files:**
- Create: `tests/integration/test_phase2_degrade_paths.py`

- [ ] **Step 1: Write tests for vlm_init_failed and vlm_runtime_failed at CLI level.**

```python
"""Integration: run-level degrade paths produce a published run dir with
Phase 1 baseline + degrade flags (§4.3)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def synth_episode(tmp_path: Path) -> dict:
    from tests.fixtures.synthesize import synthesize_aloha_episode
    return synthesize_aloha_episode(out_dir=tmp_path)


def _run_phase2(synth_episode: dict, runs_root: Path, fixture_name: str):
    fixt = Path("tests/fixtures/vlm") / fixture_name
    return subprocess.run([
        "env", "-u", "PYTHONPATH", "-u", "ROS_DISTRO", "-u", "AMENT_PREFIX_PATH",
        ".venv/bin/python", "-m", "mimicanno.cli", "annotate",
        "--video", str(synth_episode["video"]),
        "--parquet", str(synth_episode["parquet"]),
        "--task", "x", "--robot", "aloha",
        "--target-phase", "2",
        "--vlm-model", f"fixture://{fixt.resolve()}",
        "--runs-root", str(runs_root),
        "--offline",
    ], capture_output=True, text=True)


def test_init_failure_publishes_phase1_baseline_with_degrade_flag(
    synth_episode: dict, tmp_path: Path,
) -> None:
    runs = tmp_path / "runs"
    p = _run_phase2(synth_episode, runs, "init_should_raise.json")
    assert p.returncode == 0  # degrade ≠ abort

    [run_dir] = [d for d in runs.iterdir() if d.is_dir()]
    manifest = json.loads((run_dir / "manifest.json").read_text())
    annotation = json.loads((run_dir / "annotation.json").read_text())

    assert manifest["generator"]["pipeline_phase"] == 2
    assert manifest["pipeline_status"]["degraded_from_phase"] == 2
    assert manifest["pipeline_status"]["degrade_reason"] == "vlm_init_failed"
    assert all(s["phase"] == "unlabeled" for s in annotation["segments"])
    assert all(s["label_source"] == "signals_only" for s in annotation["segments"])
    assert all(s["vlm_confidence"] is None for s in annotation["segments"])
    # Notes carries degrade_reason but NOT underlying_error.
    assert "vlm_init_failed" in annotation["notes"]
    assert "OSError" not in annotation["notes"]
    assert "RuntimeError" not in annotation["notes"]


def test_runtime_oom_threshold_triggers_degrade(
    synth_episode: dict, tmp_path: Path,
) -> None:
    runs = tmp_path / "runs"
    p = _run_phase2(synth_episode, runs, "runtime_oom.json")
    assert p.returncode == 0
    [run_dir] = [d for d in runs.iterdir() if d.is_dir()]
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["pipeline_status"]["degrade_reason"] == "vlm_runtime_failed"
```

- [ ] **Step 2: Run.**

Expected: 2 passed.

- [ ] **Step 3: Commit.**

```bash
git add tests/integration/test_phase2_degrade_paths.py
git commit -m "test(integration): vlm_init_failed and vlm_runtime_failed degrade paths (§4.3)"
```

---

## Task 17: Hash distinctness + idempotency

**Spec refs:** §1.3, §2.5, parent §4.4 step 2 + §6.5.

**Files:**
- Create: `tests/integration/test_phase2_hash_distinctness.py`
- Create: `tests/integration/test_phase2_idempotency.py`

- [ ] **Step 1: Write hash-distinctness test.**

```python
"""Different VLMConfig fields produce distinct run_hash (§1.3)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def synth_episode(tmp_path: Path) -> dict:
    from tests.fixtures.synthesize import synthesize_aloha_episode
    return synthesize_aloha_episode(out_dir=tmp_path)


def _run(**kwargs) -> subprocess.CompletedProcess:
    args = ["env", "-u", "PYTHONPATH", "-u", "ROS_DISTRO", "-u", "AMENT_PREFIX_PATH",
            ".venv/bin/python", "-m", "mimicanno.cli", "annotate"]
    for k, v in kwargs.items():
        args.append(f"--{k.replace('_', '-')}")
        args.append(str(v))
    args.append("--offline")
    return subprocess.run(args, capture_output=True, text=True)


def test_different_keyframes_produce_distinct_run_hashes(
    synth_episode: dict, tmp_path: Path,
) -> None:
    fixt = Path("tests/fixtures/vlm/ok_first_try.json").resolve()
    runs = tmp_path / "runs"
    common = dict(
        video=synth_episode["video"], parquet=synth_episode["parquet"],
        task="x", robot="aloha", target_phase=2,
        vlm_model=f"fixture://{fixt}", runs_root=runs,
    )
    p1 = _run(**common, vlm_keyframes=4)
    p2 = _run(**common, vlm_keyframes=6)
    assert p1.returncode == 0 and p2.returncode == 0
    dirs = sorted(d.name for d in runs.iterdir() if d.is_dir())
    assert len(dirs) == 2, f"expected 2 distinct runs, got {dirs}"
```

- [ ] **Step 2: Write idempotency test.**

```python
"""Re-running the same Phase 2 command short-circuits per parent §4.4 step 2."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def synth_episode(tmp_path: Path) -> dict:
    from tests.fixtures.synthesize import synthesize_aloha_episode
    return synthesize_aloha_episode(out_dir=tmp_path)


def test_same_command_is_idempotent(synth_episode: dict, tmp_path: Path) -> None:
    fixt = Path("tests/fixtures/vlm/ok_first_try.json").resolve()
    runs = tmp_path / "runs"
    cmd = ["env", "-u", "PYTHONPATH", "-u", "ROS_DISTRO", "-u", "AMENT_PREFIX_PATH",
           ".venv/bin/python", "-m", "mimicanno.cli", "annotate",
           "--video", str(synth_episode["video"]), "--parquet", str(synth_episode["parquet"]),
           "--task", "x", "--robot", "aloha", "--target-phase", "2",
           "--vlm-model", f"fixture://{fixt}", "--runs-root", str(runs),
           "--offline"]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    dirs1 = sorted(d.name for d in runs.iterdir() if d.is_dir())
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    dirs2 = sorted(d.name for d in runs.iterdir() if d.is_dir())
    assert dirs1 == dirs2, "second invocation must reuse the existing run dir"
```

- [ ] **Step 3: Run.**

```
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/pytest tests/integration/test_phase2_hash_distinctness.py tests/integration/test_phase2_idempotency.py -v
```

Expected: 2 passed.

- [ ] **Step 4: Commit.**

```bash
git add tests/integration/test_phase2_hash_distinctness.py tests/integration/test_phase2_idempotency.py
git commit -m "test(integration): Phase 2 hash distinctness + idempotency"
```

---

## Task 18: Real-VLM gated smoke + final cleanup

**Spec refs:** §5.4, parent §15.2 #12 + #13.

**Files:**
- Create: `tests/test_phase2_real_vlm.py`
- Modify: `pyproject.toml` (add `huggingface_hub` and ensure `transformers>=5.5` are in `[project.optional-dependencies].vlm` or main deps)
- Modify: `README.md` (add Phase 2 quick-start)

- [ ] **Step 1: Add the env-gated real-VLM smoke test.**

```python
"""Real-VLM smoke (Layer 3, env-gated). Loads the pinned default Gemma 4
multimodal IT model and runs labeling on one short pre-canned segment.

NOT a CI gate. Run manually:
  MIMICANNO_RUN_VLM_SMOKE=1 \
    env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
    .venv/bin/pytest tests/test_phase2_real_vlm.py -v
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("MIMICANNO_RUN_VLM_SMOKE") != "1",
    reason="real-VLM smoke is opt-in via MIMICANNO_RUN_VLM_SMOKE=1",
)


def test_real_vlm_labels_one_segment_to_a_valid_phase() -> None:
    # Skip if no GPU available — the model load fails otherwise on most setups.
    import torch
    if not torch.cuda.is_available():
        pytest.skip("CUDA not available; skipping real-VLM smoke")

    from mimicanno.config import VLMConfig
    from mimicanno.preflight import resolve_vlm_model
    from mimicanno.vlm_labeler import (
        DEFAULT_LOCAL_GEMMA_MODEL_ID, LocalGemmaVLMLabeler, VLMRequest,
    )
    import numpy as np

    pre = resolve_vlm_model(DEFAULT_LOCAL_GEMMA_MODEL_ID, offline=False)
    cfg = VLMConfig(
        model_id=pre.model_id, resolved_checkpoint=pre.resolved_checkpoint,
        device="cuda", dtype="bfloat16", max_retries=1, max_output_tokens=128,
    )
    lab = LocalGemmaVLMLabeler(cfg)
    req = VLMRequest(
        task_text="Pick the red block and place it in the white bin.",
        allowed_labels=[
            "idle", "approach_object", "align_gripper", "grasp_object",
            "lift_object", "move_to_target", "align_to_target",
            "place_object", "release_object", "retreat",
        ],
        label_version="manipulation.v1", robot_type="aloha",
        fps=30.0, episode_duration_sec=2.0, segment_index=1, segment_total=1,
        keyframes=[np.zeros((224, 224, 3), dtype=np.uint8)] * 4,
        keyframe_offsets_sec=[0.0, 0.5, 1.0, 1.5],
        robot_state_summary={
            "duration_sec": 2.0, "mean_eef_speed_mps": 0.05,
            "gripper_open_fraction": 0.5, "gripper_transitions": 0,
            "dwell_fraction": 0.3,
        },
    )
    resp = lab.label_segment(req, attempt=1, segment_id="s_000")
    assert resp["phase"] in set(req["allowed_labels"]) | {"unknown"}
    assert 0.0 <= resp["vlm_confidence"] <= 1.0
```

- [ ] **Step 2: Update pyproject.toml deps if needed.**

```bash
grep -E "(huggingface_hub|transformers)" pyproject.toml
```

If missing, add to `[project.dependencies]` or a `vlm` extra:

```toml
"huggingface_hub>=0.30",
"transformers>=5.5",
"Pillow>=10",
```

- [ ] **Step 3: Add Phase 2 section to README.md.**

Append:

````markdown
### Phase 2: VLM labeling

```bash
mimicanno annotate \
  --video <ep>.mp4 --parquet <ep>.parquet --task "..." --robot aloha \
  --target-phase 2 \
  --vlm-model google/gemma-3n-E2B-it@<sha> \
  --offline
```

`--offline` is recommended for reproducibility — pin the HF revision sha
explicitly via `<id>@<40-hex-sha>`. Without `--offline`, `mimicanno`
performs a HuggingFace API lookup at startup to resolve the latest sha.

For tests / CI, use the fixture URI scheme:

```bash
mimicanno annotate ... --vlm-model fixture://tests/fixtures/vlm/ok_first_try.json --offline
```
````

- [ ] **Step 4: Run the full unit + integration suite to confirm green.**

```
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/pytest tests/unit/ tests/integration/ -v
```

Expected: every Phase 1 + Phase 2 test green.

- [ ] **Step 5: Run lint + type check.**

```
ruff check mimicanno/ tests/
mypy --strict mimicanno/
```

Expected: clean (or only existing Phase 1 noise).

- [ ] **Step 6: Commit.**

```bash
git add tests/test_phase2_real_vlm.py pyproject.toml README.md
git commit -m "feat(phase2): real-VLM gated smoke + README + deps (§5.4)"
```

- [ ] **Step 7: Final tag commit.**

```bash
git commit --allow-empty -m "milestone: Phase 2 VLM labeling complete"
```

---

## Exit criteria mapping

| Spec ref | Met by tasks |
|---|---|
| §1.1 (single CLI entry, additive layer) | T13, T14 |
| §1.3 (no schema bumps; new fields populated) | T1, T13, T15 |
| §2.1 (VLMLabeler protocol + exception classes) | T5 |
| §2.2 (FixtureVLMLabeler, LocalGemmaVLMLabeler) | T8, T11, T12 |
| §2.3 (label_run orchestrator) | T9, T10 |
| §2.4 (VLMConfig, ClipFeatureConfig) | T1 |
| §2.5 (pre-flight + offline path) | T3 |
| §2.6 (manifest.pipeline_params.vlm shape) | T13, T15 |
| §2.7 (ClipFeatureExtractor + K_effective branch) | T4 |
| §3.1 (per-segment flow + transactional baseline) | T9, T10 |
| §3.2 (segment merge invariants) | T9 |
| §3.3 (prompt skeleton + retry amendment) | T7 |
| §3.4 (parse_and_validate) | T6 |
| §3.5 (notes aggregation) | T13 |
| §4.2 (Tier 1 abort) | T2, T14 |
| §4.3 (Tier 2 degrade) | T10, T16 |
| §4.4 (Tier 3 segment fallback) | T9 |
| §4.5 (Tier 4 per-attempt) | T6, T7 |
| §4.6 (structured stderr JSONL) | T13 |
| §5.2–§5.5 (test layers) | T2–T17 |
| §5.6 (snapshot policy) | T7, T15 |
| Parent §15.2 #12 (allowed labels + retries observable) | T15 |
| Parent §15.2 #13 (label_source = vlm_robot_state_only) | T9, T15 |
| Parent §6.4 (overall_confidence formula) | T9 |
| Parent §6.5 (atomic publish, scavenger) | inherited from Phase 1 — no changes |

---

## Risks / open notes

1. **Pinned `DEFAULT_LOCAL_GEMMA_MODEL_ID`** (Task 11): the placeholder `google/gemma-3n-E2B-it` may not be the latest. Implementer MUST verify via HF and update before merge. Hash-stable: changing this string in writing-plans-pin land creates new run_hashes for all subsequent runs.
2. **`vlm_keyframes` config-via-CLI flow** (Task 14): if your team uses a config-file pattern, prefer that over CLI flags so all VLMConfig fields can be tuned without command-line bloat. CLI flags retained for the high-traffic ones (`--vlm-model`, `--vlm-keyframes`, `--vlm-max-retries`, `--offline`).
3. **`LocalGemmaVLMLabeler.label_segment` does not currently propagate `last_reject_reason`** through the call (it's per-call stateless). The retry-prompt amendment in §3.3 is exercised, but only for `LabelerError` cases. If you need cross-attempt context, thread `last_reject_reason` through the `attempt` parameter (encode in a wrapper class) — left as YAGNI for v1.
4. **No real `vlm_unreachable` integration test.** The orchestrator first-call escalation is unit-tested with a mock labeler (T10); a CLI-level integration test would require either (a) pointing at a guaranteed-unreachable HF endpoint (flaky) or (b) creating a fixture scenario where the VERY first call raises `LabelerRuntimeError("model_unreachable")`. Option (b) is left as a Task 16 follow-up if `vlm_unreachable` ever becomes a high-traffic path.
5. **Fixture file path leakage into hash:** the `_fixture_path` field on `VLMConfig` (Task 14) MUST be excluded from `to_dict` so the hash is stable across users (different absolute paths shouldn't produce different run dirs). The `resolved_checkpoint = sha256(fixture content)` already covers content-distinctness; the path is just a runtime locator.

---

## Plan review handoff

After this plan is reviewed and approved, execution proceeds via either:

1. **Subagent-driven** (recommended): one fresh subagent per task, two-stage review between tasks. See `superpowers:subagent-driven-development`.
2. **Inline**: execute in this session via `superpowers:executing-plans`, batched with checkpoints.

Each task is self-contained: produces working tests + working code + a single commit. No task depends on the next being half-done.
