# MimicAnno Phase 4 — Temporal Smoothing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `mimicanno annotate` so that `--target-phase 4 [--smoother-config <yaml>] [--no-viterbi] ...` runs the existing Phase 3 inner pipeline (signals → boundaries → SAM3 → labeling) and then a deterministic smoother (same-label merge → min-duration absorb → optional Viterbi relabel with forbidden-transition penalty). Output is a self-contained run directory whose `annotation.json` carries `smoothing_ops` per segment and whose `manifest.json` carries `pipeline_phase=4` plus a `smoothing_summary` block. Phase 1/2/3 hashes and behavior remain byte-identical.

**Architecture:** Phase 4 is a purely additive, deterministic post-pass on the labeled-segment list emitted by Phase 3. A new `mimicanno/smoother.py` module owns three operators applied in fixed order; each operator is independently unit-tested. Configuration is hashed only when `target_phase >= 4` (gate inside `AnnotationConfig.to_dict`), so Phase 1/2/3 `config_hash` and `run_hash` are byte-identical pre/post-merge. Schema is additive: per-segment `smoothing_ops: list[str]` (defaults to `[]` for Phase 1–3 readers) + `Manifest.smoothing_summary: SmoothingSummary | None`. `annotation` schema bumps `0.1.0 → 0.2.0`; readers accept both. The Viterbi tie-break is normative-lexicographic on `(score_main, count_observed, -sum_rank_labelset, -sum_alpha_rank)` — no float-precision dependency.

**Tech Stack:** Python 3.11+ (existing venv), `pyyaml` (already a dep), `pytest`. Pure Python, no GPU, no new model. The smoother itself is < 300 LOC.

**Spec source of truth:** `docs/superpowers/specs/2026-04-29-mimicanno-phase4-smoothing-design.md`. Every section reference (`§3.4`, `§4.3`, etc.) below is **into that document**, not the parent design brushup. Parent spec references are explicitly marked `parent §...`. Phase 3 spec references are marked `phase3 §...`.

---

## File structure (locked in before tasks)

**New module + assets:**

```
mimicanno/
  smoother.py                 # NEW. ~250-300 LOC. Public:
                              #   SmoothingOp = Literal[
                              #     "merge_same_label", "merge_short", "viterbi_relabel"]
                              #   SmoothingSummary  - dataclass (counts; spec §4.3)
                              #   SmoothingResult   - dataclass (segments + summary + ops_log)
                              #   apply_smoothing(segments, *, config, labelset) -> SmoothingResult
                              # Internal: _merge_same_label / _merge_short / _viterbi_relabel
                              #           _recompute_confidence (helper used by all 3 ops)
configs/
  smoother/
    default.yaml              # NEW. Mirrors SmootherConfig defaults verbatim.
```

**Modified existing modules (Phase 4 additions only):**

```
mimicanno/
  config.py                   # ADD: SmootherConfig dataclass + load_smoother_config_yaml
                              #      + AnnotationConfig.smoother field (required iff target_phase>=4)
                              # EXTEND: AnnotationConfig.to_dict gates `smoother` key on target_phase>=4
                              # No changes to Phase 1-3 hashing payload (locked by regression test).
  schema.py                   # ADD: SubtaskSegment.smoothing_ops: list[str] (default [])
                              #      + Manifest.smoothing_summary: SmoothingSummary | None
                              #      + from_dict tolerates missing smoothing_ops (defaults [])
                              # EXTEND: SubtaskSegment.__post_init__ validates smoothing_ops
                              # EXTEND: SubtaskSegment.to_dict / Manifest.to_dict emit new fields.
  schema_versions.py          # BUMP: annotation 0.1.0 -> 0.2.0
                              # COMPAT_BLOCK still parses majors -> unchanged (MAJOR=0).
  errors.py                   # ADD: 3 new error codes (spec §7.1):
                              #   smoother_config_invalid
                              #   smoother_unknown_label_in_forbidden
                              #   smoother_segment_invariant_violation
  pipeline.py                 # ADD: annotate_episode_phase4 orchestrator branch (~80 LOC).
                              #      Re-uses annotate_episode_phase3 internals up through
                              #      labeled_segments, then runs apply_smoothing, then writes.
                              # No changes to Phase 1/2/3 code paths.
  cli.py                      # ADD: --smoother-config <path>, --no-viterbi flags.
                              # EXTEND: --target-phase accepts 4; dispatch to phase4 orchestrator.
                              # EXTEND: pre-flight order for target_phase==4 (spec §5).
  preflight.py                # ADD: smoother_config_resolution step (spec §5 pre-flight order).
```

**Tests (new):**

```
tests/unit/
  test_smoother_config.py             # SmootherConfig dataclass + YAML loader
  test_smoother_merge_same_label.py   # Op 1
  test_smoother_merge_short.py        # Op 2
  test_smoother_viterbi.py            # Op 3 + tie-break determinism
  test_smoother_apply.py              # apply_smoothing top-level + confidence regression
  test_phase4_schema.py               # SubtaskSegment.smoothing_ops + SmoothingSummary
  test_phase4_hash_gating.py          # SmootherConfig only enters config_hash for target_phase>=4

tests/integration/
  test_phase4_happy_path.py
  test_phase4_no_phase123_regression.py   # mirrors test_phase3_no_phase12_regression
  test_phase4_viterbi_disabled.py
  test_phase4_smoother_yaml_override.py
  test_phase4_per_segment_fallback.py
  test_phase4_cross_artifact.py
```

---

## Pre-task setup (do once before Task 1)

- [ ] **Step P.1: Confirm clean tree on `main` synced to `origin/main`.**

```bash
cd ~/MimicAnno
git status        # expect: clean, "Your branch is up to date with 'origin/main'"
git log -1        # expect HEAD == 79936dd or later spec-fix commit
```

- [ ] **Step P.2: Create the implementation worktree.**

This plan should be executed in a worktree per parent spec process. Use the superpowers:using-git-worktrees skill to create:

```bash
git worktree add -b phase4-smoothing-impl ~/MimicAnno-worktrees/phase4-smoothing
cd ~/MimicAnno-worktrees/phase4-smoothing
uv sync   # rebuild .venv from pyproject.toml + uv.lock
```

Run all subsequent tasks from `~/MimicAnno-worktrees/phase4-smoothing`.

- [ ] **Step P.3: Confirm baseline tests pass.**

```bash
env -u PYTHONPATH -u ROS_DISTRO -u AMENT_PREFIX_PATH \
  .venv/bin/python -m pytest tests/ \
  --ignore=tests/test_phase3_real_sam3_smoke.py \
  --ignore=tests/test_phase2_real_vlm.py
# Expected: 575 passed, 1 skipped (gated SAM3 smoke).
```

If anything fails, stop and investigate before adding Phase 4 code.

---

## Task 1: Phase 4 error codes

**Files:**
- Modify: `mimicanno/errors.py`
- Test: `tests/unit/test_errors_phase4.py` (new file)

Goal: Register the three Phase 4 error codes (spec §7.1) so later tasks can raise them by name.

- [ ] **Step 1.1: Inspect existing error-code registration.**

```bash
grep -n "ERROR_CODES\|class.*Error" mimicanno/errors.py | head -20
```

Expected: a registry / Literal type listing all codes (Phase 3 added e.g. `sam3_checkpoint_not_found`).

- [ ] **Step 1.2: Write failing tests (3 codes, registry membership).**

```python
# tests/unit/test_errors_phase4.py
from mimicanno.errors import ERROR_CODES   # adjust import to match what exists

def test_smoother_config_invalid_registered() -> None:
    assert "smoother_config_invalid" in ERROR_CODES

def test_smoother_unknown_label_in_forbidden_registered() -> None:
    assert "smoother_unknown_label_in_forbidden" in ERROR_CODES

def test_smoother_segment_invariant_violation_registered() -> None:
    assert "smoother_segment_invariant_violation" in ERROR_CODES
```

If `ERROR_CODES` doesn't exist as a public name, replace with whatever the existing test pattern is (see how Phase 3 tested `sam3_checkpoint_not_found`).

- [ ] **Step 1.3: Run tests to confirm they fail.**

```bash
.venv/bin/python -m pytest tests/unit/test_errors_phase4.py -v
# Expected: 3 FAIL with KeyError or AssertionError.
```

- [ ] **Step 1.4: Add the codes to `mimicanno/errors.py`.**

Append to whatever Literal/registry holds the existing codes:

```python
# Phase 4 (spec §7.1)
"smoother_config_invalid",
"smoother_unknown_label_in_forbidden",
"smoother_segment_invariant_violation",
```

- [ ] **Step 1.5: Run tests to confirm pass.**

```bash
.venv/bin/python -m pytest tests/unit/test_errors_phase4.py -v
# Expected: 3 PASS.
```

- [ ] **Step 1.6: Commit.**

```bash
git add mimicanno/errors.py tests/unit/test_errors_phase4.py
git commit -m "feat(errors): add Phase 4 error codes (spec §7.1)"
```

---

## Task 2: `SmootherConfig` dataclass + `to_dict`

**Files:**
- Modify: `mimicanno/config.py`
- Test: `tests/unit/test_smoother_config.py` (new file; YAML loader part comes in Task 3)

Goal: Land the `SmootherConfig` dataclass with defaults from spec §2 and a deterministic `to_dict()` for hashing.

- [ ] **Step 2.1: Write failing tests for the dataclass.**

```python
# tests/unit/test_smoother_config.py
from mimicanno.config import SmootherConfig


def test_smoother_config_defaults() -> None:
    cfg = SmootherConfig()
    assert cfg.min_segment_duration_sec == 0.30
    assert cfg.viterbi_enabled is True
    assert cfg.lambda_forbidden == 0.5
    assert cfg.forbidden_transitions == (
        ("grasp_object", "approach_object"),
        ("release_object", "grasp_object"),
        ("lift_object", "idle"),
    )


def test_smoother_config_to_dict_shape() -> None:
    cfg = SmootherConfig()
    d = cfg.to_dict()
    assert set(d.keys()) == {
        "min_segment_duration_sec",
        "forbidden_transitions",
        "viterbi_enabled",
        "lambda_forbidden",
    }
    # forbidden_transitions serializes as list-of-list (canonical JSON)
    assert d["forbidden_transitions"] == [
        ["grasp_object", "approach_object"],
        ["release_object", "grasp_object"],
        ["lift_object", "idle"],
    ]


def test_smoother_config_is_frozen() -> None:
    """Frozen dataclass — must not mutate after construction (hashable)."""
    import dataclasses
    cfg = SmootherConfig()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.viterbi_enabled = False  # type: ignore[misc]
```

Add `import pytest` at the top.

- [ ] **Step 2.2: Run tests to confirm fail.**

```bash
.venv/bin/python -m pytest tests/unit/test_smoother_config.py -v
# Expected: 3 FAIL with ImportError or AttributeError.
```

- [ ] **Step 2.3: Add `SmootherConfig` to `mimicanno/config.py`.**

```python
# mimicanno/config.py — add near other config dataclasses
@dataclass(frozen=True)
class SmootherConfig:
    """Phase 4 smoother parameters (spec §2).

    Hashed via ``to_dict`` only when ``target_phase >= 4`` (see
    ``AnnotationConfig.to_dict``). Phase 1-3 runs leave
    ``AnnotationConfig.smoother = None`` and contribute nothing to ``config_hash``.
    """

    min_segment_duration_sec: float = 0.30
    forbidden_transitions: tuple[tuple[str, str], ...] = (
        ("grasp_object", "approach_object"),
        ("release_object", "grasp_object"),
        ("lift_object", "idle"),
    )
    viterbi_enabled: bool = True
    lambda_forbidden: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_segment_duration_sec": self.min_segment_duration_sec,
            "forbidden_transitions": [list(p) for p in self.forbidden_transitions],
            "viterbi_enabled": self.viterbi_enabled,
            "lambda_forbidden": self.lambda_forbidden,
        }
```

Imports: `from dataclasses import dataclass`, `from typing import Any` (likely already present).

- [ ] **Step 2.4: Run tests to confirm pass.**

```bash
.venv/bin/python -m pytest tests/unit/test_smoother_config.py -v
# Expected: 3 PASS.
```

- [ ] **Step 2.5: Type-check.**

```bash
.venv/bin/python -m mypy --strict mimicanno/config.py
# Expected: clean.
```

- [ ] **Step 2.6: Commit.**

```bash
git add mimicanno/config.py tests/unit/test_smoother_config.py
git commit -m "feat(config): SmootherConfig dataclass (spec §2)"
```

---

## Task 3: `load_smoother_config_yaml` + validation

**Files:**
- Modify: `mimicanno/config.py`
- Test: `tests/unit/test_smoother_config.py` (extend)

Goal: YAML loader with the same UX as Phase 1's `load_boundary_config_yaml`. Validation per spec §2.1: unknown labels in forbidden_transitions raise `smoother_unknown_label_in_forbidden`; type/structural errors raise `smoother_config_invalid`.

- [ ] **Step 3.1: Inspect Phase 1's YAML loader for pattern.**

```bash
grep -n "load_boundary_config_yaml\|ConfigError" mimicanno/config.py | head -20
```

Phase 4's loader must follow the same `ConfigError(error_code=..., ...)` raise pattern for consistency.

- [ ] **Step 3.2: Write failing tests (extend `test_smoother_config.py`).**

```python
# Append to tests/unit/test_smoother_config.py
import tempfile
import textwrap
from pathlib import Path

import yaml

from mimicanno.config import load_smoother_config_yaml
from mimicanno.errors import ConfigError


def _write_yaml(content: str) -> Path:
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8")
    f.write(textwrap.dedent(content).strip() + "\n")
    f.flush()
    f.close()
    return Path(f.name)


def test_load_smoother_yaml_happy_path() -> None:
    p = _write_yaml("""
        min_segment_duration_sec: 0.5
        forbidden_transitions:
          - [grasp_object, approach_object]
        viterbi_enabled: false
        lambda_forbidden: 1.0
    """)
    allowed = ["approach_object", "grasp_object"]
    cfg = load_smoother_config_yaml(p, allowed_labels=allowed)
    assert cfg.min_segment_duration_sec == 0.5
    assert cfg.viterbi_enabled is False
    assert cfg.lambda_forbidden == 1.0
    assert cfg.forbidden_transitions == (("grasp_object", "approach_object"),)


def test_load_smoother_yaml_missing_fields_use_defaults() -> None:
    p = _write_yaml("min_segment_duration_sec: 0.5")
    cfg = load_smoother_config_yaml(p, allowed_labels=["grasp_object"])
    # Missing fields -> defaults
    assert cfg.viterbi_enabled is True
    assert cfg.lambda_forbidden == 0.5
    assert cfg.forbidden_transitions == SmootherConfig().forbidden_transitions


def test_load_smoother_yaml_unknown_label_in_forbidden_raises() -> None:
    p = _write_yaml("""
        forbidden_transitions:
          - [grasp_object, no_such_label]
    """)
    with pytest.raises(ConfigError) as exc_info:
        load_smoother_config_yaml(p, allowed_labels=["grasp_object"])
    assert exc_info.value.error_code == "smoother_unknown_label_in_forbidden"


def test_load_smoother_yaml_negative_lambda_raises() -> None:
    p = _write_yaml("lambda_forbidden: -0.1")
    with pytest.raises(ConfigError) as exc_info:
        load_smoother_config_yaml(p, allowed_labels=["grasp_object"])
    assert exc_info.value.error_code == "smoother_config_invalid"


def test_load_smoother_yaml_negative_min_duration_raises() -> None:
    p = _write_yaml("min_segment_duration_sec: -0.1")
    with pytest.raises(ConfigError) as exc_info:
        load_smoother_config_yaml(p, allowed_labels=["grasp_object"])
    assert exc_info.value.error_code == "smoother_config_invalid"


def test_load_smoother_yaml_malformed_transition_raises() -> None:
    """Each forbidden_transitions entry must be a length-2 sequence."""
    p = _write_yaml("""
        forbidden_transitions:
          - [grasp_object]
    """)
    with pytest.raises(ConfigError) as exc_info:
        load_smoother_config_yaml(p, allowed_labels=["grasp_object"])
    assert exc_info.value.error_code == "smoother_config_invalid"


def test_load_smoother_yaml_unparseable_raises() -> None:
    """A YAML file that doesn't parse at all raises smoother_config_invalid."""
    p = _write_yaml("[: not yaml")
    with pytest.raises(ConfigError) as exc_info:
        load_smoother_config_yaml(p, allowed_labels=["grasp_object"])
    assert exc_info.value.error_code == "smoother_config_invalid"


def test_load_smoother_yaml_reserved_labels_in_forbidden_ok() -> None:
    """`unknown` and `unlabeled` are reserved but valid forbidden-transition
    members per spec §2.1."""
    p = _write_yaml("""
        forbidden_transitions:
          - [grasp_object, unknown]
    """)
    cfg = load_smoother_config_yaml(p, allowed_labels=["grasp_object"])
    assert ("grasp_object", "unknown") in cfg.forbidden_transitions
```

- [ ] **Step 3.3: Run tests to confirm fail.**

```bash
.venv/bin/python -m pytest tests/unit/test_smoother_config.py -v
# Expected: 8 FAIL on import or attribute error.
```

- [ ] **Step 3.4: Implement `load_smoother_config_yaml`.**

Add to `mimicanno/config.py` (after `SmootherConfig`):

```python
def load_smoother_config_yaml(
    path: Path, *, allowed_labels: list[str]
) -> SmootherConfig:
    """Load and validate a SmootherConfig from a YAML file (spec §2.1).

    Raises ConfigError(error_code="smoother_config_invalid") for type/structural
    errors and ConfigError(error_code="smoother_unknown_label_in_forbidden")
    when forbidden_transitions reference labels not in allowed_labels and not
    in the reserved set {"unknown", "unlabeled"}.
    """
    import yaml as _yaml  # local import; pyyaml already a dep
    try:
        text = path.read_text(encoding="utf-8")
        data = _yaml.safe_load(text)
    except (OSError, _yaml.YAMLError) as e:
        raise ConfigError(
            error_code="smoother_config_invalid",
            message=f"failed to read or parse {path}: {e}",
        ) from e
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(
            error_code="smoother_config_invalid",
            message=f"{path}: top-level must be a mapping, got {type(data).__name__}",
        )

    defaults = SmootherConfig()

    def _get(key: str, expected_type: type, default: Any) -> Any:
        if key not in data:
            return default
        v = data[key]
        if not isinstance(v, expected_type):
            raise ConfigError(
                error_code="smoother_config_invalid",
                message=f"{path}: '{key}' must be {expected_type.__name__}, got {type(v).__name__}",
            )
        return v

    min_dur = _get("min_segment_duration_sec",
                   (int, float), defaults.min_segment_duration_sec)
    if min_dur < 0:
        raise ConfigError(
            error_code="smoother_config_invalid",
            message=f"{path}: 'min_segment_duration_sec' must be >= 0, got {min_dur}",
        )

    lam = _get("lambda_forbidden", (int, float), defaults.lambda_forbidden)
    if lam < 0:
        raise ConfigError(
            error_code="smoother_config_invalid",
            message=f"{path}: 'lambda_forbidden' must be >= 0, got {lam}",
        )

    viterbi = _get("viterbi_enabled", bool, defaults.viterbi_enabled)

    raw_ft = data.get("forbidden_transitions")
    if raw_ft is None:
        ft: tuple[tuple[str, str], ...] = defaults.forbidden_transitions
    else:
        if not isinstance(raw_ft, list):
            raise ConfigError(
                error_code="smoother_config_invalid",
                message=f"{path}: 'forbidden_transitions' must be a list of [str, str] pairs",
            )
        validated: list[tuple[str, str]] = []
        valid_labels = set(allowed_labels) | {"unknown", "unlabeled"}
        for entry in raw_ft:
            if not isinstance(entry, list) or len(entry) != 2:
                raise ConfigError(
                    error_code="smoother_config_invalid",
                    message=f"{path}: each forbidden_transitions entry must be a length-2 list, got {entry!r}",
                )
            a, b = entry
            if not isinstance(a, str) or not isinstance(b, str):
                raise ConfigError(
                    error_code="smoother_config_invalid",
                    message=f"{path}: forbidden_transitions entries must be [str, str], got {entry!r}",
                )
            for label in (a, b):
                if label not in valid_labels:
                    raise ConfigError(
                        error_code="smoother_unknown_label_in_forbidden",
                        message=(f"{path}: forbidden_transitions references unknown label {label!r}; "
                                 f"must be in allowed_labels or reserved {{'unknown', 'unlabeled'}}"),
                    )
            validated.append((a, b))
        ft = tuple(validated)

    return SmootherConfig(
        min_segment_duration_sec=float(min_dur),
        forbidden_transitions=ft,
        viterbi_enabled=bool(viterbi),
        lambda_forbidden=float(lam),
    )
```

If `ConfigError`'s constructor signature differs in this codebase, adapt — the existing Phase 1 / Phase 3 loaders are the reference.

- [ ] **Step 3.5: Run tests to confirm pass.**

```bash
.venv/bin/python -m pytest tests/unit/test_smoother_config.py -v
# Expected: 11 PASS.
```

- [ ] **Step 3.6: Type-check + lint.**

```bash
.venv/bin/python -m mypy --strict mimicanno/config.py
.venv/bin/python -m ruff check mimicanno/config.py
```

- [ ] **Step 3.7: Commit.**

```bash
git add mimicanno/config.py tests/unit/test_smoother_config.py
git commit -m "feat(config): load_smoother_config_yaml with validation (spec §2.1)"
```

---

## Task 4: `AnnotationConfig.smoother` + hash gating

**Files:**
- Modify: `mimicanno/config.py` (extend `AnnotationConfig`)
- Test: `tests/unit/test_phase4_hash_gating.py` (new file)

Goal: Wire `SmootherConfig` into `AnnotationConfig` and gate it out of the hash payload for `target_phase < 4`. **This task locks the byte-identity invariant** for Phase 1/2/3 hashes.

- [ ] **Step 4.1: Read existing `AnnotationConfig` to see the gating pattern.**

```bash
grep -n "AnnotationConfig\|target_phase" mimicanno/config.py | head -30
```

Phase 3 used the same pattern: `if self.target_phase >= 3 and self.tracking is not None: d["tracking"] = ...`. Phase 4 mirrors that.

- [ ] **Step 4.2: Write the failing hash-regression test.**

```python
# tests/unit/test_phase4_hash_gating.py
"""Phase 4 hash-gating regression (spec §6).

The presence of SmootherConfig must NOT alter config_hash for target_phase < 4.
"""
from __future__ import annotations

from mimicanno.config import (
    AnnotationConfig,
    BoundaryConfig,
    SmootherConfig,
    build_model_config,
    compute_config_hash,
)


def _phase1_cfg() -> AnnotationConfig:
    """A minimal Phase 1 AnnotationConfig fixture matching the existing Phase 3
    hash-gating test pattern (see tests/unit/test_phase3_hash_gating.py)."""
    # NOTE: adapt this constructor to whatever pattern the existing Phase 3
    # hash-gating test uses; the point is to build an AnnotationConfig with
    # target_phase=1 that includes deterministic boundary + model_config inputs.
    return AnnotationConfig(
        target_phase=1,
        boundary=BoundaryConfig(),
        model_config=build_model_config(target_phase=1),
        vlm=None,
        tracking=None,
        smoother=None,
    )


def test_phase1_hash_unaffected_by_smoother_field() -> None:
    cfg = _phase1_cfg()
    h1 = compute_config_hash(cfg)
    # to_dict for target_phase=1 must NOT include 'smoother' key
    payload = cfg.to_dict()
    assert "smoother" not in payload
    # And the hash must match a hand-built reference (lock to current value
    # post-smoother-field add). The reference is what compute_config_hash
    # returns BEFORE this change — capture it once and pin.
    # For TDD: first run, print h1, copy into PINNED_PHASE1_HASH, re-run.
    PINNED_PHASE1_HASH = "<RUN ONCE AND PIN>"
    assert h1 == PINNED_PHASE1_HASH, (
        f"Phase 1 config_hash drifted: {h1} != {PINNED_PHASE1_HASH}. "
        "Phase 4 code must NOT enter the Phase 1 hash payload."
    )


def test_phase4_hash_includes_smoother() -> None:
    base = _phase1_cfg()
    cfg = AnnotationConfig(
        target_phase=4,
        boundary=base.boundary,
        model_config=base.model_config,
        vlm=base.vlm,
        tracking=base.tracking,
        smoother=SmootherConfig(),
    )
    payload = cfg.to_dict()
    assert "smoother" in payload
    assert payload["smoother"] == SmootherConfig().to_dict()


def test_phase4_smoother_change_changes_hash() -> None:
    base = _phase1_cfg()
    a = AnnotationConfig(
        target_phase=4, boundary=base.boundary, model_config=base.model_config,
        vlm=base.vlm, tracking=base.tracking, smoother=SmootherConfig(),
    )
    b = AnnotationConfig(
        target_phase=4, boundary=base.boundary, model_config=base.model_config,
        vlm=base.vlm, tracking=base.tracking,
        smoother=SmootherConfig(viterbi_enabled=False),
    )
    assert compute_config_hash(a) != compute_config_hash(b)
```

`AnnotationConfig` may require a Phase 2/3 VLM/tracking config to be non-None at construction depending on the existing dataclass invariants. Inspect `__post_init__` and adapt the fixture (the test should use whatever shape lets `target_phase=1` instantiate without raising).

- [ ] **Step 4.3: Run hash-regression tests; capture the current Phase 1 hash.**

Before adding the `smoother` field, run:

```bash
.venv/bin/python -c "
from mimicanno.config import (AnnotationConfig, BoundaryConfig, build_model_config, compute_config_hash)
cfg = AnnotationConfig(
    target_phase=1, boundary=BoundaryConfig(),
    model_config=build_model_config(target_phase=1),
    vlm=None, tracking=None,  # NOTE: add smoother=None AFTER step 4.4
)
print(compute_config_hash(cfg))
"
```

Copy the printed hash into `PINNED_PHASE1_HASH` in the test. (This is the **pre-Phase-4-merge** Phase 1 hash. Phase 4 code MUST NOT change it.)

If the constructor fails because `smoother` doesn't exist yet, that's expected — capture the hash without the field and pin it; the field-add must not change it.

- [ ] **Step 4.4: Add `smoother` field and gating to `AnnotationConfig`.**

```python
# mimicanno/config.py
@dataclass(frozen=True)
class AnnotationConfig:
    target_phase: int
    boundary: BoundaryConfig
    model_config: ModelConfig
    vlm: VLMConfig | None = None
    tracking: TrackingConfig | None = None
    smoother: SmootherConfig | None = None   # NEW: required iff target_phase >= 4

    def __post_init__(self) -> None:
        # ... existing checks ...
        if self.target_phase >= 4 and self.smoother is None:
            raise ValueError("target_phase=4 requires AnnotationConfig.smoother != None")

    def to_dict(self) -> dict[str, Any]:
        d = {
            "boundary": self.boundary.to_dict(target_phase=self.target_phase),
            "target_phase": self.target_phase,
            "model_config": self.model_config.to_dict(),
        }
        if self.target_phase >= 2 and self.vlm is not None:
            d["vlm"] = self.vlm.to_dict()
        if self.target_phase >= 3 and self.tracking is not None:
            d["tracking"] = self.tracking.to_dict()
        if self.target_phase >= 4 and self.smoother is not None:
            d["smoother"] = self.smoother.to_dict()
        return d
```

- [ ] **Step 4.5: Run hash-regression tests.**

```bash
.venv/bin/python -m pytest tests/unit/test_phase4_hash_gating.py -v
# Expected: 3 PASS (after pinning the captured hash in step 4.3).
```

- [ ] **Step 4.6: Run the full existing test suite to confirm no regression.**

```bash
.venv/bin/python -m pytest tests/ \
  --ignore=tests/test_phase3_real_sam3_smoke.py \
  --ignore=tests/test_phase2_real_vlm.py
# Expected: 575 + new tests passed, 1 skipped.
# CRITICAL: any pre-existing test failure here means the gating is wrong —
# Phase 1/2/3 code paths must be byte-identical with the new field.
```

- [ ] **Step 4.7: Type-check.**

```bash
.venv/bin/python -m mypy --strict mimicanno/config.py
```

- [ ] **Step 4.8: Commit.**

```bash
git add mimicanno/config.py tests/unit/test_phase4_hash_gating.py
git commit -m "feat(config): AnnotationConfig.smoother + target_phase>=4 hash gating (spec §6)"
```

---

## Task 5: Schema additions — `SubtaskSegment.smoothing_ops` + `SmoothingSummary`

**Files:**
- Modify: `mimicanno/schema.py`
- Modify: `mimicanno/schema_versions.py`
- Test: `tests/unit/test_phase4_schema.py` (new)

Goal: Land the additive schema changes (per spec §4) before any code consumes them. Reader tolerates both `0.1.0` and `0.2.0`.

- [ ] **Step 5.1: Inspect existing `SubtaskSegment` and `Manifest` to see field-add patterns.**

```bash
grep -n "class SubtaskSegment\|class Manifest\|to_dict\|from_dict" mimicanno/schema.py | head -30
```

- [ ] **Step 5.2: Write failing schema tests.**

```python
# tests/unit/test_phase4_schema.py
"""Phase 4 schema additions (spec §4)."""
from __future__ import annotations

import pytest

from mimicanno.schema import (
    BoundaryRef,
    Manifest,
    SmoothingSummary,
    SubtaskSegment,
)


def _make_segment(**overrides: object) -> SubtaskSegment:
    """Build a minimal valid SubtaskSegment for tests; matches Phase 1-3 shape."""
    base = dict(
        segment_id="ep__seg0000",
        episode_id="ep",
        start_frame=0, end_frame=10,
        start_time=0.0, end_time=0.33,
        phase="grasp_object", verb="grasp", object="cube", target=None,
        failure_flags=[],
        label_source="vlm_with_object_state",
        object_state_unavailable=False,
        object_track_ids=[],
        label_version="v1",
        start_boundary=BoundaryRef(candidate_id="b0", frame=0, score=0.5),
        end_boundary=BoundaryRef(candidate_id="b1", frame=10, score=0.5),
        boundary_confidence=0.5,
        vlm_confidence=0.7,
        overall_confidence=0.59,
        evidence=None,
        reviewed=False,
        reviewer_id=None,
    )
    base.update(overrides)
    return SubtaskSegment(**base)


def test_subtask_segment_smoothing_ops_default_empty() -> None:
    seg = _make_segment(smoothing_ops=[])
    assert seg.smoothing_ops == []


def test_subtask_segment_smoothing_ops_unknown_op_rejected() -> None:
    with pytest.raises(ValueError, match="unknown smoothing op"):
        _make_segment(smoothing_ops=["not_an_op"])


def test_subtask_segment_smoothing_ops_none_rejected() -> None:
    with pytest.raises(TypeError, match="smoothing_ops must be list"):
        _make_segment(smoothing_ops=None)  # type: ignore[arg-type]


def test_subtask_segment_to_dict_emits_smoothing_ops() -> None:
    seg = _make_segment(smoothing_ops=["merge_same_label"])
    d = seg.to_dict()
    assert d["smoothing_ops"] == ["merge_same_label"]


def test_subtask_segment_from_dict_tolerates_missing_smoothing_ops() -> None:
    """Phase 1-3 annotation.json files have no smoothing_ops key.
    Reader must default to [] (spec §4.1)."""
    seg = _make_segment(smoothing_ops=[])
    d = seg.to_dict()
    d.pop("smoothing_ops")  # simulate older payload
    seg2 = SubtaskSegment.from_dict(d) if hasattr(SubtaskSegment, "from_dict") else None
    if seg2 is not None:  # only assert if from_dict exists
        assert seg2.smoothing_ops == []


def test_smoothing_summary_to_dict_shape() -> None:
    s = SmoothingSummary(
        initial_segment_count=5,
        final_segment_count=3,
        merge_same_label_rounds=1,
        merge_same_label_collapses=1,
        merge_short_absorbs=1,
        viterbi_relabels=0,
        viterbi_skipped=False,
    )
    d = s.to_dict()
    assert d == {
        "initial_segment_count": 5,
        "final_segment_count": 3,
        "merge_same_label_rounds": 1,
        "merge_same_label_collapses": 1,
        "merge_short_absorbs": 1,
        "viterbi_relabels": 0,
        "viterbi_skipped": False,
    }


def test_manifest_smoothing_summary_optional() -> None:
    """Phase 1-3 manifests have no smoothing_summary; reader defaults to None."""
    # Build a minimal Manifest — adapt to actual constructor.
    # Just verify the field can be None and serializes to None or is omitted.
    m = Manifest(
        # ... fill in required fields ...
        smoothing_summary=None,
    )
    assert m.smoothing_summary is None
```

The exact Manifest constructor fields will need to be filled in; copy from an existing Manifest test if one exists.

- [ ] **Step 5.3: Run schema tests to confirm fail.**

```bash
.venv/bin/python -m pytest tests/unit/test_phase4_schema.py -v
# Expected: ImportError on SmoothingSummary, AttributeError on smoothing_ops.
```

- [ ] **Step 5.4: Add `SmoothingSummary` dataclass and extend `SubtaskSegment` / `Manifest`.**

```python
# mimicanno/schema.py
SmoothingOpName = Literal["merge_same_label", "merge_short", "viterbi_relabel"]
_ALLOWED_SMOOTHING_OPS: frozenset[str] = frozenset({
    "merge_same_label", "merge_short", "viterbi_relabel",
})


@dataclass(slots=True)
class SmoothingSummary:
    """Phase 4 smoothing summary block (spec §4.3)."""
    initial_segment_count: int
    final_segment_count: int
    merge_same_label_rounds: int
    merge_same_label_collapses: int
    merge_short_absorbs: int
    viterbi_relabels: int
    viterbi_skipped: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_segment_count": self.initial_segment_count,
            "final_segment_count": self.final_segment_count,
            "merge_same_label_rounds": self.merge_same_label_rounds,
            "merge_same_label_collapses": self.merge_same_label_collapses,
            "merge_short_absorbs": self.merge_short_absorbs,
            "viterbi_relabels": self.viterbi_relabels,
            "viterbi_skipped": self.viterbi_skipped,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SmoothingSummary":
        return cls(
            initial_segment_count=int(d["initial_segment_count"]),
            final_segment_count=int(d["final_segment_count"]),
            merge_same_label_rounds=int(d["merge_same_label_rounds"]),
            merge_same_label_collapses=int(d["merge_same_label_collapses"]),
            merge_short_absorbs=int(d["merge_short_absorbs"]),
            viterbi_relabels=int(d["viterbi_relabels"]),
            viterbi_skipped=bool(d["viterbi_skipped"]),
        )
```

Extend `SubtaskSegment`:

```python
@dataclass(slots=True)
class SubtaskSegment:
    # ... existing 18 fields ...
    smoothing_ops: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # ... existing validation ...
        if self.smoothing_ops is None:
            raise TypeError("smoothing_ops must be list[str], not None")
        for op in self.smoothing_ops:
            if op not in _ALLOWED_SMOOTHING_OPS:
                raise ValueError(f"unknown smoothing op: {op!r}")

    def to_dict(self) -> dict[str, Any]:
        d = {
            # ... existing keys ...
            "smoothing_ops": list(self.smoothing_ops),
        }
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SubtaskSegment":
        # If from_dict already exists, add smoothing_ops with default [].
        # If not, this whole helper may need to be added — check what
        # tests/unit/test_phase4_schema.py needs.
        return cls(
            # ... existing kwargs ...
            smoothing_ops=list(d.get("smoothing_ops", [])),
        )
```

Extend `Manifest`:

```python
@dataclass(slots=True)
class Manifest:
    # ... existing fields ...
    smoothing_summary: SmoothingSummary | None = None

    def to_dict(self) -> dict[str, Any]:
        d = {
            # ... existing keys ...
        }
        if self.smoothing_summary is not None:
            d["smoothing_summary"] = self.smoothing_summary.to_dict()
        return d

    # If Manifest has from_dict, extend it:
    # smoothing_summary=(SmoothingSummary.from_dict(d["smoothing_summary"])
    #                    if "smoothing_summary" in d else None)
```

Field ordering in `to_dict` matters for canonical JSON if anyone hashes it; place `smoothing_ops` and `smoothing_summary` consistent with how the existing field order is established.

- [ ] **Step 5.5: Bump annotation schema version.**

```python
# mimicanno/schema_versions.py
ARTIFACT_SCHEMA_VERSIONS: dict[str, str] = {
    "manifest": "0.1.0",
    "annotation": "0.2.0",   # bumped from 0.1.0 (spec §4.4)
    "boundaries": "0.1.0",
    "signals": "0.1.0",
}
```

`COMPAT_BLOCK` is derived via `parse_major` so the bump from 0.1.0 → 0.2.0 yields the same `MAJOR=0` and `COMPAT_BLOCK` is unchanged. No further changes here.

- [ ] **Step 5.6: Run schema tests to confirm pass.**

```bash
.venv/bin/python -m pytest tests/unit/test_phase4_schema.py -v
# Expected: 7 PASS.
```

- [ ] **Step 5.7: Run the full existing test suite.**

```bash
.venv/bin/python -m pytest tests/ \
  --ignore=tests/test_phase3_real_sam3_smoke.py \
  --ignore=tests/test_phase2_real_vlm.py
# Expected: all green. If any annotation-roundtrip test fails because the new
# field isn't tolerated, fix the from_dict default-to-[] path.
```

- [ ] **Step 5.8: Type-check + lint.**

```bash
.venv/bin/python -m mypy --strict mimicanno/schema.py mimicanno/schema_versions.py
.venv/bin/python -m ruff check mimicanno/schema.py mimicanno/schema_versions.py
```

- [ ] **Step 5.9: Commit.**

```bash
git add mimicanno/schema.py mimicanno/schema_versions.py tests/unit/test_phase4_schema.py
git commit -m "feat(schema): SmoothingSummary + SubtaskSegment.smoothing_ops; bump annotation 0.2.0 (spec §4)"
```

---

## Task 6: `smoother.py` scaffolding + `_recompute_confidence` helper

**Files:**
- Create: `mimicanno/smoother.py`
- Test: `tests/unit/test_smoother_apply.py` (new — only the helper test for now)

Goal: Create the module skeleton with `apply_smoothing` signature, `SmoothingResult` dataclass, and the `_recompute_confidence` helper used by all 3 ops. No op logic yet — just the scaffolding.

- [ ] **Step 6.1: Write a focused test for `_recompute_confidence`.**

```python
# tests/unit/test_smoother_apply.py
"""apply_smoothing top-level + confidence helper (spec §3.5)."""
from __future__ import annotations

import math

import pytest

from mimicanno.schema import BoundaryRef, SubtaskSegment
from mimicanno.smoother import _recompute_confidence


def _seg(*, phase: str = "grasp_object", vlm_confidence: float | None = 0.8,
         start_score: float = 0.6, end_score: float = 0.4,
         **rest: object) -> SubtaskSegment:
    return SubtaskSegment(
        segment_id="ep__seg0000", episode_id="ep",
        start_frame=0, end_frame=10, start_time=0.0, end_time=0.33,
        phase=phase, verb=None, object=None, target=None,
        failure_flags=[], label_source="vlm_with_object_state",
        object_state_unavailable=False, object_track_ids=[],
        label_version="v1",
        start_boundary=BoundaryRef(candidate_id="b0", frame=0, score=start_score),
        end_boundary=BoundaryRef(candidate_id="b1", frame=10, score=end_score),
        boundary_confidence=0.0, vlm_confidence=vlm_confidence,
        overall_confidence=0.0, evidence=None, reviewed=False, reviewer_id=None,
        smoothing_ops=[], **rest,  # type: ignore[arg-type]
    )


def test_recompute_confidence_sets_boundary_to_min_of_edges() -> None:
    seg = _seg(start_score=0.6, end_score=0.4)
    out = _recompute_confidence(seg)
    assert out.boundary_confidence == 0.4   # min(0.6, 0.4)


def test_recompute_confidence_overall_geometric_mean() -> None:
    seg = _seg(start_score=0.6, end_score=0.6, vlm_confidence=0.4)
    out = _recompute_confidence(seg)
    assert out.boundary_confidence == 0.6
    assert math.isclose(out.overall_confidence, math.sqrt(0.6 * 0.4))


def test_recompute_confidence_reserved_phases_zero() -> None:
    for phase in ("unlabeled", "unknown"):
        seg = _seg(phase=phase, start_score=0.9, end_score=0.9, vlm_confidence=0.9)
        out = _recompute_confidence(seg)
        assert out.overall_confidence == 0.0


def test_recompute_confidence_none_vlm_uses_boundary() -> None:
    seg = _seg(start_score=0.5, end_score=0.4, vlm_confidence=None)
    out = _recompute_confidence(seg)
    assert out.overall_confidence == 0.4   # boundary_confidence
```

- [ ] **Step 6.2: Run tests; expect ImportError.**

```bash
.venv/bin/python -m pytest tests/unit/test_smoother_apply.py -v
# Expected: ImportError on mimicanno.smoother._recompute_confidence.
```

- [ ] **Step 6.3: Create `mimicanno/smoother.py` with scaffolding + helper.**

```python
"""Phase 4 temporal smoothing (spec §3).

Three deterministic operators applied in fixed order:
1. _merge_same_label  — collapse adjacent same-phase segments
2. _merge_short       — absorb short segments into highest-confidence neighbor
3. _viterbi_relabel   — DP relabel with forbidden-transition penalty (optional)

Public API:
    apply_smoothing(segments, *, config, labelset) -> SmoothingResult
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Literal

from mimicanno.config import SmootherConfig
from mimicanno.schema import (
    SmoothingSummary,
    SubtaskSegment,
)

SmoothingOp = Literal["merge_same_label", "merge_short", "viterbi_relabel"]
_RESERVED_PHASES: frozenset[str] = frozenset({"unlabeled", "unknown"})


@dataclass(slots=True)
class SmoothingResult:
    """Returned by apply_smoothing (spec §1.2)."""
    segments: list[SubtaskSegment]
    summary: SmoothingSummary
    ops_log: list[tuple[SmoothingOp, list[str]]] = field(default_factory=list)
    """Ordered log of ops applied; each entry is (op_name, list_of_segment_ids_affected)."""


def _recompute_confidence(seg: SubtaskSegment) -> SubtaskSegment:
    """Re-derive boundary_confidence and overall_confidence per spec §3.5.

    boundary_confidence = min(start_boundary.score, end_boundary.score)   [parent §6.1]
    overall_confidence  = 0.0                              if phase ∈ {unlabeled, unknown}
                        = boundary_confidence              if vlm_confidence is None
                        = sqrt(boundary * vlm)             otherwise        [parent §6.4]
    """
    bc = min(seg.start_boundary.score, seg.end_boundary.score)
    if seg.phase in _RESERVED_PHASES:
        oc = 0.0
    elif seg.vlm_confidence is None:
        oc = bc
    else:
        oc = math.sqrt(bc * seg.vlm_confidence)
    return replace(seg, boundary_confidence=bc, overall_confidence=oc)


def apply_smoothing(
    segments: list[SubtaskSegment],
    *,
    config: SmootherConfig,
    labelset: list[str],
) -> SmoothingResult:
    """Apply Phase 4 smoothing (spec §3). Stub — Tasks 7-10 fill in the ops."""
    raise NotImplementedError("Tasks 7-10 implement the operators.")
```

- [ ] **Step 6.4: Run helper tests to confirm pass.**

```bash
.venv/bin/python -m pytest tests/unit/test_smoother_apply.py::test_recompute_confidence_sets_boundary_to_min_of_edges \
  tests/unit/test_smoother_apply.py::test_recompute_confidence_overall_geometric_mean \
  tests/unit/test_smoother_apply.py::test_recompute_confidence_reserved_phases_zero \
  tests/unit/test_smoother_apply.py::test_recompute_confidence_none_vlm_uses_boundary -v
# Expected: 4 PASS.
```

- [ ] **Step 6.5: Type-check + lint.**

```bash
.venv/bin/python -m mypy --strict mimicanno/smoother.py
.venv/bin/python -m ruff check mimicanno/smoother.py
```

- [ ] **Step 6.6: Commit.**

```bash
git add mimicanno/smoother.py tests/unit/test_smoother_apply.py
git commit -m "feat(smoother): module scaffolding + _recompute_confidence helper (spec §3.5)"
```

---

## Task 7: Op 1 — `_merge_same_label`

**Files:**
- Modify: `mimicanno/smoother.py`
- Test: `tests/unit/test_smoother_merge_same_label.py` (new)

Goal: Implement the same-label merge operator per spec §3.2. Iterates left-to-right, merging adjacent segments with identical `phase`, repeating rounds until no merge happens.

- [ ] **Step 7.1: Write failing tests for the operator.**

```python
# tests/unit/test_smoother_merge_same_label.py
"""Op 1: same-label merge (spec §3.2)."""
from __future__ import annotations

import math

import pytest

from mimicanno.schema import BoundaryRef, SubtaskSegment
from mimicanno.smoother import _merge_same_label


def _seg(*, idx: int, phase: str, start_frame: int, end_frame: int,
         vlm: float | None = 0.7, start_score: float = 0.5, end_score: float = 0.5,
         smoothing_ops: list[str] | None = None,
         failure_flags: list[str] | None = None,
         object_track_ids: list[str] | None = None,
         label_source: str = "vlm_with_object_state",
         ) -> SubtaskSegment:
    return SubtaskSegment(
        segment_id=f"ep__seg{idx:04d}", episode_id="ep",
        start_frame=start_frame, end_frame=end_frame,
        start_time=start_frame / 30, end_time=end_frame / 30,
        phase=phase, verb=None, object=None, target=None,
        failure_flags=list(failure_flags or []),
        label_source=label_source,  # type: ignore[arg-type]
        object_state_unavailable=False,
        object_track_ids=list(object_track_ids or []),
        label_version="v1",
        start_boundary=BoundaryRef(candidate_id=f"b{idx}s", frame=start_frame, score=start_score),
        end_boundary=BoundaryRef(candidate_id=f"b{idx}e", frame=end_frame, score=end_score),
        boundary_confidence=min(start_score, end_score),
        vlm_confidence=vlm,
        overall_confidence=math.sqrt(min(start_score, end_score) * vlm) if vlm is not None else min(start_score, end_score),
        evidence=None, reviewed=False, reviewer_id=None,
        smoothing_ops=list(smoothing_ops or []),
    )


def test_merge_same_label_two_adjacent_same_collapse() -> None:
    a = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=10)
    b = _seg(idx=1, phase="grasp_object", start_frame=10, end_frame=20)
    out, rounds, collapses = _merge_same_label([a, b])
    assert len(out) == 1
    assert out[0].start_frame == 0 and out[0].end_frame == 20
    assert out[0].phase == "grasp_object"
    assert out[0].smoothing_ops == ["merge_same_label"]
    assert rounds == 1
    assert collapses == 1


def test_merge_same_label_non_adjacent_same_no_merge() -> None:
    a = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=10)
    b = _seg(idx=1, phase="approach_object", start_frame=10, end_frame=20)
    c = _seg(idx=2, phase="grasp_object", start_frame=20, end_frame=30)
    out, _, collapses = _merge_same_label([a, b, c])
    assert len(out) == 3
    assert collapses == 0


def test_merge_same_label_three_in_a_row_collapse_in_one_round() -> None:
    a = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=10)
    b = _seg(idx=1, phase="grasp_object", start_frame=10, end_frame=20)
    c = _seg(idx=2, phase="grasp_object", start_frame=20, end_frame=30)
    out, rounds, collapses = _merge_same_label([a, b, c])
    assert len(out) == 1
    assert out[0].start_frame == 0 and out[0].end_frame == 30
    # Two left-to-right collapses in round 1 (a+b → ab; ab+c → abc)
    assert collapses == 2


def test_merge_same_label_higher_confidence_phase_wins_when_phases_differ_in_input() -> None:
    """If somehow two adjacent segments share phase but differ in label_source/verb,
    the higher-overall-confidence side wins (spec §3.2 phase/verb/object/target rule)."""
    # Same phase, but different label_source. Higher overall_confidence on the right.
    a = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=10,
             vlm=0.4, label_source="vlm_robot_state_only")
    b = _seg(idx=1, phase="grasp_object", start_frame=10, end_frame=20,
             vlm=0.9, label_source="vlm_with_object_state")
    out, _, _ = _merge_same_label([a, b])
    assert len(out) == 1
    assert out[0].label_source == "vlm_with_object_state"  # b had higher overall


def test_merge_same_label_failure_flags_set_union() -> None:
    a = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=10,
             failure_flags=["failed_grasp"])
    b = _seg(idx=1, phase="grasp_object", start_frame=10, end_frame=20,
             failure_flags=["lost_object"])
    out, _, _ = _merge_same_label([a, b])
    assert out[0].failure_flags == ["failed_grasp", "lost_object"]


def test_merge_same_label_object_track_ids_set_union() -> None:
    a = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=10,
             object_track_ids=["obj_red_block"])
    b = _seg(idx=1, phase="grasp_object", start_frame=10, end_frame=20,
             object_track_ids=["obj_red_block", "obj_bin"])
    out, _, _ = _merge_same_label([a, b])
    assert out[0].object_track_ids == ["obj_bin", "obj_red_block"]


def test_merge_same_label_boundary_confidence_derived_not_max() -> None:
    """Spec §3.2: merged boundary_confidence = min of the surviving outer edges,
    NOT max of input boundary_confidences."""
    a = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=10,
             start_score=0.9, end_score=0.9, vlm=0.5)
    b = _seg(idx=1, phase="grasp_object", start_frame=10, end_frame=20,
             start_score=0.9, end_score=0.3, vlm=0.5)
    out, _, _ = _merge_same_label([a, b])
    # merged.start = a.start (0.9), merged.end = b.end (0.3). min = 0.3
    assert out[0].boundary_confidence == 0.3
    assert math.isclose(out[0].overall_confidence, math.sqrt(0.3 * 0.5))


def test_merge_same_label_reviewed_reset() -> None:
    a = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=10)
    a = type(a)(**{**a.__dict__, "reviewed": True, "reviewer_id": "alice"})
    b = _seg(idx=1, phase="grasp_object", start_frame=10, end_frame=20)
    out, _, _ = _merge_same_label([a, b])
    assert out[0].reviewed is False
    assert out[0].reviewer_id is None


def test_merge_same_label_smoothing_ops_lineage_from_both() -> None:
    a = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=10,
             smoothing_ops=["merge_short"])
    b = _seg(idx=1, phase="grasp_object", start_frame=10, end_frame=20,
             smoothing_ops=["viterbi_relabel"])
    out, _, _ = _merge_same_label([a, b])
    # Spec §3.2: dedup(a + b + ["merge_same_label"]); preserves order
    assert out[0].smoothing_ops == ["merge_short", "viterbi_relabel", "merge_same_label"]


def test_merge_same_label_smoothing_ops_dedup_consecutive() -> None:
    a = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=10,
             smoothing_ops=["merge_same_label"])
    b = _seg(idx=1, phase="grasp_object", start_frame=10, end_frame=20,
             smoothing_ops=["merge_same_label"])
    out, _, _ = _merge_same_label([a, b])
    # Two "merge_same_label" entries from inputs + one new = three; dedup
    # consecutive duplicates leaves one.
    assert out[0].smoothing_ops == ["merge_same_label"]


def test_merge_same_label_segment_id_regenerated() -> None:
    a = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=10)
    b = _seg(idx=1, phase="approach_object", start_frame=10, end_frame=20)
    c = _seg(idx=2, phase="approach_object", start_frame=20, end_frame=30)
    out, _, _ = _merge_same_label([a, b, c])
    # b + c collapse; ids regenerated 0001-style
    assert [s.segment_id for s in out] == ["ep__seg0000", "ep__seg0001"]


def test_merge_same_label_empty_input() -> None:
    out, rounds, collapses = _merge_same_label([])
    assert out == []
    assert rounds == 0
    assert collapses == 0


def test_merge_same_label_single_segment() -> None:
    a = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=10)
    out, rounds, collapses = _merge_same_label([a])
    assert len(out) == 1
    assert out[0].smoothing_ops == []   # no merge happened, no op recorded
    assert rounds == 0
    assert collapses == 0
```

- [ ] **Step 7.2: Run tests; expect ImportError on `_merge_same_label`.**

```bash
.venv/bin/python -m pytest tests/unit/test_smoother_merge_same_label.py -v
# Expected: 13 FAIL on import.
```

- [ ] **Step 7.3: Implement `_merge_same_label` in `mimicanno/smoother.py`.**

```python
def _dedup_consecutive(ops: list[str]) -> list[str]:
    out: list[str] = []
    for op in ops:
        if not out or out[-1] != op:
            out.append(op)
    return out


def _merge_pair_same_label(left: SubtaskSegment, right: SubtaskSegment) -> SubtaskSegment:
    """Merge two adjacent same-phase segments per spec §3.2 field-merge rules."""
    higher = left if left.overall_confidence >= right.overall_confidence else right
    new_vlm: float | None
    if left.vlm_confidence is None and right.vlm_confidence is None:
        new_vlm = None
    elif left.vlm_confidence is None:
        new_vlm = right.vlm_confidence
    elif right.vlm_confidence is None:
        new_vlm = left.vlm_confidence
    else:
        # Duration-weighted mean
        d_l = left.end_time - left.start_time
        d_r = right.end_time - right.start_time
        total = d_l + d_r
        new_vlm = (left.vlm_confidence * d_l + right.vlm_confidence * d_r) / total if total > 0 else (left.vlm_confidence + right.vlm_confidence) / 2

    if left.label_version != right.label_version:
        raise AssertionError(
            f"label_version differs across run: {left.label_version} vs {right.label_version}"
        )

    merged = SubtaskSegment(
        segment_id="",  # regenerated by caller after the round
        episode_id=left.episode_id,
        start_frame=left.start_frame, end_frame=right.end_frame,
        start_time=left.start_time, end_time=right.end_time,
        phase=higher.phase, verb=higher.verb, object=higher.object, target=higher.target,
        failure_flags=sorted(set(left.failure_flags) | set(right.failure_flags)),
        label_source=higher.label_source,
        object_state_unavailable=left.object_state_unavailable or right.object_state_unavailable,
        object_track_ids=sorted(set(left.object_track_ids) | set(right.object_track_ids)),
        label_version=left.label_version,
        start_boundary=left.start_boundary,
        end_boundary=right.end_boundary,
        boundary_confidence=0.0,    # filled by _recompute_confidence
        vlm_confidence=new_vlm,
        overall_confidence=0.0,     # filled by _recompute_confidence
        evidence=higher.evidence,
        reviewed=False,
        reviewer_id=None,
        smoothing_ops=_dedup_consecutive(
            list(left.smoothing_ops) + list(right.smoothing_ops) + ["merge_same_label"]
        ),
    )
    return _recompute_confidence(merged)


def _renumber_segment_ids(segments: list[SubtaskSegment]) -> list[SubtaskSegment]:
    """Spec §4.2: segment_id = f'{episode_id}__seg{idx:04d}'."""
    return [
        replace(s, segment_id=f"{s.episode_id}__seg{idx:04d}")
        for idx, s in enumerate(segments)
    ]


def _merge_same_label(
    segments: list[SubtaskSegment],
) -> tuple[list[SubtaskSegment], int, int]:
    """Op 1 (spec §3.2). Returns (segments, rounds, collapses)."""
    if len(segments) <= 1:
        return list(segments), 0, 0
    rounds = 0
    collapses = 0
    current = list(segments)
    while True:
        rounds += 1
        out: list[SubtaskSegment] = []
        i = 0
        round_collapses = 0
        while i < len(current):
            if i + 1 < len(current) and current[i].phase == current[i + 1].phase:
                out.append(_merge_pair_same_label(current[i], current[i + 1]))
                round_collapses += 1
                i += 2
            else:
                out.append(current[i])
                i += 1
        collapses += round_collapses
        if round_collapses == 0:
            # Round did nothing — terminate
            break
        current = out
    # Renumber once at end (cheaper than per-round)
    return _renumber_segment_ids(current), rounds, collapses
```

Note: `rounds` includes the final no-op round per the test fixture's expectations — verify this matches the test expectations (`test_merge_same_label_two_adjacent_same_collapse` expects `rounds == 1` after one merge round; the no-op terminator doesn't count). Adjust the increment placement if needed: the test expects `rounds == 1` for "one merge happened, then terminate." Move `rounds += 1` to *after* the `if round_collapses == 0` check fires false, i.e. only count rounds that did work:

```python
    while True:
        out, round_collapses = _do_one_round(current)
        if round_collapses == 0:
            break
        rounds += 1
        collapses += round_collapses
        current = out
    return _renumber_segment_ids(current), rounds, collapses
```

(Refactor the inner loop into `_do_one_round` for clarity.)

- [ ] **Step 7.4: Run tests; iterate until all pass.**

```bash
.venv/bin/python -m pytest tests/unit/test_smoother_merge_same_label.py -v
# Expected: 13 PASS.
```

- [ ] **Step 7.5: Type-check + lint.**

```bash
.venv/bin/python -m mypy --strict mimicanno/smoother.py
.venv/bin/python -m ruff check mimicanno/smoother.py
```

- [ ] **Step 7.6: Commit.**

```bash
git add mimicanno/smoother.py tests/unit/test_smoother_merge_same_label.py
git commit -m "feat(smoother): Op 1 same-label merge (spec §3.2)"
```

---

## Task 8: Op 2 — `_merge_short` (min-duration absorb)

**Files:**
- Modify: `mimicanno/smoother.py`
- Test: `tests/unit/test_smoother_merge_short.py` (new)

Goal: Implement the min-duration absorb pass per spec §3.3. Repeats until no segment is below threshold; restart-at-i-1 after each merge.

- [ ] **Step 8.1: Write failing tests.**

```python
# tests/unit/test_smoother_merge_short.py
"""Op 2: min-duration absorb (spec §3.3)."""
from __future__ import annotations

import math

import pytest

from mimicanno.config import SmootherConfig
from mimicanno.schema import BoundaryRef, SubtaskSegment
from mimicanno.smoother import _merge_short


def _seg(*, idx: int, phase: str, start_frame: int, end_frame: int,
         fps: int = 30, vlm: float | None = 0.7,
         start_score: float = 0.5, end_score: float = 0.5,
         smoothing_ops: list[str] | None = None,
         label_source: str = "vlm_with_object_state",
         ) -> SubtaskSegment:
    bc = min(start_score, end_score)
    if vlm is None:
        oc = bc
    elif phase in {"unlabeled", "unknown"}:
        oc = 0.0
    else:
        oc = math.sqrt(bc * vlm)
    return SubtaskSegment(
        segment_id=f"ep__seg{idx:04d}", episode_id="ep",
        start_frame=start_frame, end_frame=end_frame,
        start_time=start_frame / fps, end_time=end_frame / fps,
        phase=phase, verb=None, object=None, target=None,
        failure_flags=[],
        label_source=label_source,  # type: ignore[arg-type]
        object_state_unavailable=False, object_track_ids=[],
        label_version="v1",
        start_boundary=BoundaryRef(candidate_id=f"b{idx}s", frame=start_frame, score=start_score),
        end_boundary=BoundaryRef(candidate_id=f"b{idx}e", frame=end_frame, score=end_score),
        boundary_confidence=bc, vlm_confidence=vlm, overall_confidence=oc,
        evidence=None, reviewed=False, reviewer_id=None,
        smoothing_ops=list(smoothing_ops or []),
    )


def test_merge_short_below_threshold_absorbs_into_higher_neighbor() -> None:
    """A 2-frame segment between two 30-frame segments (threshold 0.30s @ 30fps = 9 frames):
    short segment absorbed into the higher-confidence neighbor; neighbor's phase wins."""
    long_l = _seg(idx=0, phase="approach_object", start_frame=0, end_frame=30, vlm=0.4)
    short = _seg(idx=1, phase="grasp_object", start_frame=30, end_frame=32, vlm=0.6)
    long_r = _seg(idx=2, phase="lift_object", start_frame=32, end_frame=62, vlm=0.9)  # higher
    cfg = SmootherConfig(min_segment_duration_sec=0.30)
    out, absorbs = _merge_short([long_l, short, long_r], config=cfg)
    assert absorbs == 1
    # short merged into right (higher overall_confidence): output is [long_l, long_r_extended]
    assert len(out) == 2
    assert out[1].phase == "lift_object"
    assert out[1].start_frame == 30
    assert out[1].end_frame == 62
    assert "merge_short" in out[1].smoothing_ops


def test_merge_short_tie_prefers_left() -> None:
    long_l = _seg(idx=0, phase="approach_object", start_frame=0, end_frame=30, vlm=0.5)
    short = _seg(idx=1, phase="grasp_object", start_frame=30, end_frame=32, vlm=0.6)
    long_r = _seg(idx=2, phase="lift_object", start_frame=32, end_frame=62, vlm=0.5)  # tie
    cfg = SmootherConfig(min_segment_duration_sec=0.30)
    out, _ = _merge_short([long_l, short, long_r], config=cfg)
    # Tie → prefer left → short merged into long_l
    assert out[0].phase == "approach_object"
    assert out[0].end_frame == 32
    assert out[1].phase == "lift_object"


def test_merge_short_single_segment_no_neighbor_passes_through() -> None:
    only = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=2)
    cfg = SmootherConfig(min_segment_duration_sec=0.30)
    out, absorbs = _merge_short([only], config=cfg)
    assert len(out) == 1
    assert out[0].smoothing_ops == []
    assert absorbs == 0


def test_merge_short_no_short_segments_identity() -> None:
    a = _seg(idx=0, phase="approach_object", start_frame=0, end_frame=30)
    b = _seg(idx=1, phase="grasp_object", start_frame=30, end_frame=60)
    cfg = SmootherConfig(min_segment_duration_sec=0.30)
    out, absorbs = _merge_short([a, b], config=cfg)
    assert len(out) == 2
    assert absorbs == 0
    assert all(s.smoothing_ops == [] for s in out)


def test_merge_short_all_short_cascade() -> None:
    """All segments below threshold, equal confidence → cascade to one segment.
    Left-preference on each absorb."""
    segs = [_seg(idx=i, phase=f"phase_{i}", start_frame=i*2, end_frame=(i+1)*2, vlm=0.5)
            for i in range(4)]
    cfg = SmootherConfig(min_segment_duration_sec=0.30)
    out, absorbs = _merge_short(segs, config=cfg)
    # Each absorb collapses 2 → 1; 4 segments → 1 in 3 absorbs
    assert len(out) == 1
    assert absorbs == 3


def test_merge_short_smoothing_ops_records_merge_short() -> None:
    long_l = _seg(idx=0, phase="approach_object", start_frame=0, end_frame=30, vlm=0.5)
    short = _seg(idx=1, phase="grasp_object", start_frame=30, end_frame=32, vlm=0.5,
                 smoothing_ops=["merge_same_label"])  # prior op
    cfg = SmootherConfig(min_segment_duration_sec=0.30)
    out, _ = _merge_short([long_l, short], config=cfg)
    assert len(out) == 1
    # union of left.ops + absorbed.ops + ['merge_short']
    assert "merge_short" in out[0].smoothing_ops
    assert "merge_same_label" in out[0].smoothing_ops


def test_merge_short_boundary_confidence_re_derived() -> None:
    long_l = _seg(idx=0, phase="approach_object", start_frame=0, end_frame=30,
                  start_score=0.9, end_score=0.7, vlm=0.5)
    short = _seg(idx=1, phase="grasp_object", start_frame=30, end_frame=32,
                 start_score=0.7, end_score=0.4, vlm=0.5)
    cfg = SmootherConfig(min_segment_duration_sec=0.30)
    out, _ = _merge_short([long_l, short], config=cfg)
    # Absorb into left: merged spans 0-32. start_score=0.9, end_score=0.4.
    # boundary_confidence = min(0.9, 0.4) = 0.4
    assert math.isclose(out[0].boundary_confidence, 0.4)


def test_merge_short_left_only_neighbor() -> None:
    """Short segment at the right end with no right neighbor → absorbs left."""
    long_l = _seg(idx=0, phase="approach_object", start_frame=0, end_frame=30, vlm=0.5)
    short = _seg(idx=1, phase="grasp_object", start_frame=30, end_frame=32, vlm=0.9)
    cfg = SmootherConfig(min_segment_duration_sec=0.30)
    out, _ = _merge_short([long_l, short], config=cfg)
    assert len(out) == 1
    # Only neighbor is left → absorb left, regardless of confidence
    assert out[0].phase == "approach_object"


def test_merge_short_right_only_neighbor() -> None:
    """Short segment at the left end with no left neighbor → absorbs right."""
    short = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=2, vlm=0.9)
    long_r = _seg(idx=1, phase="approach_object", start_frame=2, end_frame=32, vlm=0.5)
    cfg = SmootherConfig(min_segment_duration_sec=0.30)
    out, _ = _merge_short([short, long_r], config=cfg)
    assert len(out) == 1
    assert out[0].phase == "approach_object"


def test_merge_short_then_same_label_pass_idempotent_when_no_new_adjacency() -> None:
    """Spec §3.3: after Op 2, run Op 1 once more. Verify Op 2 alone returns
    a list that may have new same-label adjacencies — caller (apply_smoothing)
    handles the follow-up."""
    a = _seg(idx=0, phase="grasp_object", start_frame=0, end_frame=30, vlm=0.5)
    short = _seg(idx=1, phase="approach_object", start_frame=30, end_frame=32, vlm=0.5)
    c = _seg(idx=2, phase="grasp_object", start_frame=32, end_frame=62, vlm=0.5)
    cfg = SmootherConfig(min_segment_duration_sec=0.30)
    out, _ = _merge_short([a, short, c], config=cfg)
    # `short` (approach_object) absorbed into one neighbor (left, by tie-break);
    # the result has two grasp_object segments adjacent — but Op 2 itself
    # does NOT collapse them; that's Op 1's job. Verify Op 2 leaves them be.
    assert len(out) == 2
    # Now both phases are "grasp_object" (left absorbed approach into itself,
    # but the merged segment's phase is the LEFT's phase = grasp_object).
    assert out[0].phase == "grasp_object" and out[1].phase == "grasp_object"
```

- [ ] **Step 8.2: Run tests; expect ImportError on `_merge_short`.**

```bash
.venv/bin/python -m pytest tests/unit/test_smoother_merge_short.py -v
```

- [ ] **Step 8.3: Implement `_merge_short`.**

```python
def _absorb(into: SubtaskSegment, absorbed: SubtaskSegment, *, on_left: bool) -> SubtaskSegment:
    """Merge `absorbed` into `into`. `on_left` = absorbed is to the LEFT of `into`?

    Spec §3.3: phase / verb / object / target / label_source are taken from the
    SURVIVING (`into`) side regardless of confidence. Field merge otherwise
    follows spec §3.2 union semantics.
    """
    if on_left:
        new_start = absorbed.start_boundary
        new_end = into.end_boundary
        new_start_frame, new_start_time = absorbed.start_frame, absorbed.start_time
        new_end_frame, new_end_time = into.end_frame, into.end_time
    else:
        new_start = into.start_boundary
        new_end = absorbed.end_boundary
        new_start_frame, new_start_time = into.start_frame, into.start_time
        new_end_frame, new_end_time = absorbed.end_frame, absorbed.end_time

    # vlm_confidence: duration-weighted mean (None handling per Op 1)
    if into.vlm_confidence is None and absorbed.vlm_confidence is None:
        new_vlm: float | None = None
    elif into.vlm_confidence is None:
        new_vlm = absorbed.vlm_confidence
    elif absorbed.vlm_confidence is None:
        new_vlm = into.vlm_confidence
    else:
        d_into = into.end_time - into.start_time
        d_abs = absorbed.end_time - absorbed.start_time
        total = d_into + d_abs
        new_vlm = (into.vlm_confidence * d_into + absorbed.vlm_confidence * d_abs) / total if total > 0 else (into.vlm_confidence + absorbed.vlm_confidence) / 2

    merged = SubtaskSegment(
        segment_id="",
        episode_id=into.episode_id,
        start_frame=new_start_frame, end_frame=new_end_frame,
        start_time=new_start_time, end_time=new_end_time,
        # Spec §3.3: surviving (into) side wins on label fields
        phase=into.phase, verb=into.verb, object=into.object, target=into.target,
        failure_flags=sorted(set(into.failure_flags) | set(absorbed.failure_flags)),
        label_source=into.label_source,
        object_state_unavailable=into.object_state_unavailable or absorbed.object_state_unavailable,
        object_track_ids=sorted(set(into.object_track_ids) | set(absorbed.object_track_ids)),
        label_version=into.label_version,
        start_boundary=new_start, end_boundary=new_end,
        boundary_confidence=0.0,
        vlm_confidence=new_vlm,
        overall_confidence=0.0,
        evidence=into.evidence,
        reviewed=False, reviewer_id=None,
        smoothing_ops=_dedup_consecutive(
            list(into.smoothing_ops) + list(absorbed.smoothing_ops) + ["merge_short"]
        ),
    )
    return _recompute_confidence(merged)


def _is_short(seg: SubtaskSegment, *, threshold_sec: float) -> bool:
    return (seg.end_time - seg.start_time) < threshold_sec


def _induces_forbidden(
    pair: tuple[str, str],
    forbidden: tuple[tuple[str, str], ...],
) -> bool:
    return pair in forbidden


def _merge_short(
    segments: list[SubtaskSegment],
    *,
    config: SmootherConfig,
) -> tuple[list[SubtaskSegment], int]:
    """Op 2 (spec §3.3). Repeats until no segment is below threshold."""
    threshold = config.min_segment_duration_sec
    forbidden = config.forbidden_transitions
    if len(segments) <= 1:
        return list(segments), 0

    current = list(segments)
    absorbs = 0
    while True:
        i = 0
        progress = False
        while i < len(current):
            if not _is_short(current[i], threshold_sec=threshold):
                i += 1
                continue
            # Identify neighbors
            has_left = i > 0
            has_right = i + 1 < len(current)
            if not has_left and not has_right:
                # Single segment, no neighbor — pass through
                i += 1
                continue
            if has_left and not has_right:
                # Only left neighbor: absorb absorbed into left
                merged = _absorb(into=current[i - 1], absorbed=current[i], on_left=False)
                current = current[: i - 1] + [merged] + current[i + 1 :]
                absorbs += 1
                progress = True
                i = max(i - 1, 0)
                continue
            if has_right and not has_left:
                # Only right neighbor
                merged = _absorb(into=current[i + 1], absorbed=current[i], on_left=True)
                current = current[:i] + [merged] + current[i + 2 :]
                absorbs += 1
                progress = True
                continue
            # Both neighbors: pick by overall_confidence
            left = current[i - 1]
            right = current[i + 1]
            short_seg = current[i]
            if left.overall_confidence > right.overall_confidence:
                pick = "left"
            elif right.overall_confidence > left.overall_confidence:
                pick = "right"
            else:
                # Tie: avoid forbidden transition with the *opposite* side
                # If absorb-left → merged-left adjacent to right; check (left.phase, right.phase)
                left_creates_forbidden = (i + 1 < len(current)) and _induces_forbidden(
                    (left.phase, right.phase), forbidden,
                )
                right_creates_forbidden = (i > 0) and _induces_forbidden(
                    (left.phase, right.phase), forbidden,
                )
                if left_creates_forbidden and not right_creates_forbidden:
                    pick = "right"
                elif right_creates_forbidden and not left_creates_forbidden:
                    pick = "left"
                else:
                    pick = "left"   # default left preference
            if pick == "left":
                merged = _absorb(into=left, absorbed=short_seg, on_left=False)
                current = current[: i - 1] + [merged] + current[i + 1 :]
                i = max(i - 1, 0)
            else:
                merged = _absorb(into=right, absorbed=short_seg, on_left=True)
                current = current[:i] + [merged] + current[i + 2 :]
            absorbs += 1
            progress = True
        if not progress:
            break
    return _renumber_segment_ids(current), absorbs
```

The `pick == "left"`/`"right"` branches must keep `i` consistent with the deletion. Verify each path against the test that exercises it.

- [ ] **Step 8.4: Run tests; iterate until pass.**

```bash
.venv/bin/python -m pytest tests/unit/test_smoother_merge_short.py -v
# Expected: 10 PASS.
```

- [ ] **Step 8.5: Type-check + lint.**

```bash
.venv/bin/python -m mypy --strict mimicanno/smoother.py
.venv/bin/python -m ruff check mimicanno/smoother.py
```

- [ ] **Step 8.6: Commit.**

```bash
git add mimicanno/smoother.py tests/unit/test_smoother_merge_short.py
git commit -m "feat(smoother): Op 2 min-duration absorb (spec §3.3)"
```

---

## Task 9: Op 3 — `_viterbi_relabel`

**Files:**
- Modify: `mimicanno/smoother.py`
- Test: `tests/unit/test_smoother_viterbi.py` (new)

Goal: Implement the constrained Viterbi DP per spec §3.4. Tuple-comparator tie-break is normative.

- [ ] **Step 9.1: Write failing tests.**

```python
# tests/unit/test_smoother_viterbi.py
"""Op 3: Viterbi relabel + deterministic tie-break (spec §3.4)."""
from __future__ import annotations

import math

import pytest

from mimicanno.config import SmootherConfig
from mimicanno.schema import BoundaryRef, SubtaskSegment
from mimicanno.smoother import _viterbi_relabel


def _seg(*, idx: int, phase: str, vlm: float | None = 0.7,
         label_source: str = "vlm_with_object_state") -> SubtaskSegment:
    bc = 0.5
    if phase in {"unlabeled", "unknown"}:
        oc = 0.0
    elif vlm is None:
        oc = bc
    else:
        oc = math.sqrt(bc * vlm)
    return SubtaskSegment(
        segment_id=f"ep__seg{idx:04d}", episode_id="ep",
        start_frame=idx*10, end_frame=(idx+1)*10,
        start_time=idx*10/30, end_time=(idx+1)*10/30,
        phase=phase, verb=None, object=None, target=None,
        failure_flags=[],
        label_source=label_source,  # type: ignore[arg-type]
        object_state_unavailable=False, object_track_ids=[],
        label_version="v1",
        start_boundary=BoundaryRef(candidate_id=f"b{idx}s", frame=idx*10, score=bc),
        end_boundary=BoundaryRef(candidate_id=f"b{idx}e", frame=(idx+1)*10, score=bc),
        boundary_confidence=bc, vlm_confidence=vlm, overall_confidence=oc,
        evidence=None, reviewed=False, reviewer_id=None,
        smoothing_ops=[],
    )


LABELSET = ["approach_object", "grasp_object", "lift_object", "release_object", "idle"]
# `unknown` is appended internally by the decoder; not in labels.yaml.


def test_viterbi_no_forbidden_identity() -> None:
    cfg = SmootherConfig(viterbi_enabled=True, lambda_forbidden=0.5,
                         forbidden_transitions=())
    segs = [_seg(idx=0, phase="grasp_object"), _seg(idx=1, phase="approach_object")]
    out, relabels, skipped = _viterbi_relabel(segs, config=cfg, labelset=LABELSET)
    assert relabels == 0
    assert skipped is False
    assert [s.phase for s in out] == ["grasp_object", "approach_object"]


def test_viterbi_disabled_skips() -> None:
    cfg = SmootherConfig(viterbi_enabled=False)
    segs = [_seg(idx=0, phase="grasp_object"), _seg(idx=1, phase="approach_object")]
    out, relabels, skipped = _viterbi_relabel(segs, config=cfg, labelset=LABELSET)
    assert skipped is True
    assert relabels == 0
    assert out == segs


def test_viterbi_single_segment_skipped() -> None:
    cfg = SmootherConfig(viterbi_enabled=True)
    segs = [_seg(idx=0, phase="grasp_object")]
    out, relabels, skipped = _viterbi_relabel(segs, config=cfg, labelset=LABELSET)
    assert skipped is True
    assert relabels == 0


def test_viterbi_lambda_zero_no_relabels() -> None:
    """lambda=0 → no transition penalty → identity."""
    cfg = SmootherConfig(viterbi_enabled=True, lambda_forbidden=0.0,
                         forbidden_transitions=(("grasp_object", "approach_object"),))
    segs = [_seg(idx=0, phase="grasp_object", vlm=0.3),
            _seg(idx=1, phase="approach_object", vlm=0.3)]
    out, relabels, _ = _viterbi_relabel(segs, config=cfg, labelset=LABELSET)
    assert relabels == 0


def test_viterbi_low_confidence_forbidden_pair_flips_lower_side() -> None:
    """grasp_object → approach_object is forbidden. Both at vlm=0.3.
    Penalty 0.5 > emission gain 0.3, so flipping the lower-confidence side
    (or either side, since they tie at 0.3) wins. The deterministic
    tie-break should pick the lexicographically-first decoded path."""
    cfg = SmootherConfig(viterbi_enabled=True, lambda_forbidden=0.5,
                         forbidden_transitions=(("grasp_object", "approach_object"),))
    segs = [_seg(idx=0, phase="grasp_object", vlm=0.3),
            _seg(idx=1, phase="approach_object", vlm=0.3)]
    out, relabels, _ = _viterbi_relabel(segs, config=cfg, labelset=LABELSET)
    assert relabels >= 1
    # Resulting pair must NOT be in forbidden_transitions
    assert (out[0].phase, out[1].phase) != ("grasp_object", "approach_object")


def test_viterbi_high_confidence_forbidden_pair_no_relabel() -> None:
    """Forbidden pair, but both sides have high vlm_confidence.
    Penalty 0.5 < combined emission gain 0.9+0.9 → KEEP both labels."""
    cfg = SmootherConfig(viterbi_enabled=True, lambda_forbidden=0.5,
                         forbidden_transitions=(("grasp_object", "approach_object"),))
    segs = [_seg(idx=0, phase="grasp_object", vlm=0.9),
            _seg(idx=1, phase="approach_object", vlm=0.9)]
    out, relabels, _ = _viterbi_relabel(segs, config=cfg, labelset=LABELSET)
    # Either keep both or relabel just one — but the SCORE-MAX path
    # keeps both for vlm=0.9 each (gain 0.9 each, penalty 0.5; relabel one to 0
    # emission costs more than the penalty). Confirm no relabel.
    assert relabels == 0


def test_viterbi_unknown_observed_filled_by_transitions() -> None:
    """Segment with phase='unknown' and vlm_confidence=None has zero emission
    on every state. With a non-forbidden neighbor, Viterbi should pick the
    transition-cheapest label, breaking ties by labelset declaration order."""
    cfg = SmootherConfig(viterbi_enabled=True, lambda_forbidden=0.5,
                         forbidden_transitions=())
    segs = [_seg(idx=0, phase="grasp_object", vlm=0.9),
            _seg(idx=1, phase="unknown", vlm=None)]
    out, relabels, _ = _viterbi_relabel(segs, config=cfg, labelset=LABELSET)
    # Segment 1 had observed=unknown. Decoder picks any non-forbidden state.
    # Tie-break rule 2: prefer earlier labelset rank → "approach_object" (rank 0).
    assert out[1].phase == "approach_object"
    # Per spec §3.4: allowed-label flips KEEP original verb/object/target;
    # only `phase` changes. Verify smoothing_ops contains viterbi_relabel.
    assert "viterbi_relabel" in out[1].smoothing_ops


def test_viterbi_decoded_unknown_sets_verb_object_target_none() -> None:
    """Spec §3.4: when q*=='unknown', verb/object/target = None."""
    # Force decoder into picking unknown by making all allowed labels
    # forbidden as predecessors of seg[1]'s observed label.
    cfg = SmootherConfig(viterbi_enabled=True, lambda_forbidden=10.0,
                         forbidden_transitions=tuple(
                             (lbl, "grasp_object") for lbl in LABELSET
                         ))
    # seg[0] starts the chain. seg[1] observes grasp_object; every labelset
    # predecessor is forbidden → unknown is the only viable predecessor for
    # grasp_object. The decoder may flip seg[0] to unknown.
    segs = [_seg(idx=0, phase="approach_object", vlm=0.3),
            _seg(idx=1, phase="grasp_object", vlm=0.9)]
    out, relabels, _ = _viterbi_relabel(segs, config=cfg, labelset=LABELSET)
    # If seg[0] was relabeled to unknown, it should have verb/object/target=None.
    if out[0].phase == "unknown":
        assert out[0].verb is None
        assert out[0].object is None
        assert out[0].target is None


def test_viterbi_tie_break_labelset_declaration_order() -> None:
    """Two-segment chain with no emission (both unknown). Decoder must pick
    the path that uses the EARLIEST labels in declaration order. With LABELSET
    above, both segments → 'approach_object'."""
    cfg = SmootherConfig(viterbi_enabled=True, lambda_forbidden=0.0,
                         forbidden_transitions=())
    segs = [_seg(idx=0, phase="unknown", vlm=None),
            _seg(idx=1, phase="unknown", vlm=None)]
    out, _, _ = _viterbi_relabel(segs, config=cfg, labelset=LABELSET)
    assert out[0].phase == "approach_object"
    assert out[1].phase == "approach_object"


def test_viterbi_relabeled_segment_records_op_and_keeps_evidence() -> None:
    cfg = SmootherConfig(viterbi_enabled=True, lambda_forbidden=0.5,
                         forbidden_transitions=(("grasp_object", "approach_object"),))
    a = _seg(idx=0, phase="grasp_object", vlm=0.3)
    a = type(a)(**{**a.__dict__, "evidence": "VLM said grasp because gripper closed"})
    b = _seg(idx=1, phase="approach_object", vlm=0.3)
    out, _, _ = _viterbi_relabel([a, b], config=cfg, labelset=LABELSET)
    relabeled = next((s for s in out if s.phase != s.segment_id.split("__")[-1]), None)
    # Just verify any relabeled segment recorded the op and kept original evidence
    for s, original in zip(out, [a, b]):
        if s.phase != original.phase:
            assert "viterbi_relabel" in s.smoothing_ops
            assert s.evidence == original.evidence


def test_viterbi_overall_confidence_recomputed_on_relabel() -> None:
    cfg = SmootherConfig(viterbi_enabled=True, lambda_forbidden=0.5,
                         forbidden_transitions=(("grasp_object", "approach_object"),))
    segs = [_seg(idx=0, phase="grasp_object", vlm=0.3),
            _seg(idx=1, phase="approach_object", vlm=0.3)]
    out, _, _ = _viterbi_relabel(segs, config=cfg, labelset=LABELSET)
    for s in out:
        # If relabeled to allowed label, overall = sqrt(b*v) using original vlm_confidence.
        # If relabeled to unknown, overall = 0.
        if s.phase == "unknown":
            assert s.overall_confidence == 0.0


def test_viterbi_idempotent_on_already_smooth_input() -> None:
    """Applying Viterbi to an already-smooth (no forbidden pair) sequence
    is the identity."""
    cfg = SmootherConfig(viterbi_enabled=True, lambda_forbidden=0.5,
                         forbidden_transitions=(("grasp_object", "approach_object"),))
    segs = [_seg(idx=0, phase="approach_object", vlm=0.7),
            _seg(idx=1, phase="grasp_object", vlm=0.7),
            _seg(idx=2, phase="lift_object", vlm=0.7)]
    out, relabels, _ = _viterbi_relabel(segs, config=cfg, labelset=LABELSET)
    assert relabels == 0
    assert [s.phase for s in out] == ["approach_object", "grasp_object", "lift_object"]


def test_viterbi_determinism_across_runs() -> None:
    """Same input → byte-identical decoded sequence on repeated runs.
    No iteration-order dependency."""
    cfg = SmootherConfig(viterbi_enabled=True, lambda_forbidden=0.5,
                         forbidden_transitions=(("grasp_object", "approach_object"),))
    segs = [_seg(idx=0, phase="unknown", vlm=None),
            _seg(idx=1, phase="unknown", vlm=None),
            _seg(idx=2, phase="unknown", vlm=None)]
    runs = [_viterbi_relabel(segs, config=cfg, labelset=LABELSET) for _ in range(5)]
    decoded = [tuple(s.phase for s in r[0]) for r in runs]
    assert len(set(decoded)) == 1   # all 5 identical
```

- [ ] **Step 9.2: Run tests; expect ImportError on `_viterbi_relabel`.**

- [ ] **Step 9.3: Implement `_viterbi_relabel`.**

```python
def _materialize_label(seg: SubtaskSegment, decoded_phase: str) -> SubtaskSegment:
    """Spec §3.4: materialize verb/object/target for the decoded phase.

    For decoded `unknown`: verb/object/target = None (parent §6.1 reserved-phase contract;
    matches Phase 2 retry-exhaustion fallback shape).
    For allowed labels (q*_t in labels.yaml): KEEP original verb/object/target.
    Rationale: labelset YAML's `Label` dataclass carries only `id`, `verbs: list[str]`
    (multiple acceptable verb candidates, not a single canonical), and
    `requires_object: bool` — there is no canonical (verb, object, target) tuple
    to materialize from. Preserving the original VLM-extracted values is the best
    signal we have; the `smoothing_ops` log records the relabel so Phase 5's edit
    UI can surface these segments for human review.
    """
    if decoded_phase == seg.phase:
        return seg   # no relabel
    if decoded_phase == "unknown":
        new_verb: str | None = None
        new_object: str | None = None
        new_target: str | None = None
    else:
        new_verb = seg.verb
        new_object = seg.object
        new_target = seg.target
    new_ops = _dedup_consecutive(list(seg.smoothing_ops) + ["viterbi_relabel"])
    return _recompute_confidence(replace(
        seg,
        phase=decoded_phase, verb=new_verb, object=new_object, target=new_target,
        smoothing_ops=new_ops,
    ))


def _viterbi_relabel(
    segments: list[SubtaskSegment],
    *,
    config: SmootherConfig,
    labelset: list[str],
) -> tuple[list[SubtaskSegment], int, bool]:
    """Op 3 (spec §3.4). Returns (segments, relabels_count, viterbi_skipped)."""
    if not config.viterbi_enabled or len(segments) <= 1:
        return list(segments), 0, True

    # State space: labelset (declaration-ordered) + 'unknown' at end
    states: list[str] = list(labelset) + ["unknown"]
    label_rank: dict[str, int] = {s: i for i, s in enumerate(states)}
    alpha_rank: dict[str, int] = {s: i for i, s in enumerate(sorted(states))}
    forbidden = set(config.forbidden_transitions)
    lam = config.lambda_forbidden
    T = len(segments)

    def emission(seg: SubtaskSegment, q: str) -> float:
        if seg.vlm_confidence is None:
            return 0.0
        return seg.vlm_confidence if q == seg.phase else 0.0

    def transition(a: str, b: str) -> float:
        return -lam if (a, b) in forbidden else 0.0

    # DP cell: (q at t) -> (key, predecessor_q)
    # key = (score_main, count_observed, -sum_rank, -sum_alpha)
    # We compare by tuple lexicographic order.
    Cell = tuple[tuple[float, int, int, int], str | None]

    # t=0
    dp: list[dict[str, Cell]] = [{}]
    for q in states:
        e = emission(segments[0], q)
        observed = 1 if q == segments[0].phase else 0
        key = (e, observed, -label_rank[q], -alpha_rank[q])
        dp[0][q] = (key, None)

    # t=1..T-1
    for t in range(1, T):
        cell_t: dict[str, Cell] = {}
        for q in states:
            e = emission(segments[t], q)
            observed_t = 1 if q == segments[t].phase else 0
            best: Cell | None = None
            best_pred: str | None = None
            for q_prev, (prev_key, _) in dp[t - 1].items():
                tr = transition(q_prev, q)
                # New cumulative key: (score+e+tr, count+observed, -sum_rank-rank, -sum_alpha-alpha)
                new_key = (
                    prev_key[0] + e + tr,
                    prev_key[1] + observed_t,
                    prev_key[2] + (-label_rank[q]),
                    prev_key[3] + (-alpha_rank[q]),
                )
                cand: Cell = (new_key, q_prev)
                if best is None or cand[0] > best[0]:
                    best = cand
                    best_pred = q_prev
            assert best is not None
            cell_t[q] = best
        dp.append(cell_t)

    # Find best final state by tuple key
    final_q = max(dp[-1].keys(), key=lambda q: dp[-1][q][0])
    # Backtrace
    decoded: list[str] = [final_q]
    for t in range(T - 1, 0, -1):
        _, prev = dp[t][decoded[-1]]
        assert prev is not None
        decoded.append(prev)
    decoded.reverse()

    # Materialize relabels
    out: list[SubtaskSegment] = []
    relabels = 0
    for seg, q_star in zip(segments, decoded):
        if q_star != seg.phase:
            relabels += 1
        out.append(_materialize_label(seg, q_star))
    return _renumber_segment_ids(out), relabels, False
```

The DP correctness depends on `tuple > tuple` doing lexicographic comparison (Python does this natively for `tuple`). Verify `(2.0, 1, -3, -5) > (2.0, 1, -4, -5)` evaluates to `True` — it does, since `-3 > -4`.

- [ ] **Step 9.4: Run tests; iterate.**

```bash
.venv/bin/python -m pytest tests/unit/test_smoother_viterbi.py -v
# Expected: 12+ PASS.
```

- [ ] **Step 9.5: Type-check + lint.**

```bash
.venv/bin/python -m mypy --strict mimicanno/smoother.py
.venv/bin/python -m ruff check mimicanno/smoother.py
```

- [ ] **Step 9.6: Commit.**

```bash
git add mimicanno/smoother.py tests/unit/test_smoother_viterbi.py
git commit -m "feat(smoother): Op 3 Viterbi relabel + deterministic tuple-comparator (spec §3.4)"
```

---

## Task 10: `apply_smoothing` orchestrator

**Files:**
- Modify: `mimicanno/smoother.py`
- Test: `tests/unit/test_smoother_apply.py` (extend)

Goal: Wire the three ops together in spec §3 order; produce `SmoothingResult` with summary and ops_log.

- [ ] **Step 10.1: Write failing tests (extend `test_smoother_apply.py`).**

```python
# Append to tests/unit/test_smoother_apply.py

from mimicanno.config import SmootherConfig
from mimicanno.schema import SmoothingSummary
from mimicanno.smoother import apply_smoothing


LABELSET = ["approach_object", "grasp_object", "lift_object", "release_object", "idle"]


def test_apply_smoothing_empty_input() -> None:
    cfg = SmootherConfig()
    result = apply_smoothing([], config=cfg, labelset=LABELSET)
    assert result.segments == []
    assert result.summary.initial_segment_count == 0
    assert result.summary.final_segment_count == 0
    assert result.summary.viterbi_skipped is True


def test_apply_smoothing_single_segment_passthrough() -> None:
    only = _seg()
    cfg = SmootherConfig()
    result = apply_smoothing([only], config=cfg, labelset=LABELSET)
    assert len(result.segments) == 1
    assert result.summary.initial_segment_count == 1
    assert result.summary.final_segment_count == 1


def test_apply_smoothing_idempotent_on_stable_input() -> None:
    """Apply twice = apply once if input is already smooth."""
    cfg = SmootherConfig(forbidden_transitions=())
    segs = [_seg(phase="approach_object", start_score=0.5, end_score=0.5,
                 vlm_confidence=0.7),
            _seg(phase="grasp_object", start_score=0.5, end_score=0.5,
                 vlm_confidence=0.7)]
    # Override start/end frames for non-overlap
    segs[0] = type(segs[0])(**{**segs[0].__dict__,
                                "start_frame": 0, "end_frame": 30,
                                "start_time": 0.0, "end_time": 1.0,
                                "segment_id": "ep__seg0000"})
    segs[1] = type(segs[1])(**{**segs[1].__dict__,
                                "start_frame": 30, "end_frame": 60,
                                "start_time": 1.0, "end_time": 2.0,
                                "segment_id": "ep__seg0001"})
    result1 = apply_smoothing(segs, config=cfg, labelset=LABELSET)
    result2 = apply_smoothing(result1.segments, config=cfg, labelset=LABELSET)
    assert [s.phase for s in result1.segments] == [s.phase for s in result2.segments]


def test_apply_smoothing_summary_counts_match() -> None:
    """Compose a fixture exercising all 3 ops and verify summary counts."""
    # 3 same-label adjacent + 1 short + 1 forbidden-pair-low-conf scenario.
    # See spec §4.3 SmoothingSummary fields.
    # ... (build fixture, call apply_smoothing, assert each count)
    pass


def test_apply_smoothing_no_segment_pair_violates_forbidden_after_smoothing() -> None:
    """Spec exit criterion §10 #3: no adjacent pair (s_i, s_{i+1}) is in
    forbidden_transitions AND both have overall_confidence > 0.5."""
    # ... (build fixture with forbidden pair, both vlm > 0.5, call apply,
    # assert no violation in result)
    pass


def test_apply_smoothing_segment_invariant_check_passes_on_smooth_input() -> None:
    """§3.6 invariant check should pass for a normal apply_smoothing run."""
    cfg = SmootherConfig()
    a = _seg(); a = type(a)(**{**a.__dict__,
                                "start_frame": 0, "end_frame": 30,
                                "start_time": 0.0, "end_time": 1.0,
                                "segment_id": "ep__seg0000",
                                "phase": "approach_object"})
    b = _seg(); b = type(b)(**{**b.__dict__,
                                "start_frame": 30, "end_frame": 60,
                                "start_time": 1.0, "end_time": 2.0,
                                "segment_id": "ep__seg0001",
                                "phase": "grasp_object",
                                "start_boundary": BoundaryRef(candidate_id="b1", frame=30, score=0.5)})
    result = apply_smoothing([a, b], config=cfg, labelset=LABELSET)
    # No exception means invariant check passed.
    assert len(result.segments) >= 1


def test_apply_smoothing_segment_invariant_violation_raises() -> None:
    """If a hand-crafted gap exists between adjacent segments (synthesized
    bypass of the merge ops), the invariant check raises
    smoother_segment_invariant_violation. This guards against regressions
    in the merge functions."""
    from mimicanno.errors import MimicAnnoError    # adjust to actual base
    from mimicanno.smoother import _assert_segment_invariants
    a = _seg(); a = type(a)(**{**a.__dict__,
                                "end_boundary": BoundaryRef(candidate_id="ax", frame=10, score=0.5)})
    b = _seg(); b = type(b)(**{**b.__dict__,
                                "segment_id": "ep__seg0001",
                                "start_boundary": BoundaryRef(candidate_id="bx", frame=20, score=0.5),
                                "end_boundary": BoundaryRef(candidate_id="by", frame=30, score=0.5)})
    with pytest.raises(MimicAnnoError) as exc_info:
        _assert_segment_invariants([a, b])
    assert exc_info.value.error_code == "smoother_segment_invariant_violation"
```

(For brevity I've left two tests as `pass` placeholders. Fill in the fixtures and assertions during implementation.)

- [ ] **Step 10.2: Implement `apply_smoothing` (with §3.6 post-smoothing invariant check).**

```python
from mimicanno.errors import MimicAnnoError   # adjust to actual base exception class


def _assert_segment_invariants(segments: list[SubtaskSegment]) -> None:
    """Spec §3.6 post-smoothing invariants. Raises smoother_segment_invariant_violation.

    Checks:
    - Adjacent segments share a frame: end_boundary[s_i].frame == start_boundary[s_{i+1}].frame
      (no gaps, no overlaps at the segment-level view).
    - boundary_confidence is finite and in [0, 1].
    - overall_confidence is finite and in [0, 1].
    - smoothing_ops contains only allowed values (defense-in-depth; SubtaskSegment
      __post_init__ already validates, but re-check after merges).
    """
    for i, seg in enumerate(segments):
        # Confidence finiteness
        if not (math.isfinite(seg.boundary_confidence) and 0.0 <= seg.boundary_confidence <= 1.0):
            raise MimicAnnoError(
                error_code="smoother_segment_invariant_violation",
                message=(f"segment {seg.segment_id}: boundary_confidence "
                         f"{seg.boundary_confidence!r} not finite or not in [0,1]"),
            )
        if not (math.isfinite(seg.overall_confidence) and 0.0 <= seg.overall_confidence <= 1.0):
            raise MimicAnnoError(
                error_code="smoother_segment_invariant_violation",
                message=(f"segment {seg.segment_id}: overall_confidence "
                         f"{seg.overall_confidence!r} not finite or not in [0,1]"),
            )
        # Adjacency
        if i + 1 < len(segments):
            nxt = segments[i + 1]
            if seg.end_boundary.frame != nxt.start_boundary.frame:
                raise MimicAnnoError(
                    error_code="smoother_segment_invariant_violation",
                    message=(f"segments {seg.segment_id} / {nxt.segment_id} have "
                             f"a gap or overlap: end_frame={seg.end_boundary.frame} "
                             f"!= start_frame={nxt.start_boundary.frame}"),
                )


def apply_smoothing(
    segments: list[SubtaskSegment],
    *,
    config: SmootherConfig,
    labelset: list[str],
) -> SmoothingResult:
    """Phase 4 smoothing pipeline (spec §3).

    Order: same-label merge → min-duration absorb → (Op 1 again) → Viterbi (optional)
           → (Op 1 again) → invariant check.
    """
    initial = len(segments)
    if initial == 0:
        return SmoothingResult(
            segments=[],
            summary=SmoothingSummary(
                initial_segment_count=0, final_segment_count=0,
                merge_same_label_rounds=0, merge_same_label_collapses=0,
                merge_short_absorbs=0, viterbi_relabels=0, viterbi_skipped=True,
            ),
            ops_log=[],
        )
    ops_log: list[tuple[SmoothingOp, list[str]]] = []

    # Op 1
    after_op1, rounds1, collapses1 = _merge_same_label(list(segments))
    if collapses1 > 0:
        ops_log.append(("merge_same_label", [s.segment_id for s in after_op1]))

    # Op 2
    after_op2, absorbs = _merge_short(after_op1, config=config)
    if absorbs > 0:
        ops_log.append(("merge_short", [s.segment_id for s in after_op2]))
        # Op 1 follow-up
        after_op2, rounds_after_op2, collapses_after_op2 = _merge_same_label(after_op2)
        rounds1 += rounds_after_op2
        collapses1 += collapses_after_op2

    # Op 3
    after_op3, relabels, viterbi_skipped = _viterbi_relabel(
        after_op2, config=config, labelset=labelset,
    )
    if relabels > 0:
        ops_log.append(("viterbi_relabel", [s.segment_id for s in after_op3]))
        # Op 1 follow-up after Viterbi (spec §3.4 final-step rule)
        after_op3, rounds_after_op3, collapses_after_op3 = _merge_same_label(after_op3)
        rounds1 += rounds_after_op3
        collapses1 += collapses_after_op3

    # Spec §3.6 — post-smoothing invariants
    _assert_segment_invariants(after_op3)

    summary = SmoothingSummary(
        initial_segment_count=initial,
        final_segment_count=len(after_op3),
        merge_same_label_rounds=rounds1,
        merge_same_label_collapses=collapses1,
        merge_short_absorbs=absorbs,
        viterbi_relabels=relabels,
        viterbi_skipped=viterbi_skipped,
    )
    return SmoothingResult(segments=after_op3, summary=summary, ops_log=ops_log)
```

The exact `MimicAnnoError` constructor signature may differ; match whatever Phase 1/2/3 use to raise structured errors with `error_code=`.

- [ ] **Step 10.3: Run tests; iterate.**

```bash
.venv/bin/python -m pytest tests/unit/test_smoother_apply.py -v
.venv/bin/python -m pytest tests/unit/ -v -k "smoother"
# Expected: all green, including 4 helper tests from Task 6.
```

- [ ] **Step 10.4: Spot-run codex review on `mimicanno/smoother.py` (mid-impl checkpoint).**

```bash
codex exec --skip-git-repo-check "Review mimicanno/smoother.py against docs/superpowers/specs/2026-04-29-mimicanno-phase4-smoothing-design.md §3. Look for: (1) confidence formula deviations, (2) tie-break iteration-order dependencies, (3) smoothing_ops dedup correctness, (4) any missing edge case from spec §3.3 cascade. Report only blockers." < /dev/null
```

Iterate on any blocker reported before proceeding.

- [ ] **Step 10.5: Type-check + lint + commit.**

```bash
.venv/bin/python -m mypy --strict mimicanno/smoother.py
.venv/bin/python -m ruff check mimicanno/smoother.py
git add mimicanno/smoother.py tests/unit/test_smoother_apply.py
git commit -m "feat(smoother): apply_smoothing orchestrator (spec §3)"
```

---

## Task 11: `annotate_episode_phase4` orchestrator

**Files:**
- Modify: `mimicanno/pipeline.py`
- Test: covered by integration tests in Task 13.

Goal: Add the Phase 4 orchestrator that re-uses Phase 3 inner pipeline for signals → boundaries → SAM3 → labeling, then applies smoothing, then writes artifacts.

- [ ] **Step 11.1: Inspect `annotate_episode_phase3` to identify the labeled-segments handoff point.**

```bash
grep -n "annotate_episode_phase3\|labeled_segments\|apply_phase3_labeling\|write" mimicanno/pipeline.py | head -30
```

- [ ] **Step 11.2: Implement `annotate_episode_phase4`.**

Pattern: copy `annotate_episode_phase3`, add `apply_smoothing` call after labeling, wire `pipeline_phase=4` and `smoothing_summary` into the manifest.

```python
# mimicanno/pipeline.py — add near annotate_episode_phase3
def annotate_episode_phase4(req: AnnotateRequest) -> AnnotateResult:
    """Phase 4 orchestrator (spec §1.1).

    Re-runs the Phase 3 inner pipeline (signals → boundaries → SAM3 → labeling)
    then applies the Phase 4 smoother and writes artifacts with pipeline_phase=4.
    """
    # ... (existing Phase 3 inner pipeline code, OR refactor _annotate_episode_phase3_inner
    #      to return (segments, manifest_partial, ...) and call it here.)
    # The cleanest pattern: extract a shared helper `_run_phase3_inner(req)` that
    # returns the labeled segments + tracks + manifest scaffolding, and have
    # annotate_episode_phase3 call it and write, while annotate_episode_phase4
    # calls it, smooths, then writes.

    cfg = req.config
    assert cfg.target_phase == 4, "annotate_episode_phase4 requires target_phase=4"
    assert cfg.smoother is not None, "Phase 4 requires SmootherConfig"

    # 1) Phase 3 inner work (re-use existing helpers)
    segments, tracks_artifact, phase3_outcome, _coverage = _run_phase3_inner_pipeline(req)

    # 2) Smoothing
    # Pass labels in DECLARATION ORDER (spec §3.4 rule 2) — not as a set.
    # `LabelSet.labels` is a list[Label]; preserve order via [.id for ...].
    label_ids_in_order = [lbl.id for lbl in req.labelset.labels]
    smoothing_result = apply_smoothing(
        segments,
        config=cfg.smoother,
        labelset=label_ids_in_order,
    )

    # 3) Write artifacts with pipeline_phase=4 + smoothing_summary
    manifest = Manifest(
        # ... existing fields, but with:
        pipeline_phase=4,
        smoothing_summary=smoothing_result.summary,
        # ... pipeline_status carries over from Phase 3 untouched
    )

    publish(req, segments=smoothing_result.segments, manifest=manifest, tracks=tracks_artifact)
    return AnnotateResult(...)
```

The exact `_run_phase3_inner_pipeline` extraction depends on how Phase 3's orchestrator is currently written. If it's monolithic, **first refactor** Phase 3 to expose the inner pipeline as a callable; ensure all Phase 3 tests still pass byte-for-byte. Then build Phase 4 on top.

- [ ] **Step 11.3: Run all existing Phase 3 tests after the refactor (if any).**

```bash
.venv/bin/python -m pytest tests/integration/test_phase3_*.py tests/unit/test_phase3_*.py -v
# Expected: all green.
```

- [ ] **Step 11.4: Type-check + lint.**

```bash
.venv/bin/python -m mypy --strict mimicanno/pipeline.py
.venv/bin/python -m ruff check mimicanno/pipeline.py
```

- [ ] **Step 11.5: Commit.**

```bash
git add mimicanno/pipeline.py
git commit -m "feat(pipeline): annotate_episode_phase4 orchestrator (spec §1.1)"
```

---

## Task 12: CLI `--target-phase 4`, `--smoother-config`, `--no-viterbi`

**Files:**
- Modify: `mimicanno/cli.py`
- Modify: `mimicanno/preflight.py`
- Create: `configs/smoother/default.yaml`
- Test: covered by integration tests in Task 13.

Goal: Wire the new CLI flags and pre-flight order per spec §5.

- [ ] **Step 12.1: Add `--smoother-config` and `--no-viterbi` flags.**

```python
# mimicanno/cli.py — extend the Typer command
@app.command()
def annotate(
    # ... existing options ...
    target_phase: int = typer.Option(...),
    smoother_config: Path | None = typer.Option(None, help="..."),
    no_viterbi: bool = typer.Option(False, help="Disable Viterbi relabel (spec §3.4)."),
) -> None:
    if target_phase not in {1, 2, 3, 4}:
        raise SystemExit(f"--target-phase must be 1-4, got {target_phase}")
    # ...existing dispatch...
    if target_phase == 4:
        smoother_cfg = _resolve_smoother_config(smoother_config, allowed_labels=...)
        if no_viterbi:
            smoother_cfg = replace(smoother_cfg, viterbi_enabled=False)
        annotation_cfg = AnnotationConfig(..., smoother=smoother_cfg)
        result = annotate_episode_phase4(req)
    elif target_phase == 3:
        ...
    # etc.
```

- [ ] **Step 12.2: Add pre-flight resolver `_resolve_smoother_config` (or extend `mimicanno/preflight.py`).**

Per spec §5: Phase 4 pre-flight runs Phase 3 pre-flight first, then validates `--smoother-config` if given. Validation errors surface as `error_code="smoother_config_invalid"` (or `smoother_unknown_label_in_forbidden`) and exit 2.

- [ ] **Step 12.3: Ship `configs/smoother/default.yaml`.**

```yaml
# Default Phase 4 SmootherConfig values (spec §2.1 / §12 Resolved Decisions).
min_segment_duration_sec: 0.30
forbidden_transitions:
  - [grasp_object, approach_object]
  - [release_object, grasp_object]
  - [lift_object, idle]
viterbi_enabled: true
lambda_forbidden: 0.5
```

- [ ] **Step 12.4: Type-check + lint.**

```bash
.venv/bin/python -m mypy --strict mimicanno/cli.py mimicanno/preflight.py
.venv/bin/python -m ruff check mimicanno/cli.py mimicanno/preflight.py
```

- [ ] **Step 12.5: Commit.**

```bash
git add mimicanno/cli.py mimicanno/preflight.py configs/smoother/default.yaml
git commit -m "feat(cli,preflight): --target-phase 4, --smoother-config, --no-viterbi (spec §5)"
```

---

## Task 13: Integration tests (end-to-end Phase 4 + no-regression)

**Files:**
- Test (new):
  - `tests/integration/test_phase4_happy_path.py`
  - `tests/integration/test_phase4_no_phase123_regression.py`
  - `tests/integration/test_phase4_viterbi_disabled.py`
  - `tests/integration/test_phase4_smoother_yaml_override.py`
  - `tests/integration/test_phase4_per_segment_fallback.py`
  - `tests/integration/test_phase4_cross_artifact.py`

Goal: End-to-end coverage per spec §8.2. Re-uses the Phase 3 fixture harness (FixtureVLM + FixtureSAM3) at `tests/integration/_phase3_harness.py`.

- [ ] **Step 13.1: Inspect Phase 3 harness for the entry pattern.**

```bash
ls tests/integration/_phase3_harness.py
grep -n "patch_phase3\|FixtureVLM\|FixtureSAM3" tests/integration/_phase3_harness.py | head -20
```

- [ ] **Step 13.2: Write `test_phase4_happy_path.py`.**

```python
# tests/integration/test_phase4_happy_path.py
"""Phase 4 happy-path smoke (spec §8.2 #1)."""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from mimicanno.cli import app
from tests.integration._phase3_harness import patch_phase3


def test_phase4_happy_path(tmp_path: Path) -> None:
    runner = CliRunner()
    runs_root = tmp_path / "runs"
    with patch_phase3():
        result = runner.invoke(
            app, [
                "annotate",
                "--video", str(_synth_video()),       # adapt to harness conventions
                "--parquet", str(_synth_parquet()),
                "--task", "Pick up the cube and place it in the box.",
                "--robot", "aloha",
                "--target-phase", "4",
                "--vlm-model", "google/gemma-4-E2B-it",
                "--sam3-checkpoint", str(_dummy_checkpoint(tmp_path)),
                "--runs-root", str(runs_root),
                "--score-threshold", "0.10",
            ],
        )
    assert result.exit_code == 0, result.output
    # Locate the run dir
    run_dirs = list(runs_root.iterdir())
    assert len(run_dirs) == 1
    manifest = json.loads((run_dirs[0] / "manifest.json").read_text())
    assert manifest["pipeline_phase"] == 4
    assert "smoothing_summary" in manifest
    assert manifest["smoothing_summary"]["initial_segment_count"] >= manifest["smoothing_summary"]["final_segment_count"]

    annotation = json.loads((run_dirs[0] / "annotation.json").read_text())
    for seg in annotation["segments"]:
        assert "smoothing_ops" in seg
    # Exit criterion §10 #3: no adjacent pair forbidden with both confidence > 0.5
    forbidden = {("grasp_object", "approach_object"),
                 ("release_object", "grasp_object"),
                 ("lift_object", "idle")}
    segs = annotation["segments"]
    for a, b in zip(segs, segs[1:]):
        if (a["phase"], b["phase"]) in forbidden:
            assert min(a["overall_confidence"], b["overall_confidence"]) <= 0.5
```

- [ ] **Step 13.3: Write `test_phase4_no_phase123_regression.py`.**

Mirror `tests/integration/test_phase3_no_phase12_regression.py`. Pin Phase 1, Phase 2, Phase 3 `config_hash` and `run_hash` for the synth fixture; verify they're unchanged after Phase 4 code is present.

- [ ] **Step 13.4: Write the remaining 4 integration tests (viterbi disabled, yaml override, per-segment fallback, cross-artifact).**

(Templates omitted for brevity — model on existing Phase 3 integration tests.)

- [ ] **Step 13.5: Run the full integration suite.**

```bash
.venv/bin/python -m pytest tests/integration/ -v
# Expected: all green.
```

- [ ] **Step 13.6: Run full test suite.**

```bash
.venv/bin/python -m pytest tests/ \
  --ignore=tests/test_phase3_real_sam3_smoke.py \
  --ignore=tests/test_phase2_real_vlm.py
# Expected: 575 (existing) + ~50-60 new = ~630 passed, 1 skipped.
```

- [ ] **Step 13.7: Commit.**

```bash
git add tests/integration/test_phase4_*.py
git commit -m "test(integration): Phase 4 end-to-end + no-regression (spec §8.2)"
```

---

## Task 14: Quality pass + final codex review

**Files:** all modified Phase 4 files.

Goal: Lint clean, mypy --strict clean, full test suite passes, codex final review on the implementation.

- [ ] **Step 14.1: Run mypy --strict on the whole package.**

```bash
.venv/bin/python -m mypy --strict mimicanno/
# Expected: clean. Fix any reported issues.
```

- [ ] **Step 14.2: Run ruff on the whole package.**

```bash
.venv/bin/python -m ruff check mimicanno/ tests/
# Expected: clean.
```

- [ ] **Step 14.3: Run the full test suite one more time.**

```bash
.venv/bin/python -m pytest tests/ \
  --ignore=tests/test_phase3_real_sam3_smoke.py \
  --ignore=tests/test_phase2_real_vlm.py -q
```

- [ ] **Step 14.4: Codex final review on the full Phase 4 diff.**

```bash
git diff main...HEAD -- mimicanno/ tests/ configs/ > /tmp/phase4-impl.diff
codex exec --skip-git-repo-check "Review the Phase 4 implementation diff at /tmp/phase4-impl.diff against docs/superpowers/specs/2026-04-29-mimicanno-phase4-smoothing-design.md. Verify (1) confidence formulas (parent §6.1, §6.4), (2) tie-break determinism, (3) hash-isolation regression guarded, (4) reader tolerance for older annotation versions, (5) all 3 Phase 4 error codes raised. Report blockers only." < /dev/null > /tmp/phase4-impl-review.log 2>&1
```

Iterate on any blocker reported.

- [ ] **Step 14.5: Update memory.**

```bash
# Edit ~/.claude/projects/-home-takakimaeda-MimicAnno/memory/phase4_progress.md
# to mark IMPLEMENTATION COMPLETE and record final test count + commit hash.
```

- [ ] **Step 14.6: Final commit if any post-review fixes.**

```bash
git add ...
git commit -m "chore(phase4): post-review polish"
```

- [ ] **Step 14.7: Hand off to merge.**

After codex approves and the test suite is green, the worktree is ready to merge into `main`. Use `superpowers:finishing-a-development-branch` to choose merge strategy (Phase 3 used `--no-ff` direct merge from local; same pattern here is fine).

---

## Exit checklist (matches spec §10)

Before declaring Phase 4 complete:

- [ ] `mimicanno annotate --target-phase 4 ...` produces a run dir with `pipeline_phase=4` and a non-null `smoothing_summary`.
- [ ] Phase 4 default-config segment count ≤ Phase 3 default-config segment count for the same fixture inputs.
- [ ] No segment-pair `(s_i, s_{i+1})` in any Phase 4 fixture run is in `forbidden_transitions` AND has `min(s_i.overall_confidence, s_{i+1}.overall_confidence) > 0.5`.
- [ ] Phase 1 / Phase 2 / Phase 3 `config_hash` and `run_hash` are byte-identical with vs. without Phase 4 code present (regression test passes).
- [ ] Annotation reader accepts both `schema_version=0.1.0` and `schema_version=0.2.0`.
- [ ] `mypy --strict mimicanno/` clean.
- [ ] `ruff check mimicanno/ tests/` clean.
- [ ] Full pytest suite passes (existing 575 + new Phase 4 tests).
