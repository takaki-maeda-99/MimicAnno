# MimicAnno Phase 5 — Parquet Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `mimicanno export`, a CLI that reads a Phase 1–4 mimicanno run dir + a source LeRobot v3 dataset and writes a SARM-trainable LeRobot v3 dataset augmented with subtask annotations and canonical action features.

**Architecture:** Layered: (1) source reader = existing `RobotAdapter` + a thin parquet loader; (2) canonical IR (`CanonicalEpisode`) holding xyz+rotvec EE pose, body-frame `ee_delta_6d`, normalized gripper, and the full mimicanno segment list; (3) sink writer (`LeRobotV3SinkWriter`) emitting subtask_index per frame, global subtasks registry, per-episode list columns, and a lossless `meta/mimicanno_segments.parquet` sidecar; (4) bulk orchestrator with profile-driven configuration and atomic publish.

**Tech Stack:** Python 3.11, pyarrow/pandas, scipy.spatial.transform (rotvec↔quat), pyyaml, jsonschema, typer (existing CLI), pytest. uv for dependency management.

**Worktree:** `~/MimicAnno-worktrees/phase5-export-impl/` on branch `phase5-export-impl` (already created).

**Spec:** [`docs/superpowers/specs/2026-04-30-mimicanno-phase5-export-design.md`](../specs/2026-04-30-mimicanno-phase5-export-design.md). Read it before starting; this plan references its sections.

**Autonomous-mode directive (CLAUDE.md, 2026-04-30):** until pipeline + real-data sanity check complete, proceed without per-task user approval; spec review and verification still apply.

---

## Conventions for every task

- TDD: write failing test → run, confirm it fails for the **right reason** → implement → run, confirm pass → commit. Do not skip the failing-test step.
- Each task ends with one commit. Use `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` trailer.
- Run all commands from the worktree (`cd ~/MimicAnno-worktrees/phase5-export-impl/`).
- When commands fail, **stop and read the error** — do not retry blindly. If failure is unexpected, fix the root cause; if the test failure was right-reasoned, proceed to the implementation step.
- After every implementation task: run `uv run pytest -q` to confirm no regression. After every 3rd task: run `uv run mypy --strict mimicanno/` and `uv run ruff check mimicanno/`.
- When an implementation requires a contract clarification not in the spec, add a short note to the spec via a follow-up commit. Do not silently diverge.

---

## Phase 0 — Reality checks (Task 0)

### Task 0: Verify SO101 column names + locate adapter / io / runindex APIs

This is a 10-minute "look before you write" pass. No tests, no commits — just record findings to inform Tasks 3, 4, 9, 20.

**Steps:**

- [ ] **Step 1: SO101 column inventory.**

```bash
uv run python -c "
import pyarrow.parquet as pq
t = pq.read_schema('/home/takakimaeda/MimicRec/datasets/SO101/data/chunk-000/episode_000000.parquet')
for f in t: print(f'  {f.name}: {f.type}')
"
```

Confirm column names assumed by `so101_sarm.yaml` (Task 3) match reality:
- `observation.state.gripper_pos` (scalar double)
- `observation.state.ee_pos` (list<float>, 3-vec)
- `observation.state.ee_rotvec` (list<float>, 3-vec)

Also sample gripper range with `pq.read_table(...).column('observation.state.gripper_pos').to_pylist()` → confirm `gripper_scale_max` value (~100 or another constant) for the YAML.

- [ ] **Step 2: Confirm `mimicanno.io` does NOT yet have JSON loaders for annotation / manifest.** Run `grep -n "def read_" mimicanno/io.py`. The current state is loader-light: `read_tracks_json` exists but `read_annotation_result` / `read_manifest` do not. Task 9 must implement them as a sub-step (see updated Task 9 Step 0).

- [ ] **Step 3: Confirm `mimicanno.runindex` API surface.** Run `grep -n "^def\|^class" mimicanno/runindex.py`. Expect `read_index`, `write_index_atomic`, `upsert_row` (or similar). There is **no** `find_runs_for_episode` helper — Task 20 implements its own filter on top of `read_index().rows`.

- [ ] **Step 4: Confirm Phase 4 has been run on at least one SO101 episode.** `ls runs/` (in worktree). If empty, Task 30 Step 1 will need to run Phase 4 first; if populated, that step short-circuits.

No commit — findings flow into the next tasks.

---

## Phase A — Foundation: errors, schemas, profile (Tasks 1–5)

### Task 1: EXPORT_* error codes

**Files:**
- Modify: `mimicanno/errors.py` — add 16 new `ErrorCode` enum members
- Test: `tests/exports/test_errors_codes_exist.py` (new)

**Steps:**

- [ ] **Step 1: Create `tests/exports/__init__.py` (empty) and write failing test**

```python
# tests/exports/test_errors_codes_exist.py
from mimicanno.errors import ErrorCode

EXPECTED_EXPORT_CODES = {
    "EXPORT_PROFILE_INVALID",
    "EXPORT_PROFILE_NOT_FOUND",
    "EXPORT_DATASET_NOT_FOUND",
    "EXPORT_RUNS_ROOT_NOT_FOUND",
    "EXPORT_RUN_NOT_FOUND",
    "EXPORT_RUN_AMBIGUOUS",
    "EXPORT_EPISODE_MISMATCH",
    "EXPORT_PHASE_DOWNGRADE",
    "EXPORT_UNLABELED_PRESENT",
    "EXPORT_NOT_REVIEWED",
    "EXPORT_OUT_EXISTS",
    "EXPORT_OUT_PARENT_MISSING",
    "EXPORT_RAW_ACTION_MISSING",
    "EXPORT_FRAME_COUNT_MISMATCH",
    "EXPORT_INPLACE_NO_CONFIRM",
    "EXPORT_INPLACE_BACKUP_FAILED",
    "EXPORT_SINK_VALIDATION_FAILED",
    "EXPORT_EE_POSE_UNAVAILABLE",   # added: profile demands ee_delta_6d but adapter returns None
}

def test_all_export_codes_exist():
    actual = {m.name for m in ErrorCode if m.name.startswith("EXPORT_")}
    assert EXPECTED_EXPORT_CODES.issubset(actual), f"missing: {EXPECTED_EXPORT_CODES - actual}"
```

- [ ] **Step 2: Run test, confirm it fails**: `uv run pytest tests/exports/test_errors_codes_exist.py -v` → AttributeError or assertion failure listing missing codes.

- [ ] **Step 3: Add the 18 codes to `mimicanno/errors.py` ErrorCode enum.** Each code's value = string identical to its name (existing convention).

- [ ] **Step 4: Run test, confirm pass.**

- [ ] **Step 5: Commit**: `git add tests/exports/__init__.py tests/exports/test_errors_codes_exist.py mimicanno/errors.py && git commit -m "feat(phase5/errors): add 18 EXPORT_* error codes"`

---

### Task 2: JSON schemas (export_profile, export_manifest, mimicanno_segments)

**Files:**
- Create: `mimicanno/jsonschemas/export_profile.schema.json`
- Create: `mimicanno/jsonschemas/export_manifest.schema.json`
- Create: `mimicanno/jsonschemas/mimicanno_segments.schema.json` (parquet column-set spec — JSON Schema-as-documentation, not runtime-validated)
- Modify: `pyproject.toml` — add the three to `[tool.hatch.build.targets.wheel.force-include]`
- Test: `tests/exports/test_schemas_loadable.py` (new)

**Steps:**

- [ ] **Step 1: Write failing test**

```python
# tests/exports/test_schemas_loadable.py
import json
from importlib import resources
import jsonschema

def _load(name):
    return json.loads(resources.files("mimicanno.jsonschemas").joinpath(name).read_text())

def test_export_profile_schema_is_draft_2020():
    sch = _load("export_profile.schema.json")
    jsonschema.Draft202012Validator.check_schema(sch)
    assert sch["$id"].endswith("export_profile.schema.json")

def test_export_manifest_schema_is_draft_2020():
    sch = _load("export_manifest.schema.json")
    jsonschema.Draft202012Validator.check_schema(sch)

def test_mimicanno_segments_schema_documents_columns():
    sch = _load("mimicanno_segments.schema.json")
    # documentation-only schema: required column list per spec §3.1
    cols = sch["required_columns"]
    expected = {"episode_index", "segment_index", "segment_id", "phase", "verb", "object",
                "target", "failure_flags", "start_frame", "end_frame", "start_time",
                "end_time", "label_source", "object_state_unavailable", "object_track_ids",
                "label_version", "boundary_confidence", "vlm_confidence", "overall_confidence",
                "evidence", "reviewed", "reviewer_id", "smoothing_ops",
                "boundary_source_start", "boundary_source_end",
                "run_hash", "config_hash", "input_hash", "pipeline_phase",
                "mimicanno_version", "generated_at"}
    assert set(cols.keys()) == expected
```

- [ ] **Step 2: Run, confirm failure (FileNotFoundError).**

- [ ] **Step 3: Author the three schemas.** Each follows the spec:
  - `export_profile.schema.json`: spec §5.1 YAML structure as JSON Schema Draft 2020-12. Required: `schema_version`, `name`, `source`, `canonical`, `sink`, `sidecar`, `gates`. Sub-objects per spec §5.2.
  - `export_manifest.schema.json`: spec §8 `.mimicanno-export.json` structure.
  - `mimicanno_segments.schema.json`: a custom shape `{"$id":"…","schema_version":"1","required_columns":{<name>:{"type":"<arrow-type>","nullable":<bool>}}}` documenting spec §3.1. (Not validated at runtime against the actual parquet — pyarrow handles type checks.)

- [ ] **Step 4: Update `pyproject.toml` force-include list.**

- [ ] **Step 5: Run test, confirm pass.**

- [ ] **Step 6: Commit**: `feat(phase5/schemas): export_profile / export_manifest / mimicanno_segments JSON schemas`

---

### Task 3: Default profile YAMLs (so101_sarm, aloha_sarm, generic)

**Files:**
- Create: `mimicanno/configs/exports/so101_sarm.yaml`
- Create: `mimicanno/configs/exports/aloha_sarm.yaml`
- Create: `mimicanno/configs/exports/generic.yaml`
- Modify: `pyproject.toml` — add the three to force-include
- Test: `tests/exports/test_default_profiles.py` (new)

**Steps:**

- [ ] **Step 1: Write failing test**

```python
# tests/exports/test_default_profiles.py
import json, jsonschema
from importlib import resources
import yaml

def _validate(yaml_name):
    sch = json.loads(resources.files("mimicanno.jsonschemas").joinpath("export_profile.schema.json").read_text())
    cfg = yaml.safe_load(resources.files("mimicanno.configs.exports").joinpath(yaml_name).read_text())
    jsonschema.Draft202012Validator(sch).validate(cfg)
    return cfg

def test_so101_sarm_profile_loads():
    cfg = _validate("so101_sarm.yaml")
    assert cfg["name"] == "so101_sarm"
    assert cfg["source"]["robot_adapter"] == "generic"   # SO101 uses extended GenericAdapter
    assert cfg["sink"]["params"]["annotation_prefix"] == "mimicanno"

def test_aloha_sarm_profile_loads():
    cfg = _validate("aloha_sarm.yaml")
    assert cfg["source"]["robot_adapter"] == "aloha"

def test_generic_profile_loads():
    cfg = _validate("generic.yaml")
    assert cfg["source"]["robot_adapter"] == "generic"
```

- [ ] **Step 2: Confirm failure.**

- [ ] **Step 3: Author the three YAMLs per spec §5.1.** SO101 profile uses GenericAdapter with embedded column-mapping config:

```yaml
# mimicanno/configs/exports/so101_sarm.yaml
schema_version: "1"
name: so101_sarm
description: |
  Default SO101 → LeRobot v3 SARM-trainable export.
  Body-frame ee_delta_6d + gripper, mimicanno-prefixed annotation columns.
source:
  robot_adapter: generic
  pass_through_raw_action: true
  generic_adapter_config:
    schema_version: "0.2.0"           # bumped from 0.1.0; new fields below
    name: so101
    gripper_column: observation.state.gripper_pos
    gripper_scale_min: 0.0
    gripper_scale_max: 100.0           # SO101 gripper is reported in 0..100 units
    eef_xyz_column: observation.state.ee_pos
    eef_rotvec_column: observation.state.ee_rotvec   # SO101 native rotvec
    eef_quat_column: null                            # mutually exclusive with eef_rotvec_column
canonical:
  delta_basis: body_frame_t
  rotation_repr: rotvec
  gripper_source: observation
sink:
  writer: lerobot_v3
  params:
    annotation_prefix: mimicanno
    subtask_registry_path: meta/subtasks.parquet
    extra_per_frame_columns:
      - {name: mimicanno.ee_delta_6d, source: ee_delta_6d, dtype: float32}
      - {name: mimicanno.gripper_normalized, source: gripper_normalized, dtype: float32}
      - {name: mimicanno.gripper_delta, source: gripper_delta, dtype: float32}
sidecar:
  enabled: true
  path: meta/mimicanno_segments.parquet
gates:
  require_reviewed: false
  forbid_degraded_pipeline: false
  forbid_unlabeled_segments: false
```

`aloha_sarm.yaml`: `robot_adapter: aloha`, no `generic_adapter_config`. Otherwise identical structure.

`generic.yaml`: `robot_adapter: generic`, leaves `generic_adapter_config` as a stub example with all fields commented `<REQUIRED>`. User fills it.

- [ ] **Step 4: Update `pyproject.toml` force-include.**

- [ ] **Step 5: Run test, confirm pass.**

- [ ] **Step 6: Commit**: `feat(phase5/configs): default export profiles (so101_sarm / aloha_sarm / generic)`

---

### Task 4: Extend GenericAdapter with rotvec + gripper-scale fields

**Files:**
- Modify: `mimicanno/adapters/generic.py` — bump schema_version, add 3 new fields
- Test: `tests/adapters/test_generic_extended.py` (new — separate file to keep additive)

**Steps:**

- [ ] **Step 1: Write failing tests for new behavior**

```python
# tests/adapters/test_generic_extended.py
from pathlib import Path
import numpy as np
import pyarrow as pa
import pytest
import yaml

from mimicanno.adapters.generic import GenericAdapter

def _write_yaml(tmp_path, cfg):
    p = tmp_path / "robot.yaml"
    p.write_text(yaml.safe_dump(cfg))
    return p

def test_rotvec_column_passthrough(tmp_path):
    cfg = {
        "schema_version": "0.2.0",
        "name": "so101_test",
        "gripper_column": "g",
        "eef_xyz_column": "xyz",
        "eef_rotvec_column": "rv",
        "eef_quat_column": None,
    }
    a = GenericAdapter.from_yaml(_write_yaml(tmp_path, cfg))
    df = pa.table({
        "g": pa.array([0.0, 50.0, 100.0]),
        "xyz": pa.array([[0.1,0.0,0.0],[0.2,0.0,0.0],[0.3,0.0,0.0]]),
        "rv": pa.array([[0.0,0.0,0.5],[0.0,0.0,0.6],[0.0,0.0,0.7]]),
    })
    pose = a.eef_pose(df)
    assert pose.shape == (3, 6)            # xyz + rotvec when rotvec column is set
    np.testing.assert_allclose(pose[:, 3:], [[0,0,0.5],[0,0,0.6],[0,0,0.7]])

def test_gripper_scale_min_max(tmp_path):
    cfg = {
        "schema_version": "0.2.0",
        "name": "so101_test",
        "gripper_column": "g",
        "gripper_scale_min": 0.0,
        "gripper_scale_max": 100.0,
        "eef_xyz_column": None,
        "eef_quat_column": None,
        "eef_rotvec_column": None,
    }
    a = GenericAdapter.from_yaml(_write_yaml(tmp_path, cfg))
    df = pa.table({"g": pa.array([0.0, 25.0, 50.0, 100.0, 200.0])})
    g = a.gripper_signal(df)
    np.testing.assert_allclose(g, [0.0, 0.25, 0.5, 1.0, 1.0])  # clipped at 1.0

def test_old_v0_1_0_yaml_still_loads_with_quat_column(tmp_path):
    cfg = {
        "schema_version": "0.1.0",
        "name": "legacy",
        "gripper_column": "g",
        "eef_xyz_column": "xyz",
        "eef_quat_column": "q",
    }
    a = GenericAdapter.from_yaml(_write_yaml(tmp_path, cfg))
    df = pa.table({
        "g": pa.array([0.5]),
        "xyz": pa.array([[0.1,0.0,0.0]]),
        "q": pa.array([[0.0,0.0,0.0,1.0]]),
    })
    pose = a.eef_pose(df)
    assert pose.shape == (1, 7)            # legacy path still returns xyz+quat (T,7)
```

- [ ] **Step 2: Confirm failure** (current adapter rejects `0.2.0` and lacks the new fields).

- [ ] **Step 3: Implement.** Update `GenericAdapter`:
  - Accept both `schema_version: 0.1.0` and `0.2.0`. Keep `0.1.0` semantics unchanged for backwards compat.
  - In `0.2.0`: add fields `eef_rotvec_column`, `gripper_scale_min`, `gripper_scale_max`. `eef_quat_column` and `eef_rotvec_column` are mutually exclusive.
  - `gripper_signal`: if `gripper_scale_min`/`max` set, normalize `(g - min) / (max - min)`, then clip [0, 1]. Otherwise existing clip-only behavior.
  - `eef_pose`: if `eef_rotvec_column` set, return (T, 6) `concat(xyz, rotvec)`. Else if `eef_quat_column` set, return (T, 7) as today. Else None.

- [ ] **Step 4: Run tests** → `uv run pytest tests/adapters/test_generic_extended.py -v`. Run full suite to confirm no regression on Phase 1–4 GenericAdapter tests: `uv run pytest tests/adapters/ -v`.

- [ ] **Step 5: Commit**: `feat(adapters/generic): schema 0.2.0 — eef_rotvec_column + gripper_scale_min/max`

---

### Task 5: ExportProfile dataclass + YAML loader + profile_hash

**Files:**
- Create: `mimicanno/exports/__init__.py` (empty for now)
- Create: `mimicanno/exports/profile.py`
- Test: `tests/exports/test_profile.py`

**Steps:**

- [ ] **Step 1: Write failing tests**

```python
# tests/exports/test_profile.py
from pathlib import Path
import pytest
from mimicanno.exports.profile import ExportProfile

def test_load_so101_sarm_by_name():
    p = ExportProfile.resolve("so101_sarm")
    assert p.name == "so101_sarm"
    assert p.source.robot_adapter == "generic"
    assert p.canonical.delta_basis == "body_frame_t"
    assert p.sidecar.enabled is True
    assert p.sink.params["annotation_prefix"] == "mimicanno"

def test_load_aloha_sarm_by_name():
    p = ExportProfile.resolve("aloha_sarm")
    assert p.source.robot_adapter == "aloha"

def test_load_generic_by_name():
    p = ExportProfile.resolve("generic")
    assert p.source.robot_adapter == "generic"

def test_load_by_absolute_path(tmp_path):
    yml = tmp_path / "x.yaml"
    yml.write_text((Path(__file__).parent.parent.parent / "mimicanno/configs/exports/so101_sarm.yaml").read_text())
    p = ExportProfile.resolve(str(yml))
    assert p.name == "so101_sarm"

def test_unknown_profile_raises_EXPORT_PROFILE_NOT_FOUND():
    from mimicanno.errors import MimicAnnoError
    with pytest.raises(MimicAnnoError) as ei:
        ExportProfile.resolve("nonexistent_profile_xyz")
    assert ei.value.code.name == "EXPORT_PROFILE_NOT_FOUND"

def test_invalid_yaml_raises_EXPORT_PROFILE_INVALID(tmp_path):
    from mimicanno.errors import MimicAnnoError
    yml = tmp_path / "bad.yaml"
    yml.write_text("schema_version: 1\nname: bad\n")  # missing required sections
    with pytest.raises(MimicAnnoError) as ei:
        ExportProfile.resolve(str(yml))
    assert ei.value.code.name == "EXPORT_PROFILE_INVALID"

def test_profile_hash_is_stable_across_loads():
    a = ExportProfile.resolve("so101_sarm")
    b = ExportProfile.resolve("so101_sarm")
    assert a.hash() == b.hash()
    assert len(a.hash()) == 64   # sha256 hex

def test_two_different_profiles_have_different_hashes():
    a = ExportProfile.resolve("so101_sarm")
    b = ExportProfile.resolve("aloha_sarm")
    assert a.hash() != b.hash()
```

- [ ] **Step 2: Confirm failure.**

- [ ] **Step 3: Implement `mimicanno/exports/profile.py`.**

```python
# mimicanno/exports/profile.py
"""ExportProfile: typed wrapper around export YAML profiles (spec §5)."""
from __future__ import annotations
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
import hashlib
import json
from typing import Any, Literal

import jsonschema
import yaml

from mimicanno.errors import ErrorCode, MimicAnnoError


@dataclass(frozen=True)
class SourceConfig:
    robot_adapter: Literal["aloha", "koch", "so100", "generic"]
    # NOTE: SO101 routes through "generic" (no so101.py adapter); spec §5.2's example
    # YAML mentioning "so101" is outdated. Default profile so101_sarm.yaml uses "generic"
    # with an embedded generic_adapter_config block.
    pass_through_raw_action: bool
    generic_adapter_config: dict[str, Any] | None = None

@dataclass(frozen=True)
class CanonicalConfig:
    delta_basis: Literal["body_frame_t", "world", "base"]
    rotation_repr: Literal["rotvec"]
    gripper_source: Literal["observation", "action"]

@dataclass(frozen=True)
class SinkConfig:
    writer: Literal["lerobot_v3"]
    params: dict[str, Any]

@dataclass(frozen=True)
class SidecarConfig:
    enabled: bool
    path: str

@dataclass(frozen=True)
class GatesConfig:
    require_reviewed: bool
    forbid_degraded_pipeline: bool
    forbid_unlabeled_segments: bool

@dataclass(frozen=True)
class ExportProfile:
    schema_version: Literal["1"]
    name: str
    description: str
    source: SourceConfig
    canonical: CanonicalConfig
    sink: SinkConfig
    sidecar: SidecarConfig
    gates: GatesConfig

    @classmethod
    def resolve(cls, name_or_path: str) -> ExportProfile:
        """Resolve <name> against package configs, or load <path>."""
        path = cls._resolve_path(name_or_path)
        if path is None:
            raise MimicAnnoError(
                ErrorCode.EXPORT_PROFILE_NOT_FOUND,
                f"profile {name_or_path!r} not found",
                {"name_or_path": name_or_path},
            )
        return cls.from_yaml(path)

    @staticmethod
    def _resolve_path(name_or_path: str) -> Path | None:
        # absolute or ./*.yaml path
        if name_or_path.endswith((".yaml", ".yml")):
            p = Path(name_or_path)
            return p if p.is_file() else None
        # name → package config
        try:
            t = resources.files("mimicanno.configs.exports").joinpath(f"{name_or_path}.yaml")
            return Path(str(t)) if t.is_file() else None
        except (ModuleNotFoundError, FileNotFoundError):
            return None

    @classmethod
    def from_yaml(cls, path: Path) -> ExportProfile:
        try:
            cfg = yaml.safe_load(path.read_text())
        except yaml.YAMLError as e:
            raise MimicAnnoError(
                ErrorCode.EXPORT_PROFILE_INVALID, f"YAML parse error: {e}", {"path": str(path)}
            ) from e
        # Validate against JSON schema
        sch = json.loads(resources.files("mimicanno.jsonschemas").joinpath("export_profile.schema.json").read_text())
        try:
            jsonschema.Draft202012Validator(sch).validate(cfg)
        except jsonschema.ValidationError as e:
            raise MimicAnnoError(
                ErrorCode.EXPORT_PROFILE_INVALID,
                f"profile schema violation: {e.message}",
                {"path": str(path), "json_path": list(e.absolute_path)},
            ) from e
        return cls(
            schema_version=cfg["schema_version"],
            name=cfg["name"],
            description=cfg.get("description", ""),
            source=SourceConfig(**cfg["source"]),
            canonical=CanonicalConfig(**cfg["canonical"]),
            sink=SinkConfig(**cfg["sink"]),
            sidecar=SidecarConfig(**cfg["sidecar"]),
            gates=GatesConfig(**cfg["gates"]),
        )

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict
        return asdict(self)

    def hash(self) -> str:
        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(canonical).hexdigest()
```

- [ ] **Step 4: Run tests, confirm pass.** Run mypy: `uv run mypy --strict mimicanno/exports/`.

- [ ] **Step 5: Commit**: `feat(phase5/exports): ExportProfile dataclass + YAML loader + profile_hash`

---

## Phase B — Canonical IR (Tasks 6–9)

### Task 6: SO(3) helpers — exp_so3 / log_so3 / quat_to_rotvec

**Files:**
- Create: `mimicanno/exports/so3.py`
- Test: `tests/exports/test_so3.py`

**Steps:**

- [ ] **Step 1: Write failing tests with closed-form check values**

```python
# tests/exports/test_so3.py
import numpy as np
import pytest
from mimicanno.exports.so3 import exp_so3, log_so3, quat_to_rotvec, rotvec_to_quat

def test_exp_so3_identity():
    R = exp_so3(np.array([0., 0., 0.]))
    np.testing.assert_allclose(R, np.eye(3), atol=1e-12)

def test_exp_so3_z_quarter():
    R = exp_so3(np.array([0., 0., np.pi/2]))
    expected = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], dtype=float)
    np.testing.assert_allclose(R, expected, atol=1e-12)

def test_log_so3_inverse_of_exp():
    rng = np.random.default_rng(42)
    for _ in range(50):
        rv = rng.normal(size=3) * 0.7  # avoid antipodal
        R = exp_so3(rv)
        rv_back = log_so3(R)
        np.testing.assert_allclose(rv_back, rv, atol=1e-10)

def test_log_so3_identity_is_zero():
    rv = log_so3(np.eye(3))
    np.testing.assert_allclose(rv, np.zeros(3), atol=1e-12)

def test_quat_to_rotvec_xyzw_convention():
    # 90deg around z: quat = (0, 0, sin(pi/4), cos(pi/4))
    q = np.array([[0, 0, np.sin(np.pi/4), np.cos(np.pi/4)]])
    rv = quat_to_rotvec(q)
    np.testing.assert_allclose(rv, [[0, 0, np.pi/2]], atol=1e-10)

def test_rotvec_to_quat_inverse():
    rng = np.random.default_rng(7)
    rv = rng.normal(size=(20, 3)) * 0.5
    q = rotvec_to_quat(rv)
    rv_back = quat_to_rotvec(q)
    np.testing.assert_allclose(rv_back, rv, atol=1e-10)
```

- [ ] **Step 2: Confirm failure (ImportError).**

- [ ] **Step 3: Implement `mimicanno/exports/so3.py` using `scipy.spatial.transform.Rotation`.**

```python
# mimicanno/exports/so3.py
"""SO(3) helpers: rotvec ↔ rotation matrix ↔ quaternion (xyzw)."""
from __future__ import annotations
import numpy as np
from scipy.spatial.transform import Rotation  # type: ignore[import-untyped]

def exp_so3(rotvec: np.ndarray) -> np.ndarray:
    """Rotvec (3,) → rotation matrix (3, 3)."""
    return Rotation.from_rotvec(rotvec).as_matrix()

def log_so3(R: np.ndarray) -> np.ndarray:
    """Rotation matrix (3, 3) → rotvec (3,)."""
    return Rotation.from_matrix(R).as_rotvec()

def quat_to_rotvec(quat_xyzw: np.ndarray) -> np.ndarray:
    """Quaternion (..., 4) in (x, y, z, w) → rotvec (..., 3)."""
    return Rotation.from_quat(quat_xyzw).as_rotvec()

def rotvec_to_quat(rotvec: np.ndarray) -> np.ndarray:
    """Rotvec (..., 3) → quaternion (..., 4) in (x, y, z, w)."""
    return Rotation.from_rotvec(rotvec).as_quat()
```

- [ ] **Step 4: Add `scipy>=1.11` to pyproject.toml `[project.dependencies]` if not already present.** (`scipy>=1.11` is already there per Phase 1.)

- [ ] **Step 5: Run tests → pass. Run `uv run mypy --strict mimicanno/exports/`.**

- [ ] **Step 6: Commit**: `feat(phase5/exports/so3): SO(3) helpers (rotvec ↔ matrix ↔ quat)`

---

### Task 7: CanonicalEpisode dataclass + ee_delta_6d + gripper_delta math

**Files:**
- Create: `mimicanno/exports/canonical.py`
- Test: `tests/exports/test_canonical_math.py`

**Steps:**

- [ ] **Step 1: Write failing tests covering all delta_basis modes and edge cases**

```python
# tests/exports/test_canonical_math.py
import numpy as np
import pytest
from mimicanno.exports.canonical import (
    compute_ee_delta_6d, compute_gripper_delta,
)

def _pose(xyz, rv):
    return np.concatenate([np.array(xyz), np.array(rv)], axis=-1).astype(np.float64)

def test_pure_translation_body_frame_zero_rotation():
    # All rotations identity. body_frame_t Δp_body = world Δp because R_t = I.
    pose = np.array([[0,0,0,0,0,0],[1,0,0,0,0,0],[2,0,0,0,0,0]], dtype=np.float64)
    d = compute_ee_delta_6d(pose, basis="body_frame_t")
    np.testing.assert_allclose(d[0], [1,0,0,0,0,0], atol=1e-12)
    np.testing.assert_allclose(d[1], [1,0,0,0,0,0], atol=1e-12)
    np.testing.assert_allclose(d[2], 0, atol=1e-12)         # last frame padded

def test_pure_z_rotation_body_frame():
    # Rotate by pi/4 around z each frame, no translation.
    pose = np.array([
        [0,0,0, 0,0,0],
        [0,0,0, 0,0,np.pi/4],
        [0,0,0, 0,0,np.pi/2],
    ], dtype=np.float64)
    d = compute_ee_delta_6d(pose, basis="body_frame_t")
    # body-frame rotvec delta: log(R_t.T @ R_{t+1}) = pi/4 around z each step
    np.testing.assert_allclose(d[0, 3:], [0,0,np.pi/4], atol=1e-10)
    np.testing.assert_allclose(d[1, 3:], [0,0,np.pi/4], atol=1e-10)

def test_translation_in_world_seen_from_rotated_body():
    # Frame 0: identity. Frame 1: rotated 90 deg around z, translated +x in world.
    # Body-frame Δp at t=0 should be R_0.T @ (p1 - p0) = [1,0,0] (since R_0 = I).
    pose = np.array([
        [0,0,0, 0,0,0],
        [1,0,0, 0,0,np.pi/2],
    ], dtype=np.float64)
    d = compute_ee_delta_6d(pose, basis="body_frame_t")
    np.testing.assert_allclose(d[0, :3], [1,0,0], atol=1e-10)
    np.testing.assert_allclose(d[0, 3:], [0,0,np.pi/2], atol=1e-10)

def test_world_basis_uses_left_invariant():
    pose = np.array([[0,0,0,0,0,0],[1,2,3,0,0,np.pi/4]], dtype=np.float64)
    d = compute_ee_delta_6d(pose, basis="world")
    np.testing.assert_allclose(d[0, :3], [1,2,3], atol=1e-12)         # plain world delta
    np.testing.assert_allclose(d[0, 3:], [0,0,np.pi/4], atol=1e-10)   # log(R1 R0.T) = R1

def test_base_basis_equals_world_basis():
    pose = np.array([[0,0,0,0,0,0],[1,0,0,0,0,np.pi/4]], dtype=np.float64)
    np.testing.assert_allclose(
        compute_ee_delta_6d(pose, basis="world"),
        compute_ee_delta_6d(pose, basis="base"),
    )

def test_t_equals_one_returns_zero_delta():
    pose = np.array([[0.5,0.5,0.5, 0.1,0.2,0.3]], dtype=np.float64)
    d = compute_ee_delta_6d(pose, basis="body_frame_t")
    assert d.shape == (1, 6)
    np.testing.assert_allclose(d, 0, atol=1e-12)

def test_gripper_delta_basic():
    g = np.array([0.1, 0.3, 0.7, 0.7, 0.2])
    d = compute_gripper_delta(g)
    np.testing.assert_allclose(d, [0.2, 0.4, 0.0, -0.5, 0.0])
```

- [ ] **Step 2: Confirm failure.**

- [ ] **Step 3: Implement `compute_ee_delta_6d` and `compute_gripper_delta`** in `mimicanno/exports/canonical.py`. Stub the `CanonicalEpisode` dataclass so subsequent tasks can import it but leave `build_canonical_episode` for Task 8.

```python
# mimicanno/exports/canonical.py (partial — Task 7)
"""Canonical IR: CanonicalEpisode + ee_delta_6d / gripper_delta math (spec §2)."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
import numpy as np

from mimicanno.exports.so3 import exp_so3, log_so3


def compute_ee_delta_6d(
    pose_world: np.ndarray,                            # (T, 6) xyz + rotvec
    *, basis: Literal["body_frame_t", "world", "base"]
) -> np.ndarray:
    """Spec §2.2 closed-form ee_delta_6d.  Last frame padded with zeros."""
    T = pose_world.shape[0]
    out = np.zeros((T, 6), dtype=np.float64)
    if T <= 1:
        return out
    p = pose_world[:, :3]
    r = pose_world[:, 3:6]
    for t in range(T - 1):
        R_t = exp_so3(r[t])
        R_tp1 = exp_so3(r[t + 1])
        if basis == "body_frame_t":
            dp = R_t.T @ (p[t + 1] - p[t])
            dR = R_t.T @ R_tp1
        elif basis in ("world", "base"):
            dp = p[t + 1] - p[t]
            dR = R_tp1 @ R_t.T
        else:
            raise ValueError(f"unknown basis: {basis!r}")
        dr = log_so3(dR)
        out[t, :3] = dp
        out[t, 3:6] = dr
    return out


def compute_gripper_delta(g: np.ndarray) -> np.ndarray:
    """Frame-to-frame gripper delta with zero-padded last frame."""
    if g.size == 0:
        return np.zeros_like(g)
    out = np.zeros_like(g)
    out[:-1] = np.diff(g)
    return out


@dataclass(frozen=True)
class CanonicalEpisode:
    # Identity
    episode_index: int
    episode_id: str
    fps: float
    num_frames: int
    # Per-frame canonical (T-aligned, float32 in stored form, float64 internally OK)
    ee_pose_world: np.ndarray            # (T, 6) xyz + rotvec
    ee_delta_6d: np.ndarray              # (T, 6) per profile.canonical.delta_basis
    gripper_normalized: np.ndarray       # (T,)
    gripper_delta: np.ndarray            # (T,)
    # Per-frame raw (optional)
    raw_action: np.ndarray | None
    raw_action_columns: tuple[str, ...] | None
    # Per-segment from mimicanno
    segments: tuple                      # tuple[SubtaskSegment, ...]; will be SubtaskSegment after schema imports
    # Provenance
    run_hash: str
    config_hash: str
    input_hash: str
    label_version: str
    pipeline_phase: int
    mimicanno_version: str
    generated_at: str
    pipeline_status: object              # PipelineStatus (parent §4.3); concrete type imported in builder
```

- [ ] **Step 4: Run tests. All pass. mypy + ruff clean.**

- [ ] **Step 5: Commit**: `feat(phase5/exports/canonical): ee_delta_6d / gripper_delta math + CanonicalEpisode skeleton`

---

### Task 8: SubtaskSegment.from_row helper for sidecar reconstruction

**Files:**
- Modify: `mimicanno/schema.py` — add `SubtaskSegment.from_row` classmethod (lossless inverse of `to_dict` for the sidecar columns; per spec §3.3 boundary per_source_scores are accepted lossy)
- Test: `tests/schema/test_subtask_segment_from_row.py`

**Steps:**

- [ ] **Step 1: Write failing test** that round-trips a SubtaskSegment via to_dict → flat_row (mimicking sidecar) → from_row.

```python
# tests/schema/test_subtask_segment_from_row.py
from mimicanno.schema import SubtaskSegment

def test_round_trip_minimal_segment():
    seg = SubtaskSegment.unlabeled(
        segment_id="ep0_seg0", start_frame=0, end_frame=10,
        start_time=0.0, end_time=1.0, label_version="manipulation.v1",
    )
    row = seg.to_sidecar_row()
    assert row["phase"] == "unlabeled"
    seg2 = SubtaskSegment.from_row(row)
    assert seg2.phase == seg.phase
    assert seg2.start_frame == 0
    assert seg2.end_frame == 10
    assert seg2.failure_flags == []

# Add 2 more tests covering full-Phase-4 segment (with smoothing_ops, vlm_confidence, reviewed=True)
# and a segment with failure_flags + object_track_ids populated.
```

- [ ] **Step 2: Confirm failure.**

- [ ] **Step 3: Implement** `to_sidecar_row()` and `from_row()` on `SubtaskSegment`. Map each spec §3.1 column. For BoundaryRef, store `start_boundary.score` as `boundary_confidence` (already derived per §3.1 update — `min(start, end)`); store `start_boundary.sources` as `boundary_source_start` list. On reconstruction, build a `BoundaryRef` with `score=boundary_confidence` and the source list, leaving `per_source_scores` empty (documented lossy).

- [ ] **Step 4: Run tests, all pass.**

- [ ] **Step 5: Commit**: `feat(schema): SubtaskSegment.to_sidecar_row + from_row for Phase 5 round-trip`

---

### Task 9: build_canonical_episode integrator

**Files:**
- **Modify (sub-step 0): `mimicanno/io.py`** — add `read_annotation_result(path: Path) -> AnnotationResult` and `read_manifest(path: Path) -> Manifest` JSON loaders. They do not exist yet (Task 0 confirmed). They should validate against the existing JSON schemas (`annotation.schema.json`, `manifest.schema.json`) and return typed dataclasses. Add tests in `tests/io/test_read_annotation_manifest.py` (3-4 tests covering happy path + schema-violation rejection).
- Modify: `mimicanno/exports/canonical.py` — add `build_canonical_episode`
- Create: `mimicanno/exports/dataset_layout.py` — episode-path resolution from `meta/info.json`
- Test: `tests/exports/test_build_canonical.py`
- Test: `tests/exports/test_dataset_layout.py`
- Test: `tests/io/test_read_annotation_manifest.py` (new — Step 0 sub-step)

**Steps:**

- [ ] **Step 0: Implement JSON loaders in `mimicanno/io.py` first** (TDD: write tests for the loaders, confirm fail, implement, pass, commit as a separate `feat(io): read_annotation_result + read_manifest JSON loaders` commit before continuing).

- [ ] **Step 1: Write failing test for `dataset_layout`** (resolve `(dataset_root, episode_index) → (parquet_path, row_filter)`):

```python
# tests/exports/test_dataset_layout.py
import json
from pathlib import Path
from mimicanno.exports.dataset_layout import (
    enumerate_episodes, resolve_episode_path,
)

def _write_info(p: Path, data_path: str, total_episodes: int):
    p.mkdir(parents=True, exist_ok=True)
    (p / "info.json").write_text(json.dumps({
        "codebase_version": "v3.0",
        "total_episodes": total_episodes,
        "chunks_size": 1000,
        "data_path": data_path,
        "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/episode_{episode_index:06d}.mp4",
        "fps": 30,
        "splits": {"train": f"0:{total_episodes}"},
        "features": {},
    }))

def test_enumerate_episodes_v3(tmp_path):
    _write_info(tmp_path / "meta", "data/chunk-{chunk_index:03d}/episode_{episode_index:06d}.parquet", 5)
    eps = enumerate_episodes(tmp_path)
    assert eps == list(range(5))

def test_resolve_episode_path_v3(tmp_path):
    _write_info(tmp_path / "meta", "data/chunk-{chunk_index:03d}/episode_{episode_index:06d}.parquet", 5)
    path, row_filter = resolve_episode_path(tmp_path, episode_index=2, chunks_size=1000)
    assert path == tmp_path / "data/chunk-000/episode_000002.parquet"
    assert row_filter is None

def test_resolve_episode_path_v2_combined_file(tmp_path):
    # v2 layout: file-NNN.parquet contains multiple episodes; row_filter selects.
    _write_info(tmp_path / "meta", "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet", 3)
    path, row_filter = resolve_episode_path(tmp_path, episode_index=1, chunks_size=1000)
    assert path == tmp_path / "data/chunk-000/file-000.parquet"
    assert row_filter == {"column": "episode_index", "value": 1}
```

- [ ] **Step 2: Confirm failure.**

- [ ] **Step 3: Implement `mimicanno/exports/dataset_layout.py`.** Read `meta/info.json`, parse `data_path` template, format with `{episode_index, chunk_index, file_index}` substitutions. v2 detection: template contains `{file_index:` instead of `{episode_index:`. Return path + optional row filter dict.

- [ ] **Step 4: Write failing test for `build_canonical_episode`.** Use the mini fixture (Task 14 will create it; for now use a synthetic in-memory parquet via pyarrow):

```python
# tests/exports/test_build_canonical.py
# Synthetic fixture: 3-frame "so101" episode + a synthetic AnnotationResult.
# Verifies build_canonical_episode produces correct ee_pose_world / ee_delta_6d / gripper / segments / provenance.
# Also tests EXPORT_FRAME_COUNT_MISMATCH and EXPORT_RAW_ACTION_MISSING error paths.
```

(Test file is ~80 lines; full implementation provided during execution. Key assertions: `ee_pose_world.shape == (T, 6)`, rotvec data preserved when SO101-style adapter, gripper normalized to [0, 1] via `gripper_scale_min/max`, raw_action populated when `pass_through_raw_action=true`, frame_count mismatch raises right code.)

- [ ] **Step 5: Implement `build_canonical_episode`** per spec §2.3. Steps 1-10 from the spec. Use existing `mimicanno.io_parquet.load_episode_parquet`, existing adapter dispatch logic (extracted from `pipeline._select_adapter`), existing `mimicanno.io.read_annotation_result` / `read_manifest` (or implement if missing — they may not exist yet; use the existing JSON loaders). Convert quat→rotvec via `quat_to_rotvec` if adapter returns (T, 7); pass through if (T, 6).

- [ ] **Step 6: All tests pass. mypy --strict + ruff clean. Commit**: `feat(phase5/exports/canonical): build_canonical_episode + dataset_layout helpers`

---

## Phase C — Sink writer (Tasks 10–16)

### Task 10: SinkWriter protocol + LeRobotV3SinkWriter skeleton

**Files:**
- Create: `mimicanno/exports/sink_base.py` — `SinkWriter` Protocol
- Create: `mimicanno/exports/sink_lerobot_v3.py` — empty class implementing the Protocol
- Test: `tests/exports/test_sink_base.py`

**Steps:**

- [ ] **Step 1: Failing test** that `LeRobotV3SinkWriter` implements the Protocol and exposes `write_all(out_dir, episodes, profile) -> None`.

- [ ] **Step 2: Confirm failure.**

- [ ] **Step 3: Implement Protocol + skeleton class. `write_all` raises NotImplementedError for now.**

- [ ] **Step 4: Pass + mypy clean.**

- [ ] **Step 5: Commit**: `feat(phase5/exports): SinkWriter protocol + LeRobotV3SinkWriter skeleton`

---

### Task 11: Sidecar parquet writer (`meta/mimicanno_segments.parquet`)

**Files:**
- Modify: `mimicanno/exports/sink_lerobot_v3.py` — add `_write_sidecar`
- Test: `tests/exports/test_sink_sidecar.py`

**Steps:**

- [ ] **Step 1: Failing test** building 2 mock CanonicalEpisode instances, calling `_write_sidecar(out, episodes)`, then reading back `meta/mimicanno_segments.parquet` and asserting:
  - row count = sum of segments across episodes
  - rows sorted by `(episode_index, segment_index)`
  - all 31 columns from spec §3.1 present, with correct Arrow types
  - sample row values match input

- [ ] **Step 2: Confirm failure.**

- [ ] **Step 3: Implement** `_write_sidecar`. Use pyarrow `Table.from_pylist` with explicit schema. Atomic write via `mimicanno.writers.atomic_write_parquet` (existing helper) — confirm it exists; if not, write via `.tmp.<pid>` + `os.replace`.

- [ ] **Step 4: Pass + mypy.**

- [ ] **Step 5: Commit**: `feat(phase5/sink): sidecar parquet writer (meta/mimicanno_segments.parquet)`

---

### Task 12: Subtasks registry writer (`meta/subtasks.parquet`)

**Files:**
- Modify: `mimicanno/exports/sink_lerobot_v3.py` — add `_write_subtasks_registry` returning `dict[phase_name → subtask_index]`
- Test: `tests/exports/test_sink_subtasks_registry.py`

**Steps:**

- [ ] **Step 1: Failing test** verifying:
  - rows = first-appearance order across all episodes' segments
  - includes reserved phases (`unlabeled`, `unknown`) when they appear OR when needed for gap-filling (mark gap-filling as a separate boolean param)
  - returns mapping `{phase_name → subtask_index}` with stable indices
  - schema mirrors `tasks.parquet` (`subtask: string`, `subtask_index: int64`, `description: string`)

- [ ] **Step 2: Confirm failure.**

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Pass + mypy. Commit**: `feat(phase5/sink): subtasks.parquet global registry writer`

---

### Task 13: Per-frame data parquet writer (subtask_index + extras)

**Files:**
- Modify: `mimicanno/exports/sink_lerobot_v3.py` — add `_write_data_parquet` per episode
- Test: `tests/exports/test_sink_data_parquet.py`

**Steps:**

- [ ] **Step 1: Failing tests** covering:
  - source columns preserved byte-for-byte
  - new `subtask_index` column added with correct values per spec §4.1 (closed-closed inclusive frame ranges, no `0`-padding for gaps — gap frames get the `unlabeled` index)
  - `extra_per_frame_columns` written with profile-specified names and dtypes
  - bare-prefix collision (existing `subtask_*` columns when `annotation_prefix=null`) raises `EXPORT_SINK_VALIDATION_FAILED` (spec §4.3 added rule)

- [ ] **Step 2: Confirm failure.**

- [ ] **Step 3: Implement.** Read source parquet via `pq.read_table(path)`, build new columns as Arrow arrays, concat (preserving order), atomic write to OUT path.

- [ ] **Step 4: Pass + mypy. Commit**: `feat(phase5/sink): data parquet writer with subtask_index + extras`

---

### Task 14: Per-episode list-column writer (`meta/episodes/<chunk>/file-NNN.parquet`)

**Files:**
- Modify: `mimicanno/exports/sink_lerobot_v3.py` — add `_write_episodes_metadata`
- Test: `tests/exports/test_sink_episodes_metadata.py`

**Steps:**

- [ ] **Step 1: Failing tests** covering:
  - source `meta/episodes/<chunk>/file-NNN.parquet` rows preserved
  - 3 list columns added with correct prefix (`mimicanno_subtask_names`/`_start_frames`/`_end_frames`) when `annotation_prefix=mimicanno`
  - bare names when prefix is null
  - inclusive frame ranges
  - row order matches source (keyed by `episode_index`)

- [ ] **Step 2: Confirm failure.**

- [ ] **Step 3: Implement.** Read source episodes parquet, group by chunk file, append list columns, write atomically.

- [ ] **Step 4: Pass + mypy. Commit**: `feat(phase5/sink): per-episode list columns writer`

---

### Task 15: info.json features merger

**Files:**
- Modify: `mimicanno/exports/sink_lerobot_v3.py` — add `_write_info_json`
- Test: `tests/exports/test_sink_info_json.py`

**Steps:**

- [ ] **Step 1: Failing test** covering:
  - source `info.json` keys preserved verbatim except `features`
  - `features` gets new entries: `subtask_index` (int64 shape [1]), each `extra_per_frame_column.name` (dtype + shape per profile)
  - existing `features` entries untouched
  - JSON serialization indented with 2 spaces (LeRobot convention)

- [ ] **Step 2: Confirm failure.**

- [ ] **Step 3: Implement.** Atomic write via `mimicanno.io.write_json_atomic` (existing).

- [ ] **Step 4: Pass + mypy. Commit**: `feat(phase5/sink): info.json features merger`

---

### Task 16: LeRobotV3SinkWriter.write_all integrator + post-write validation

**Files:**
- Modify: `mimicanno/exports/sink_lerobot_v3.py` — implement `write_all` calling all sub-writers in order
- Add: `_validate_output(out_dir)` — re-reads all written parquets and asserts schemas match expectations; raise `EXPORT_SINK_VALIDATION_FAILED` on mismatch
- Test: `tests/exports/test_sink_writer_integration.py`

**Steps:**

- [ ] **Step 1: Failing test** that calls `LeRobotV3SinkWriter().write_all(...)` end-to-end with 2 mock CanonicalEpisodes against an empty target dir + a fake source dataset, then checks all output files exist with correct shapes.

- [ ] **Step 2: Confirm failure.**

- [ ] **Step 3: Implement** the integrator. Order: subtasks_registry first (to get index map) → data parquets per episode → episodes metadata → info.json → sidecar. Each call atomic individually; integrator does not own transaction-level atomicity (that's the output_layout module).

- [ ] **Step 4: Pass + mypy. Commit**: `feat(phase5/sink): LeRobotV3SinkWriter.write_all + post-write validation`

---

## Phase D — Output destination (Tasks 17–19)

### Task 17: output_layout module (symlink/copy/in_place + atomic publish)

**Files:**
- Create: `mimicanno/exports/output_layout.py`
- Test: `tests/exports/test_output_layout.py`

**Steps:**

- [ ] **Step 1: Failing tests** covering:
  - `prepare_layout(mode="symlink", source, out)` creates `out.tmp.<pid>/` with relative symlink to `source/videos/`
  - `prepare_layout(mode="copy", ...)` deep-copies videos
  - `prepare_layout(mode="in_place", source, ...)` returns the source path (writes go to `<source>/.tmp.<pid>/` per file) and creates `<source>/.mimicanno-backup-<ISO>/` with full backup of files that the export will write
  - `finalize(mode, ..., success=True)` `os.replace`'s `.tmp.<pid>` to final or commits per-file in-place renames; `success=False` leaves `.tmp.<pid>` for inspection
  - `--in-place` without `--yes-i-mean-it` raises `EXPORT_INPLACE_NO_CONFIRM`

- [ ] **Step 2: Confirm failure.**

- [ ] **Step 3: Implement.** Two transaction strategies (clean OUT atomic; in-place per-file). Backup creation per spec §7.3 (back up everything export will touch). All writes via `mimicanno.writers` `.tmp.<pid>` pattern.

- [ ] **Step 4: Pass + mypy. Commit**: `feat(phase5/exports): output_layout (symlink|copy|in_place + atomic publish)`

---

### Task 18: meta/* verbatim copier (tasks.parquet, stats.parquet, etc.)

**Files:**
- Modify: `mimicanno/exports/output_layout.py` — add `copy_meta_verbatim(source, out, exclusions)`
- Test: `tests/exports/test_meta_verbatim_copy.py`

**Steps:**

- [ ] **Step 1: Failing test** verifying that everything in `<source>/meta/` except listed exclusions (`subtasks.parquet`, `mimicanno_segments.parquet`, `info.json`, `episodes/`) is copied byte-for-byte to `<out>/meta/`.

- [ ] **Step 2-5:** Implement, test, commit as `feat(phase5/exports): copy_meta_verbatim helper`

---

### Task 19: in_place backup loop + restore-direction docs (no restore tool yet)

**Files:**
- Modify: `mimicanno/exports/output_layout.py` — add `create_inplace_backup(source, files_to_back_up)` returning backup_dir
- Test: `tests/exports/test_inplace_backup.py`

**Steps:**

- [ ] **Step 1: Failing test** verifying that:
  - backup dir is `<source>/.mimicanno-backup-<ISO>/` with current timestamp
  - all files passed in `files_to_back_up` exist as verbatim copies in backup dir at their relative path
  - backup creation happens BEFORE any in-place write
  - second invocation creates a new dated backup dir (does not overwrite)
  - if any backup copy fails, raises `EXPORT_INPLACE_BACKUP_FAILED` and creates no backup dir at all

- [ ] **Step 2-5:** Implement, test, commit as `feat(phase5/exports): in-place backup loop`

---

## Phase E — Bulk orchestrator (Tasks 20–23)

### Task 20: Run resolution (find canonical_name per episode_index)

**Files:**
- Create: `mimicanno/exports/run_resolution.py`
- Test: `tests/exports/test_run_resolution.py`

**Steps:**

- [ ] **Step 1: Failing test** with synthetic `runs/` directory containing multiple `<canonical>/` for different episode_index / target_phase / config_hash. Verify:
  - `resolve_runs(runs_root, episode_indices, target_phase, config_hash=None)` returns `dict[int → str]` (canonical_name)
  - Multiple matches with no `config_hash` filter → raises `EXPORT_RUN_AMBIGUOUS` with candidate list in error JSON
  - Zero matches → raises `EXPORT_RUN_NOT_FOUND` (or warns + skips with `--skip-missing`)
  - Filter by `config_hash` narrows correctly
  - Explicit `--run` list bypasses target_phase filter and just validates existence

- [ ] **Step 2: Confirm failure.**

- [ ] **Step 3: Implement.** Use existing `mimicanno.runindex.read_index()` (returns rows with `canonical_name`, `episode_id`, `config_hash`, `target_phase`, `run_hash` etc.), filter the rows in `run_resolution.py` (do not extend `runindex.py` — Task 0 confirmed there's no pre-existing `find_runs_for_episode` helper). Return `dict[episode_index → canonical_name]`.

- [ ] **Step 4: Pass + mypy. Commit**: `feat(phase5/exports): run_resolution (canonical_name per episode)`

---

### Task 21: Provenance manifest writer (`.mimicanno-export.json`)

**Files:**
- Create: `mimicanno/exports/provenance.py`
- Test: `tests/exports/test_provenance.py`

**Steps:**

- [ ] **Step 1: Failing test** validating `write_export_manifest(out, profile, runs_used, source_dataset, target_phase, config_hash_filter, output_mode, mimicanno_version, generated_at, cli_args)` produces a `.mimicanno-export.json` matching `export_manifest.schema.json` with exactly the spec §8 fields.

- [ ] **Step 2-5:** Implement, test, commit as `feat(phase5/exports): provenance manifest writer`

---

### Task 22: Bulk export orchestrator + idempotency reuse short-circuit

**Files:**
- Create: `mimicanno/exports/bulk.py`
- Test: `tests/exports/test_bulk.py` (will use mini fixture from Task 24 once it lands; for now stub fixtures inline)

**Steps:**

- [ ] **Step 1: Failing test** for `bulk_export(dataset_root, runs_root, target_phase, profile, out, output_mode, ...) -> ExportResult` covering:
  - Happy path: 3 episodes, all resolved, complete pipeline runs end-to-end (using a small synthetic source + synthetic runs)
  - Idempotency: second `bulk_export(...)` with same args is a no-op (reads existing `.mimicanno-export.json`, matches profile_hash + runs_used, exits 0 with original `generated_at`)
  - `--force` re-runs even on match
  - Episode count, sidecar path, manifest path returned in `ExportResult`
  - One missing run + `--skip-missing=True` warns + excludes that episode

- [ ] **Step 2: Confirm failure.**

- [ ] **Step 3: Implement** the orchestrator per spec §1.1 pipeline. Sequence: load profile → enumerate episodes → resolve runs → idempotency check → prepare layout → for each episode (load annotation+manifest, build canonical) → sink_writer.write_all → write export manifest → finalize layout.

- [ ] **Step 4: Pass + mypy. Commit**: `feat(phase5/exports): bulk_export orchestrator + idempotency`

---

### Task 23: mimicanno.export() programmatic API

**Files:**
- Modify: `mimicanno/__init__.py` — export `export` callable
- Test: `tests/exports/test_programmatic_api.py`

**Steps:**

- [ ] **Step 1: Failing test** importing `from mimicanno import export` and calling it directly.

- [ ] **Step 2-5:** Wire up, test, commit as `feat(mimicanno): expose `export()` programmatic API`

---

## Phase F — CLI (Tasks 24–25)

### Task 24: Mini fixture dataset + build script

**Files:**
- Create: `tests/exports/fixtures/build_mini_so101.py` — generates `tests/exports/fixtures/mini_so101/` from scratch with deterministic synthetic data
- Create: `tests/exports/fixtures/mini_so101/` — checked-in artifacts produced by the build script
- Create: `tests/exports/fixtures/mini_runs/` — corresponding mimicanno run dirs (Phase 4 annotation.json + manifest.json + boundaries.json + signals.json) for each episode
- Create: `tests/exports/fixtures/build_mini_runs.py` — generates mini_runs from synthetic AnnotationResult dataclasses
- Test: `tests/exports/test_fixtures.py`

**Steps:**

- [ ] **Step 1: Failing test** verifying that `mini_so101/` is a valid LeRobot v3 dataset (3 episodes, ~20 frames each, all required columns present) and that `mini_runs/` contains valid Phase 4 run dirs for those 3 episodes.

- [ ] **Step 2: Confirm failure.**

- [ ] **Step 3: Implement** both build scripts. Use deterministic synthetic data — random seeded, EE pose follows a known trajectory, gripper opens/closes at known frames so segments align. Run each build script, commit the generated artifacts.

- [ ] **Step 4: Pass. Commit**: `test(phase5/fixtures): mini_so101 dataset + mini_runs Phase 4 artifacts (~50 KB total)`

---

### Task 25: CLI `export` subcommand

**Files:**
- Modify: `mimicanno/cli.py` — add `export` Typer command with all spec §6 flags
- Test: `tests/exports/test_cli_export.py`

**Steps:**

- [ ] **Step 1: Failing tests** invoking the CLI as a subprocess against the mini fixture:
  - `mimicanno export --dataset <mini_so101> --runs-root <mini_runs> --target-phase 4 --profile so101_sarm --out <tmp>` exits 0
  - `--dry-run` produces machine-readable JSON on stdout matching spec §6.1 shape
  - `--in-place` without `--yes-i-mean-it` exits 2 with `EXPORT_INPLACE_NO_CONFIRM`
  - `--force` replaces existing OUT
  - Mutually exclusive output mode flags rejected at parse time
  - Each gate flag (`--require-reviewed`, `--allow-degraded`, etc.) is wired and effective

- [ ] **Step 2: Confirm failure.**

- [ ] **Step 3: Implement.** Use Typer (existing CLI uses Typer). Parse args, validate exclusivity, call `mimicanno.export(...)`, print summary JSON, exit 0/1/2 appropriately.

- [ ] **Step 4: Pass + mypy + ruff. Commit**: `feat(cli): mimicanno export subcommand`

---

## Phase G — Round-trip + error-path tests (Tasks 26–28)

### Task 26: RT-1 label round-trip test

**Files:**
- Test: `tests/exports/test_roundtrip_label.py`

**Steps:**

- [ ] **Step 1:** Read three fixture `annotation.json` files (Phase 1, 3, 4) from `mini_runs/`, run full export, read sidecar parquet + subtasks parquet, reconstruct `list[SubtaskSegment]` via `SubtaskSegment.from_row`, assert equality on all fields except documented lossy ones (per_source_scores).

- [ ] **Step 2-5:** Implement test, run, fix any field-mapping mistakes in Tasks 8 / 11. Commit: `test(phase5): RT-1 label round-trip`

---

### Task 27: RT-2 action round-trip test

**Files:**
- Test: `tests/exports/test_roundtrip_action.py`

**Steps:**

- [ ] **Step 1:** Build a synthetic CanonicalEpisode with known arrays, write via sink, read back via pyarrow, reconstruct CanonicalEpisode, `np.allclose(orig, reconstructed, atol=1e-6, rtol=1e-5)` on `ee_delta_6d`, `gripper_normalized`, `gripper_delta`. Test all three `delta_basis` modes.

- [ ] **Step 2-5:** Implement, run, commit: `test(phase5): RT-2 action round-trip across all delta_basis modes`

---

### Task 28: Error-path tests (one per EXPORT_* code)

**Files:**
- Test: `tests/exports/test_errors.py`

**Steps:**

- [ ] **Step 1:** One test function per code (18 total). Each constructs the failure condition (corrupt YAML, missing dataset, ambiguous runs, etc.) and asserts the right `error_code` raises with the right exit + stderr JSON.

- [ ] **Step 2-5:** Implement, run, commit: `test(phase5): error-path tests for all 18 EXPORT_* codes`

---

## Phase H — Real-data smoke verification (Tasks 29–31)

### Task 29: Full pytest + mypy + ruff regression check

- [ ] **Step 1:** `cd ~/MimicAnno-worktrees/phase5-export-impl && uv run pytest -q`. Expect 668 + ≥ 50 new tests pass.
- [ ] **Step 2:** `uv run mypy --strict mimicanno/`. Expect clean.
- [ ] **Step 3:** `uv run ruff check mimicanno/`. Expect clean.
- [ ] **Step 4:** If any fail, fix root cause (do not silence). Commit fixes individually with descriptive messages.

---

### Task 30: SO101 real-data run

This is the smoke check that the user's autonomous-mode directive depends on.

**Steps:**

- [ ] **Step 1: Verify prerequisites.** Confirm `~/MimicRec/datasets/SO101/` exists with episodes, and that mimicanno can run Phase 4 on at least 1 SO101 episode. If no Phase 4 run dir exists, run:

```bash
cd ~/MimicAnno-worktrees/phase5-export-impl
uv run mimicanno annotate \
    --video ~/MimicRec/datasets/SO101/videos/observation.images.front/chunk-000/episode_000000.mp4 \
    --parquet ~/MimicRec/datasets/SO101/data/chunk-000/episode_000000.parquet \
    --task "Put the tape into the bottle" \
    --robot generic \
    --robot-config tests/exports/fixtures/so101_robot_config.yaml \
    --target-phase 4 \
    --runs-root ./runs
```

(Need to create `tests/exports/fixtures/so101_robot_config.yaml` — a `generic` adapter config matching SO101's column layout — as a sub-step.)

If Phase 4 fails on real SO101 (e.g. column mismatch in GenericAdapter v0.2.0), patch the adapter or robot config and re-run. Capture the failure mode in a follow-up commit.

- [ ] **Step 2: Run export.**

```bash
uv run mimicanno export \
    --dataset ~/MimicRec/datasets/SO101 \
    --runs-root ./runs \
    --target-phase 4 \
    --profile so101_sarm \
    --out /tmp/SO101_annotated_phase5_smoke
```

Expect: exit 0, summary JSON on stdout listing episodes processed.

- [ ] **Step 3: Inspect output structure.**

```bash
ls /tmp/SO101_annotated_phase5_smoke/{data,meta,videos}
ls /tmp/SO101_annotated_phase5_smoke/meta/
cat /tmp/SO101_annotated_phase5_smoke/.mimicanno-export.json
uv run python -c "
import pyarrow.parquet as pq
sub = pq.read_table('/tmp/SO101_annotated_phase5_smoke/meta/subtasks.parquet')
print('subtasks:', sub.column_names, sub.num_rows)
print('rows:', sub.to_pylist())
ep0 = pq.read_table('/tmp/SO101_annotated_phase5_smoke/data/chunk-000/episode_000000.parquet')
print('episode 0 cols:', ep0.column_names)
print('subtask_index distribution:', set(ep0.column('subtask_index').to_pylist()))
seg = pq.read_table('/tmp/SO101_annotated_phase5_smoke/meta/mimicanno_segments.parquet')
print('sidecar segments:', seg.num_rows)
print('phases used:', set(seg.column('phase').to_pylist()))
"
```

Sanity check: subtasks list should contain a few of the allowed labels (`grasp_object`, `lift_object`, `place_object`, etc.) and possibly `unlabeled`. `subtask_index` distribution should show ≥ 2 distinct values (episode is non-trivial).

- [ ] **Step 4: Run SARM consumer smoke test.**

```bash
uv run python -c "
import sys
sys.path.insert(0, '/home/takakimaeda/MimicRec/lerobot/src')
import pandas as pd
ep_df = pd.read_parquet('/tmp/SO101_annotated_phase5_smoke/meta/episodes/chunk-000/file-000.parquet')
print('episode columns:', list(ep_df.columns))
assert 'mimicanno_subtask_names' in ep_df.columns
assert 'mimicanno_subtask_start_frames' in ep_df.columns
assert 'mimicanno_subtask_end_frames' in ep_df.columns
row = ep_df.iloc[0]
print('episode 0 subtask names:', list(row['mimicanno_subtask_names']))
print('episode 0 start frames:', list(row['mimicanno_subtask_start_frames']))
print('episode 0 end frames:', list(row['mimicanno_subtask_end_frames']))
"
```

Verifies SARM `_load_episode_annotations(annotation_type='mimicanno')` would find the columns.

- [ ] **Step 5: Subjective sanity** — does the labeling look reasonable? Pull up the segments sidecar and check phase order makes sense for "Put the tape into the bottle":

```bash
uv run python -c "
import pyarrow.parquet as pq
seg = pq.read_table('/tmp/SO101_annotated_phase5_smoke/meta/mimicanno_segments.parquet')
df = seg.to_pandas().sort_values(['episode_index','segment_index'])
for _, row in df.iterrows():
    print(f'  ep{row.episode_index} seg{row.segment_index:2d} '
          f'[{row.start_frame:3d}..{row.end_frame:3d}] '
          f'{row.phase:20s} conf={row.overall_confidence:.2f}')
"
```

Expected: a sequence like `idle → approach_object → align_gripper → grasp_object → lift_object → move_to_target → place_object → release_object → retreat`. Some `unlabeled` is OK if Phase 1-4 left some segments unlabeled. Garbage (e.g. all `unlabeled`, or random alternation between phases) means upstream Phase 4 / labeling has issues, not export issues.

- [ ] **Step 6: Idempotency check** — re-run the same `mimicanno export` command. Expect log "existing export matches current request; no-op", exit 0, no file mtime changes.

- [ ] **Step 7: Document result in commit.** Either:
  - "Real-data smoke pass: 1 episode of SO101 exported, sidecar contains N segments spanning {phases}, SARM-readable episodes parquet confirmed." (success path)
  - Or: open issue describing what failed and commit a draft fix.

Commit: `verify(phase5): SO101 real-data export smoke check`

---

### Task 31: Update memory + summary, prepare for merge

**Files:**
- Update: `~/.claude/projects/-home-takakimaeda-MimicAnno/memory/MEMORY.md` and `phase5_progress.md` (new memory file)
- Optional: tag the commit for review

**Steps:**

- [ ] **Step 1: Run full final suite once more** (`uv run pytest -q`, mypy, ruff, smoke from Task 30).

- [ ] **Step 2: Write `phase5_progress.md`** memory note: status (export sub-project complete; real-data smoke pass on SO101), HEAD commit on `phase5-export-impl`, what's still open (other Phase 5 sub-projects: A/B/D/E).

- [ ] **Step 3: Add `MEMORY.md` entry pointing to it.**

- [ ] **Step 4: Push the branch:** `git push -u origin phase5-export-impl`

- [ ] **Step 5: Hand back to user** with a summary. Per CLAUDE.md autonomy-window exit criteria: write a short report stating what shipped, what looked off (if anything), open questions. Suggest the user review the branch / PR before merge.

---

## Estimated effort

- Phase A (foundation): ~3-4 hours
- Phase B (canonical IR + math): ~3-4 hours
- Phase C (sink writer): ~5-6 hours
- Phase D (output destination): ~2-3 hours
- Phase E (bulk orchestrator): ~3-4 hours
- Phase F (fixtures + CLI): ~3-4 hours
- Phase G (round-trip + error tests): ~2-3 hours
- Phase H (real-data verify): ~1-2 hours

Total: 22-30 hours of focused work for an experienced engineer; expect more if SO101 real-data shows adapter/data issues.

## Open dependencies / risks

- **GenericAdapter schema bump** (Task 4) is technically a public-API change. Existing Phase 1-4 consumers using `0.1.0` YAML must keep working — Task 4's third test pins this contract.
- **scipy** is already a Phase 1 dependency, no new dep added.
- **SO101 column scaling** for gripper (`0..100` assumption in Task 3 default profile) is a guess — Task 30 step 1 will validate empirically. If the actual range differs, update the profile.
- **runs/index.json schema** assumed stable across phases. If it ever changes, run_resolution (Task 20) needs adjusting; this should already be solid given Phase 1-4 reliance on it.
- **Phase 4 on SO101 may not yet have been run successfully** by the user. Task 30 step 1 includes a fallback to run Phase 4 first if no run exists; that path may surface SO101-specific Phase 1-4 bugs that need fixing before export can be smoke-checked.
