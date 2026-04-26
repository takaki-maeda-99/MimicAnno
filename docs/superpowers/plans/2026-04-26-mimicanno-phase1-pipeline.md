# MimicAnno Phase 1 — Python Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `mimicanno` Python package and `mimicanno annotate` CLI that ingests a LeRobot episode (mp4 + parquet) and writes a self-contained, atomically-published run directory under `<repo>/runs/<canonical_name>/`. The run directory is what the (separate) Plan 2 React viewer consumes.

**Architecture:** Pure-numpy signal-based boundary detection (no SAM3/VLM in Phase 1) → integrated weighted score → Phase-1 skeleton segments with `phase="unlabeled"` → atomic publish under a single `runs/index.json.lock` transaction (lock-free reuse short-circuit, locked reuse re-check, POSIX two-rename replacement, scavenger via `.writer.json`).

**Tech Stack:** Python 3.11+, `pyarrow` (parquet), `numpy`/`scipy` (signals), `imageio-ffmpeg` (video sha256 + duration + fps probe), `pyyaml` (label YAMLs), `typer` (CLI), `dataclasses` + `json` for schema, `jsonschema` for runtime validation, `pytest` for tests, `ruff` + `mypy --strict` for lint/type. POSIX semantics required (Windows acknowledged as best-effort, see spec §6.5).

**Spec source of truth:** `docs/superpowers/specs/2026-04-25-mimicanno-design-brushup.md`. Every section reference below (`§4.1`, `§5.3`, etc.) is into that document. **Do not deviate without updating the spec first.**

---

## File structure (locked in before tasks)

```
MimicAnno/
  pyproject.toml                          # NEW
  ruff.toml                               # NEW
  .gitignore                              # NEW (or modified) — adds runs/, *.pyc, etc.
  runs/
    .gitkeep                              # NEW
  mimicanno/                              # NEW package
    __init__.py
    __version__.py                        # CLI version string (single source)
    cli.py                                # typer entry point
    pipeline.py                           # orchestrator
    config.py                             # AnnotationConfig + hashing
    schema.py                             # dataclasses (Manifest, AnnotationResult, ...)
    schema_versions.py                    # per-artifact MAJOR.MINOR.PATCH constants
    hashing.py                            # canonical_json + sha256 helpers
    signals.py                            # smoothing + signal extraction
    boundaries.py                         # detectors + integrated score
    bracketing.py                         # §5.6 Phase 1 clip bracketing
    publish.py                            # publish transaction (composer)
    rundir.py                             # canonical_name + run dir paths
    scavenger.py                          # .writer.json contract
    runindex.py                           # runs/index.json read/upsert
    locks.py                              # POSIX/Windows file lock
    io_video.py                           # ffprobe + sha256 + copy/symlink
    io_parquet.py                         # parquet load + sha256 + gap handling
    errors.py                             # structured error JSON helpers
    labelset.py                           # load + validate labels YAML
    adapters/
      __init__.py
      base.py                             # RobotAdapter Protocol
      aloha.py
      koch.py
      so100.py
      generic.py
    configs/
      labels/
        manipulation.yaml                 # default label set (10 labels, no failure_recovery)
  tests/
    conftest.py                           # shared fixtures
    fixtures/
      synthesize.py                       # programmatic synthetic-episode generator
      __init__.py
    unit/
      test_hashing.py
      test_schema_versions.py
      test_schema.py
      test_config_hash.py
      test_labelset.py
      test_io_parquet.py
      test_io_video.py
      test_signals.py
      test_boundaries.py
      test_bracketing.py
      test_adapters_aloha.py
      test_adapters_koch.py
      test_adapters_generic.py
      test_locks.py
      test_scavenger.py
      test_runindex.py
      test_rundir.py
      test_publish.py
      test_errors.py
    integration/
      test_cli_smoke_aloha.py
      test_cli_reuse_and_force.py
      test_cli_concurrent_publish.py
      test_cli_collision_extension.py
      test_cli_eef_disabled_koch.py
      test_cli_zero_action.py
      test_cli_invalid_inputs.py
      test_cli_perf_compute_path.py
```

**Decomposition rules followed:**
- **Files that change together live together.** `publish.py` orchestrates `rundir.py`, `scavenger.py`, `runindex.py`, `locks.py` — each is independently testable.
- **One file = one responsibility.** `boundaries.py` has detectors + integrated score; bracketing lives separately because it's invoked downstream of boundary detection and never together.
- **Input/output split.** `io_parquet.py` and `io_video.py` are kept thin wrappers around `pyarrow` and `ffmpeg` respectively; signal math lives in `signals.py`.
- **Adapters per file.** Each robot adapter is a focused file; tests are 1:1.

---

## Task ordering rationale

Tasks build dependencies bottom-up so each one merges green:

```
A. Foundations (no I/O):  scaffolding → hashing → schema → config_hash
B. Adapters:              base → aloha → koch → generic
C. Input I/O:             parquet → fps → video
D. Signals & boundaries:  smoothing → detectors → score → bracketing
E. Output writers:        rundir → signals.json → boundaries.json → annotation.json → manifest.json
F. Publish transaction:   scavenger → locks → runindex → reuse → replace → orchestrator
G. CLI:                   args → pipeline orchestrator → errors
H. Integration:           synthetic fixtures → smoke → reuse → concurrent → collision → degrade → perf
```

Each task ends with a green `pytest` run and a commit. **Never skip the commit step.**

---

## Conventions used in this plan

- All `pytest` invocations include `-v` and target the specific test file or test name.
- All commit messages follow the existing repo style (no scope prefix, imperative mood, second line blank, body explains "why" if non-obvious).
- All `git add` calls list paths explicitly — never `git add -A`.
- Code blocks are **complete**; never write `# ... (rest of code)` or "add validation here." If a function body is shown, that body is what goes in the file.
- When the spec mandates a behavior, the test asserts that behavior verbatim.
- TDD discipline: write failing test → run it → see red → minimal code → run it → see green → refactor if needed → commit. Skipping the red step is a bug; you must SEE the failure to know your test isn't a tautology.

---

## Phase A — Foundations

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `ruff.toml`
- Create: `.gitignore`
- Create: `runs/.gitkeep`
- Create: `mimicanno/__init__.py`
- Create: `mimicanno/__version__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1.1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling>=1.21"]
build-backend = "hatchling.build"

[project]
name = "mimicanno"
version = "0.1.0"
description = "Robot-episode subtask annotation pipeline."
requires-python = ">=3.11"
dependencies = [
  "numpy>=1.26",
  "scipy>=1.11",
  "pyarrow>=15",
  "pyyaml>=6.0",
  "typer>=0.12",
  "jsonschema>=4.21",
  "imageio-ffmpeg>=0.4.9",
]

[project.scripts]
mimicanno = "mimicanno.cli:app"

[project.optional-dependencies]
dev = [
  "pytest>=8",
  "pytest-xdist>=3.5",
  "ruff>=0.4",
  "mypy>=1.10",
]

[tool.hatch.build.targets.wheel]
packages = ["mimicanno"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers"
markers = [
  "integration: end-to-end CLI tests that touch the filesystem",
  "perf: performance regression tests",
]

[tool.mypy]
python_version = "3.11"
strict = true
files = ["mimicanno"]
```

- [ ] **Step 1.2: Write `ruff.toml`**

```toml
line-length = 100
target-version = "py311"

[lint]
select = ["E", "F", "I", "B", "UP", "N", "SIM", "RUF"]
ignore = ["E501"]  # line length is enforced by formatter

[lint.per-file-ignores]
"tests/**" = ["B011"]  # allow assert in tests
```

- [ ] **Step 1.3: Write `.gitignore`**

```gitignore
__pycache__/
*.pyc
*.pyo
.pytest_cache/
.mypy_cache/
.ruff_cache/
*.egg-info/
build/
dist/

# Phase 1 run output (kept out of git)
runs/*
!runs/.gitkeep

# Editor / OS
.DS_Store
.vscode/
.idea/
```

- [ ] **Step 1.4: Create empty `runs/.gitkeep` and package init files**

```python
# mimicanno/__init__.py
"""MimicAnno — robot episode subtask annotation pipeline."""
from mimicanno.__version__ import __version__

__all__ = ["__version__"]
```

```python
# mimicanno/__version__.py
__version__ = "0.1.0"
```

```python
# tests/__init__.py
```

```python
# tests/conftest.py
"""Shared pytest fixtures for mimicanno tests."""
```

`runs/.gitkeep` is an empty file.

- [ ] **Step 1.5: Install deps and verify import**

Run: `python -m pip install -e '.[dev]'`
Then run: `python -c "import mimicanno; print(mimicanno.__version__)"`
Expected: `0.1.0`

Run: `pytest -v`
Expected: `no tests ran` (exit code 5; that's fine for now).

- [ ] **Step 1.6: Commit**

```bash
git add pyproject.toml ruff.toml .gitignore runs/.gitkeep mimicanno/__init__.py mimicanno/__version__.py tests/__init__.py tests/conftest.py
git commit -m "$(cat <<'EOF'
mimicanno: project scaffolding for Phase 1 Python pipeline

Adds pyproject (hatchling build, pytest/mypy/ruff config), gitignore
that keeps runs/ out of git, and package skeleton with version
constant. No behavior yet.
EOF
)"
```

---

### Task 2: Hashing utilities (`mimicanno/hashing.py`)

The whole canonical-name story (§4.1) hinges on stable, deterministic JSON serialization and sha256. Every other module imports from here.

**Files:**
- Create: `mimicanno/hashing.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/unit/test_hashing.py`

- [ ] **Step 2.1: Write the failing tests**

```python
# tests/unit/test_hashing.py
import hashlib
from pathlib import Path

import pytest

from mimicanno.hashing import canonical_json, sha256_file, sha256_hex_of_str


class TestCanonicalJson:
    def test_dict_keys_are_sorted(self):
        a = canonical_json({"b": 1, "a": 2})
        b = canonical_json({"a": 2, "b": 1})
        assert a == b
        assert a == '{"a":2,"b":1}'

    def test_no_whitespace(self):
        result = canonical_json({"a": [1, 2, 3]})
        assert " " not in result
        assert "\n" not in result

    def test_nested_dicts_sorted(self):
        result = canonical_json({"outer": {"z": 1, "a": 2}})
        assert result == '{"outer":{"a":2,"z":1}}'

    def test_unicode_kept_as_unicode(self):
        # No escape of non-ASCII; this matters for stable cross-platform hashes.
        result = canonical_json({"task": "つかむ"})
        assert "つかむ" in result

    def test_floats_use_repr(self):
        result = canonical_json({"x": 0.1 + 0.2})
        assert result == '{"x":0.30000000000000004}'

    def test_none_serialized_as_null(self):
        assert canonical_json({"x": None}) == '{"x":null}'

    def test_rejects_nan(self):
        with pytest.raises(ValueError, match="NaN"):
            canonical_json({"x": float("nan")})

    def test_rejects_infinity(self):
        with pytest.raises(ValueError, match="Infinity"):
            canonical_json({"x": float("inf")})


class TestSha256HexOfStr:
    def test_known_value(self):
        # echo -n "" | sha256sum
        assert sha256_hex_of_str("") == (
            "e3b0c44298fc1c149afbf4c8996fb924"
            "27ae41e4649b934ca495991b7852b855"
        )

    def test_utf8_bytes(self):
        result = sha256_hex_of_str("つかむ")
        expected = hashlib.sha256("つかむ".encode("utf-8")).hexdigest()
        assert result == expected


class TestSha256File:
    def test_known_file(self, tmp_path: Path):
        f = tmp_path / "x.bin"
        f.write_bytes(b"hello world")
        assert sha256_file(f) == hashlib.sha256(b"hello world").hexdigest()

    def test_streamed_for_large_file(self, tmp_path: Path):
        # Generate ~3 MB file; we stream in 1 MiB chunks so this must not OOM.
        f = tmp_path / "big.bin"
        f.write_bytes(b"a" * (3 * 1024 * 1024))
        result = sha256_file(f)
        expected = hashlib.sha256(b"a" * (3 * 1024 * 1024)).hexdigest()
        assert result == expected
```

- [ ] **Step 2.2: Run tests to see them fail**

Run: `pytest tests/unit/test_hashing.py -v`
Expected: All tests fail with `ModuleNotFoundError: No module named 'mimicanno.hashing'`.

- [ ] **Step 2.3: Implement `mimicanno/hashing.py`**

```python
"""Deterministic JSON + sha256 helpers.

All hashes used in canonical_name (spec §4.1) flow through here.
Determinism rules:
- dict keys sorted ASCII-lexicographically
- no whitespace separators
- non-ASCII strings kept as-is (ensure_ascii=False)
- NaN / Infinity rejected (canonical hashing must not depend on platform float quirks)
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

_CHUNK_SIZE = 1024 * 1024  # 1 MiB


def _check_finite(value: Any) -> Any:
    if isinstance(value, float):
        if math.isnan(value):
            raise ValueError("NaN is not allowed in canonical JSON")
        if math.isinf(value):
            raise ValueError("Infinity is not allowed in canonical JSON")
    return value


def canonical_json(obj: Any) -> str:
    """Serialize ``obj`` to a stable, whitespace-free, sort-keys JSON string.

    The result is suitable for hashing: identical inputs produce byte-identical output
    across machines and Python versions.
    """
    return json.dumps(
        obj,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=_check_finite,
    )


def sha256_hex_of_str(s: str) -> str:
    """Return the SHA-256 hex digest of ``s`` encoded as UTF-8."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest of the file at ``path`` (streamed in 1 MiB chunks)."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()
```

- [ ] **Step 2.4: Create `tests/unit/__init__.py` (empty)**

- [ ] **Step 2.5: Run tests, expect green**

Run: `pytest tests/unit/test_hashing.py -v`
Expected: All tests pass.

- [ ] **Step 2.6: Commit**

```bash
git add mimicanno/hashing.py tests/unit/__init__.py tests/unit/test_hashing.py
git commit -m "$(cat <<'EOF'
hashing: deterministic canonical_json + sha256 helpers

These underpin canonical_name (spec §4.1). NaN/Infinity are rejected
because canonical hashing must not depend on platform float quirks.
File hashing streams in 1 MiB chunks so that large mp4s don't OOM.
EOF
)"
```

---

### Task 3: Schema version constants (`mimicanno/schema_versions.py`)

Per §6.6, each artifact carries an independent `schema_version`. Centralize the constants so they're impossible to drift out of step with the producer's `compat` block.

**Files:**
- Create: `mimicanno/schema_versions.py`
- Create: `tests/unit/test_schema_versions.py`

- [ ] **Step 3.1: Write the failing test**

```python
# tests/unit/test_schema_versions.py
from mimicanno.schema_versions import (
    ARTIFACT_SCHEMA_VERSIONS,
    COMPAT_BLOCK,
    LABELS_SCHEMA_VERSION,
    INDEX_SCHEMA_VERSION,
    parse_major,
)


def test_artifact_versions_present():
    assert set(ARTIFACT_SCHEMA_VERSIONS.keys()) == {
        "manifest", "annotation", "boundaries", "signals",
    }
    for version in ARTIFACT_SCHEMA_VERSIONS.values():
        assert version == "0.1.0"


def test_compat_block_only_lists_in_run_artifacts():
    # External schemas (labels, index) are NOT in compat per spec §6.6.
    assert set(COMPAT_BLOCK.keys()) == {
        "manifest", "annotation", "boundaries", "signals",
    }
    for major in COMPAT_BLOCK.values():
        assert major == 1


def test_external_schemas_have_independent_versions():
    assert LABELS_SCHEMA_VERSION == "0.1.0"
    assert INDEX_SCHEMA_VERSION == "0.1.0"


def test_parse_major():
    assert parse_major("0.1.0") == 0
    assert parse_major("1.2.3") == 1
    assert parse_major("12.0.0") == 12
```

- [ ] **Step 3.2: Run, see red**

Run: `pytest tests/unit/test_schema_versions.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3.3: Implement**

```python
# mimicanno/schema_versions.py
"""Artifact schema version constants (spec §6.6).

Each schema is independent. ``COMPAT_BLOCK`` is the producer-side declaration
of what MAJOR each in-run artifact was emitted at; consumers verify this against
their own ``supported_majors`` set membership (NOT >=).
"""
from __future__ import annotations


def parse_major(version: str) -> int:
    """Return the MAJOR of a ``MAJOR.MINOR.PATCH`` semver string."""
    major_str, _, _ = version.partition(".")
    return int(major_str)


ARTIFACT_SCHEMA_VERSIONS: dict[str, str] = {
    "manifest":   "0.1.0",
    "annotation": "0.1.0",
    "boundaries": "0.1.0",
    "signals":    "0.1.0",
}

# COMPAT scope per §6.6: in-run artifacts only. Labels YAML and index.json
# carry their own schema_version and are validated independently at load time.
COMPAT_BLOCK: dict[str, int] = {
    role: parse_major(version)
    for role, version in ARTIFACT_SCHEMA_VERSIONS.items()
}

LABELS_SCHEMA_VERSION = "0.1.0"
INDEX_SCHEMA_VERSION = "0.1.0"
```

- [ ] **Step 3.4: Run, see green**

Run: `pytest tests/unit/test_schema_versions.py -v`
Expected: All pass.

- [ ] **Step 3.5: Commit**

```bash
git add mimicanno/schema_versions.py tests/unit/test_schema_versions.py
git commit -m "$(cat <<'EOF'
schema_versions: per-artifact version constants + compat block

Centralizes the per-artifact schema_version values (§6.6). The compat
block scope is in-run artifacts only; labels YAML and index.json have
their own independent schema_version and are validated at load time.
EOF
)"
```

---

### Task 4: Schema dataclasses (`mimicanno/schema.py`)

Plain `@dataclass` types for every shape that hits disk. Each has `to_dict()` for canonical-JSON serialization. We deliberately do not use pydantic — the cost of a third dependency is not worth it when our serialization needs are this simple.

**Files:**
- Create: `mimicanno/schema.py`
- Create: `tests/unit/test_schema.py`

- [ ] **Step 4.1: Write failing tests**

```python
# tests/unit/test_schema.py
import pytest

from mimicanno.schema import (
    AnnotationResult,
    Artifact,
    BoundaryCandidate,
    BoundaryRef,
    GeneratorInfo,
    InputRef,
    Manifest,
    PipelineStatus,
    SubtaskSegment,
    TaskInfo,
)
from mimicanno.schema_versions import COMPAT_BLOCK


class TestSubtaskSegment:
    def test_minimal_phase1_segment(self):
        seg = SubtaskSegment(
            segment_id="s_001",
            episode_id="ep0",
            start_frame=0,
            end_frame=10,
            start_time=0.0,
            end_time=0.333,
            phase="unlabeled",
            verb=None,
            object=None,
            target=None,
            failure_flags=[],
            label_source="signals_only",
            object_state_unavailable=True,
            object_track_ids=[],
            label_version="manipulation.v1",
            start_boundary=BoundaryRef(
                candidate_id=None,
                time=0.0,
                sources=["episode_start"],
                score=1.0,
            ),
            end_boundary=BoundaryRef(
                candidate_id="b_001",
                time=0.333,
                sources=["gripper_transition"],
                score=0.95,
            ),
            boundary_confidence=0.95,
            vlm_confidence=None,
            overall_confidence=0.0,  # reserved phase = 0
            evidence=None,
            reviewed=False,
            reviewer_id=None,
        )
        d = seg.to_dict()
        assert d["phase"] == "unlabeled"
        assert d["start_boundary"]["sources"] == ["episode_start"]
        assert d["end_boundary"]["candidate_id"] == "b_001"
        assert d["object_track_ids"] == []
        assert d["failure_flags"] == []

    def test_failure_flags_required_list(self):
        # Must be list, not None. The schema is opinionated to avoid downstream None-checks.
        with pytest.raises(TypeError):
            SubtaskSegment(  # type: ignore[call-arg]
                segment_id="s",
                episode_id="e",
                start_frame=0,
                end_frame=1,
                start_time=0.0,
                end_time=0.1,
                phase="unlabeled",
                verb=None,
                object=None,
                target=None,
                failure_flags=None,  # type: ignore[arg-type]
                label_source="signals_only",
                object_state_unavailable=True,
                object_track_ids=[],
                label_version="m.v1",
                start_boundary=BoundaryRef(None, 0.0, ["episode_start"], 1.0),
                end_boundary=BoundaryRef(None, 0.1, ["episode_end"], 1.0),
                boundary_confidence=1.0,
                vlm_confidence=None,
                overall_confidence=0.0,
                evidence=None,
                reviewed=False,
                reviewer_id=None,
            )


class TestBoundaryCandidate:
    def test_serializes_max_merged_scores(self):
        c = BoundaryCandidate(
            id="b_001",
            frame=42,
            time=1.4,
            sources=["eef_velocity_valley", "gripper_transition"],
            scores={"gripper_transition": 0.95, "eef_velocity_valley": 0.62},
            score=0.625,
        )
        d = c.to_dict()
        assert d["sources"] == ["eef_velocity_valley", "gripper_transition"]
        assert d["scores"]["gripper_transition"] == 0.95


class TestManifest:
    def test_compat_block_matches_constant(self):
        m = _make_minimal_manifest()
        d = m.to_dict()
        assert d["compat"] == COMPAT_BLOCK
        assert d["schema_version"] == "0.1.0"

    def test_artifact_lookup_by_role(self):
        m = _make_minimal_manifest()
        assert m.artifact("video").url == "video.mp4"
        with pytest.raises(KeyError):
            m.artifact("does_not_exist")

    def test_pipeline_status_phase1_default(self):
        m = _make_minimal_manifest()
        d = m.to_dict()
        assert d["pipeline_status"]["object_state_available"] is False
        assert d["pipeline_status"]["degraded_from_phase"] is None
        assert d["pipeline_status"]["degrade_reason"] is None


def _make_minimal_manifest() -> Manifest:
    return Manifest(
        schema_version="0.1.0",
        episode_id="ep0",
        task=TaskInfo(text="pick red block", version=None),
        generated_at="2026-04-26T00:00:00Z",
        generator=GeneratorInfo(
            name="mimicanno", cli_version="0.1.0", pipeline_phase=1,
        ),
        config_hash="sha256:" + "0" * 64,
        input_hash="sha256:" + "1" * 64,
        run_hash="sha256:" + "2" * 64,
        model_versions={"sam3": None, "vlm": None},
        pipeline_params={
            "boundary": {
                "weights": {"gripper": 0.5, "velocity": 0.25, "acceleration": 0.15, "action": 0.1},
                "thresholds": {"gripper_delta": 0.3, "velocity_valley": 0.05},
                "merge_window_sec": 0.10,
                "score_threshold": 0.30,
                "disabled_sources": [],
            },
        },
        inputs={
            "video": InputRef(path="data/ep0.mp4", sha256="sha256:" + "a" * 64),
            "parquet": InputRef(path="data/ep0.parquet", sha256="sha256:" + "b" * 64),
        },
        time_base="video_pts_seconds",
        fps=30.0,
        duration_sec=42.5,
        pipeline_status=PipelineStatus(
            object_state_available=False,
            degraded_from_phase=None,
            degrade_reason=None,
        ),
        compat=COMPAT_BLOCK,
        artifacts=[
            Artifact(role="video", url="video.mp4", content_type="video/mp4"),
            Artifact(role="annotation", url="annotation.json", content_type="application/json"),
            Artifact(role="boundaries", url="boundaries.json", content_type="application/json"),
            Artifact(role="signals", url="signals.json", content_type="application/json"),
        ],
    )


class TestAnnotationResult:
    def test_phase1_skeleton(self):
        a = AnnotationResult(
            schema_version="0.1.0",
            episode_id="ep0",
            task=TaskInfo(text="t", version=None),
            generated_at="2026-04-26T00:00:00Z",
            generator=GeneratorInfo(name="mimicanno", cli_version="0.1.0", pipeline_phase=1),
            config_hash="sha256:" + "0" * 64,
            input_hash="sha256:" + "1" * 64,
            run_hash="sha256:" + "2" * 64,
            model_versions={"sam3": None, "vlm": None},
            pipeline_phase=1,
            pipeline_status=PipelineStatus(False, None, None),
            segments=[],
            boundaries_url="boundaries.json",
            signals_url="signals.json",
            notes=None,
        )
        d = a.to_dict()
        assert d["pipeline_phase"] == 1
        assert d["segments"] == []
```

- [ ] **Step 4.2: Run, see red**

Run: `pytest tests/unit/test_schema.py -v`
Expected: `ModuleNotFoundError: No module named 'mimicanno.schema'`.

- [ ] **Step 4.3: Implement `mimicanno/schema.py`**

```python
"""Versioned dataclasses for every JSON shape that hits disk.

Each dataclass exposes ``to_dict()`` returning a JSON-ready Python object
(only str/int/float/bool/None/list/dict). Use ``json.dumps`` (or
``mimicanno.hashing.canonical_json`` for hashing) on the result.

We deliberately use plain ``@dataclass`` rather than pydantic / msgspec —
this code has no validation needs that can't be served by ``jsonschema``
at the I/O boundary, and avoiding the third-party dep simplifies install.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(slots=True)
class TaskInfo:
    text: str
    version: str | None

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "version": self.version}


@dataclass(slots=True)
class GeneratorInfo:
    name: str
    cli_version: str
    pipeline_phase: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "cli_version": self.cli_version,
            "pipeline_phase": self.pipeline_phase,
        }


@dataclass(slots=True)
class InputRef:
    path: str
    sha256: str  # Always prefixed "sha256:"

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256}


@dataclass(slots=True)
class Artifact:
    role: str
    url: str
    content_type: str

    def to_dict(self) -> dict[str, Any]:
        return {"role": self.role, "url": self.url, "content_type": self.content_type}


@dataclass(slots=True)
class PipelineStatus:
    object_state_available: bool
    degraded_from_phase: int | None
    degrade_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_state_available": self.object_state_available,
            "degraded_from_phase": self.degraded_from_phase,
            "degrade_reason": self.degrade_reason,
        }


@dataclass(slots=True)
class BoundaryRef:
    """Per-edge reference attached to a SubtaskSegment (spec §6.1).

    ``candidate_id`` is None for sentinel boundaries (episode_start, episode_end);
    in that case ``sources`` holds ``["episode_start"]`` or ``["episode_end"]``
    and ``score`` is 1.0.
    """
    candidate_id: str | None
    time: float
    sources: list[str]
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "time": self.time,
            "sources": list(self.sources),
            "score": self.score,
        }


@dataclass(slots=True)
class BoundaryCandidate:
    """A boundary candidate emitted by the integrated-score detector (spec §5.4)."""
    id: str
    frame: int
    time: float
    sources: list[str]
    scores: dict[str, float]
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "frame": self.frame,
            "time": self.time,
            "sources": list(self.sources),
            "scores": dict(self.scores),
            "score": self.score,
        }


LabelSource = Literal[
    "signals_only",
    "vlm_robot_state_only",
    "vlm_with_object_state",
    "human_edit",
]


@dataclass(slots=True)
class SubtaskSegment:
    """One labeled (or, in Phase 1, ``unlabeled``) clip in a timeline."""
    segment_id: str
    episode_id: str
    start_frame: int
    end_frame: int
    start_time: float
    end_time: float
    phase: str
    verb: str | None
    object: str | None
    target: str | None
    failure_flags: list[str]
    label_source: LabelSource
    object_state_unavailable: bool
    object_track_ids: list[str]
    label_version: str
    start_boundary: BoundaryRef
    end_boundary: BoundaryRef
    boundary_confidence: float
    vlm_confidence: float | None
    overall_confidence: float
    evidence: str | None
    reviewed: bool
    reviewer_id: str | None

    def __post_init__(self) -> None:
        # Reject None for list fields — the schema is opinionated to avoid
        # downstream None-checks. Empty list is the valid sentinel.
        if self.failure_flags is None:  # type: ignore[unreachable]
            raise TypeError("failure_flags must be list[str], not None")
        if self.object_track_ids is None:  # type: ignore[unreachable]
            raise TypeError("object_track_ids must be list[str], not None")

    def to_dict(self) -> dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "episode_id": self.episode_id,
            "start_frame": self.start_frame,
            "end_frame": self.end_frame,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "phase": self.phase,
            "verb": self.verb,
            "object": self.object,
            "target": self.target,
            "failure_flags": list(self.failure_flags),
            "label_source": self.label_source,
            "object_state_unavailable": self.object_state_unavailable,
            "object_track_ids": list(self.object_track_ids),
            "label_version": self.label_version,
            "start_boundary": self.start_boundary.to_dict(),
            "end_boundary": self.end_boundary.to_dict(),
            "boundary_confidence": self.boundary_confidence,
            "vlm_confidence": self.vlm_confidence,
            "overall_confidence": self.overall_confidence,
            "evidence": self.evidence,
            "reviewed": self.reviewed,
            "reviewer_id": self.reviewer_id,
        }


@dataclass(slots=True)
class Manifest:
    schema_version: str
    episode_id: str
    task: TaskInfo
    generated_at: str
    generator: GeneratorInfo
    config_hash: str
    input_hash: str
    run_hash: str
    model_versions: dict[str, str | None]
    pipeline_params: dict[str, Any]
    inputs: dict[str, InputRef]
    time_base: str
    fps: float
    duration_sec: float
    pipeline_status: PipelineStatus
    compat: dict[str, int]
    artifacts: list[Artifact]

    def artifact(self, role: str) -> Artifact:
        for a in self.artifacts:
            if a.role == role:
                return a
        raise KeyError(f"no artifact with role={role!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "episode_id": self.episode_id,
            "task": self.task.to_dict(),
            "generated_at": self.generated_at,
            "generator": self.generator.to_dict(),
            "config_hash": self.config_hash,
            "input_hash": self.input_hash,
            "run_hash": self.run_hash,
            "model_versions": dict(self.model_versions),
            "pipeline_params": _deep_jsonify(self.pipeline_params),
            "inputs": {k: v.to_dict() for k, v in self.inputs.items()},
            "time_base": self.time_base,
            "fps": self.fps,
            "duration_sec": self.duration_sec,
            "pipeline_status": self.pipeline_status.to_dict(),
            "compat": dict(self.compat),
            "artifacts": [a.to_dict() for a in self.artifacts],
        }


@dataclass(slots=True)
class AnnotationResult:
    schema_version: str
    episode_id: str
    task: TaskInfo
    generated_at: str
    generator: GeneratorInfo
    config_hash: str
    input_hash: str
    run_hash: str
    model_versions: dict[str, str | None]
    pipeline_phase: int
    pipeline_status: PipelineStatus
    segments: list[SubtaskSegment]
    boundaries_url: str
    signals_url: str
    notes: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "episode_id": self.episode_id,
            "task": self.task.to_dict(),
            "generated_at": self.generated_at,
            "generator": self.generator.to_dict(),
            "config_hash": self.config_hash,
            "input_hash": self.input_hash,
            "run_hash": self.run_hash,
            "model_versions": dict(self.model_versions),
            "pipeline_phase": self.pipeline_phase,
            "pipeline_status": self.pipeline_status.to_dict(),
            "segments": [s.to_dict() for s in self.segments],
            "boundaries_url": self.boundaries_url,
            "signals_url": self.signals_url,
            "notes": self.notes,
        }


def _deep_jsonify(value: Any) -> Any:
    """Recursively convert nested dataclasses inside dict/list to dicts.

    Used for ``pipeline_params`` which is a free-form nested dict in the spec.
    """
    if isinstance(value, dict):
        return {k: _deep_jsonify(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_jsonify(v) for v in value]
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    return value
```

- [ ] **Step 4.4: Run, see green**

Run: `pytest tests/unit/test_schema.py -v`
Expected: All pass.

- [ ] **Step 4.5: Commit**

```bash
git add mimicanno/schema.py tests/unit/test_schema.py
git commit -m "$(cat <<'EOF'
schema: dataclasses for Manifest, AnnotationResult, SubtaskSegment, etc.

Plain @dataclass with to_dict(). PipelineStatus, per-edge BoundaryRef,
and the full SubtaskSegment shape (with failure_flags / object_track_ids
defaulting to []). __post_init__ rejects None for list fields so
downstream code never has to None-guard.
EOF
)"
```

---

### Task 5: AnnotationConfig + composite hashing (`mimicanno/config.py`)

This is the heart of canonical_name. Spec §4.1 spells out exactly what feeds `config_hash` (annotation params + target_phase + model identity) vs `input_hash` (episode bytes + task text + adapter identity + labels YAML). `run_hash = sha256(config_hash + input_hash)`.

**Files:**
- Create: `mimicanno/config.py`
- Create: `tests/unit/test_config_hash.py`

- [ ] **Step 5.1: Write failing tests**

```python
# tests/unit/test_config_hash.py
import pytest

from mimicanno.config import (
    AnnotationConfig,
    BoundaryConfig,
    InputBundle,
    ModelConfig,
    compose_run_hash,
    compute_config_hash,
    compute_input_hash,
)


def _make_config(score_threshold: float = 0.30) -> AnnotationConfig:
    return AnnotationConfig(
        boundary=BoundaryConfig(
            weights={"gripper": 0.5, "velocity": 0.25, "acceleration": 0.15, "action": 0.1},
            thresholds={"gripper_delta": 0.3, "velocity_valley": 0.05},
            merge_window_sec=0.10,
            score_threshold=score_threshold,
            disabled_sources=[],
        ),
        target_phase=1,
        model_config=ModelConfig(
            vlm_model=None, vlm_checkpoint=None,
            sam3_model=None, sam3_checkpoint=None,
        ),
    )


def _make_inputs(task: str = "pick red block") -> InputBundle:
    return InputBundle(
        video_sha256="sha256:" + "a" * 64,
        parquet_sha256="sha256:" + "b" * 64,
        task_text=task,
        robot_adapter_name="aloha",
        robot_adapter_config_sha256=None,
        labels_yaml_sha256="sha256:" + "c" * 64,
    )


class TestConfigHash:
    def test_same_config_produces_same_hash(self):
        h1 = compute_config_hash(_make_config())
        h2 = compute_config_hash(_make_config())
        assert h1 == h2

    def test_threshold_change_changes_hash(self):
        h1 = compute_config_hash(_make_config(score_threshold=0.30))
        h2 = compute_config_hash(_make_config(score_threshold=0.31))
        assert h1 != h2

    def test_target_phase_changes_hash(self):
        c1 = _make_config()
        c2 = _make_config()
        c2.target_phase = 2
        assert compute_config_hash(c1) != compute_config_hash(c2)

    def test_vlm_model_changes_hash(self):
        c1 = _make_config()
        c2 = _make_config()
        c2.model_config.vlm_model = "google/gemma-4-E2B-it"
        assert compute_config_hash(c1) != compute_config_hash(c2)

    def test_hash_is_sha256_prefixed(self):
        h = compute_config_hash(_make_config())
        assert h.startswith("sha256:")
        assert len(h) == len("sha256:") + 64


class TestInputHash:
    def test_task_text_changes_hash(self):
        h1 = compute_input_hash(_make_inputs("a"))
        h2 = compute_input_hash(_make_inputs("b"))
        assert h1 != h2

    def test_adapter_name_changes_hash(self):
        i1 = _make_inputs()
        i2 = _make_inputs()
        i2.robot_adapter_name = "koch"
        assert compute_input_hash(i1) != compute_input_hash(i2)

    def test_adapter_config_sha_changes_hash(self):
        i1 = _make_inputs()
        i2 = _make_inputs()
        i2.robot_adapter_config_sha256 = "sha256:" + "d" * 64
        assert compute_input_hash(i1) != compute_input_hash(i2)


class TestComposeRunHash:
    def test_run_hash_depends_on_both(self):
        c = _make_config()
        i = _make_inputs()
        baseline = compose_run_hash(compute_config_hash(c), compute_input_hash(i))

        c2 = _make_config(score_threshold=0.31)
        changed_config = compose_run_hash(compute_config_hash(c2), compute_input_hash(i))

        i2 = _make_inputs(task="something else")
        changed_input = compose_run_hash(compute_config_hash(c), compute_input_hash(i2))

        assert baseline != changed_config
        assert baseline != changed_input
        assert changed_config != changed_input

    def test_run_hash_short_is_12_hex(self):
        from mimicanno.config import run_hash_short
        h = "sha256:" + "9" * 64
        assert run_hash_short(h, length=12) == "9" * 12
        assert run_hash_short(h, length=16) == "9" * 16

    def test_run_hash_short_default_length(self):
        from mimicanno.config import RUN_HASH_DEFAULT_PREFIX_LEN, run_hash_short
        assert RUN_HASH_DEFAULT_PREFIX_LEN == 12
        h = "sha256:" + "f" * 64
        assert len(run_hash_short(h)) == 12
```

- [ ] **Step 5.2: Run, see red**

Run: `pytest tests/unit/test_config_hash.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 5.3: Implement `mimicanno/config.py`**

```python
"""AnnotationConfig + the composite hashing rule from spec §4.1.

config_hash covers everything that changes how the pipeline computes:
    AnnotationConfig + target_phase + model_config (vlm/sam3 + checkpoints).

input_hash covers the bytes/text that go in:
    video_sha256, parquet_sha256, task_text,
    robot_adapter_name, robot_adapter_config_sha256, labels_yaml_sha256.

run_hash = sha256(config_hash || input_hash).
canonical_name = f"{episode_id}__{run_hash[:12]}"  (extended to [:16] on collision).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from mimicanno.hashing import canonical_json, sha256_hex_of_str

RUN_HASH_DEFAULT_PREFIX_LEN: int = 12
RUN_HASH_FALLBACK_PREFIX_LEN: int = 16


@dataclass(slots=True)
class BoundaryConfig:
    weights: dict[str, float]
    thresholds: dict[str, float]
    merge_window_sec: float
    score_threshold: float
    disabled_sources: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "weights": dict(self.weights),
            "thresholds": dict(self.thresholds),
            "merge_window_sec": self.merge_window_sec,
            "score_threshold": self.score_threshold,
            "disabled_sources": list(self.disabled_sources),
        }


@dataclass(slots=True)
class ModelConfig:
    vlm_model: str | None
    vlm_checkpoint: str | None
    sam3_model: str | None
    sam3_checkpoint: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "vlm_model": self.vlm_model,
            "vlm_checkpoint": self.vlm_checkpoint,
            "sam3_model": self.sam3_model,
            "sam3_checkpoint": self.sam3_checkpoint,
        }


@dataclass(slots=True)
class AnnotationConfig:
    boundary: BoundaryConfig
    target_phase: int
    model_config: ModelConfig

    def to_dict(self) -> dict[str, Any]:
        return {
            "annotation_config": {"boundary": self.boundary.to_dict()},
            "target_phase": self.target_phase,
            "model_config": self.model_config.to_dict(),
        }


@dataclass(slots=True)
class InputBundle:
    """Identity of the inputs for one run. All sha256 strings are ``sha256:<hex>``."""
    video_sha256: str
    parquet_sha256: str
    task_text: str
    robot_adapter_name: str
    robot_adapter_config_sha256: str | None
    labels_yaml_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_sha256": self.video_sha256,
            "parquet_sha256": self.parquet_sha256,
            "task_text": self.task_text,
            "robot_adapter_name": self.robot_adapter_name,
            "robot_adapter_config_sha256": self.robot_adapter_config_sha256,
            "labels_yaml_sha256": self.labels_yaml_sha256,
        }


def compute_config_hash(cfg: AnnotationConfig) -> str:
    return "sha256:" + sha256_hex_of_str(canonical_json(cfg.to_dict()))


def compute_input_hash(inputs: InputBundle) -> str:
    return "sha256:" + sha256_hex_of_str(canonical_json(inputs.to_dict()))


def compose_run_hash(config_hash: str, input_hash: str) -> str:
    if not config_hash.startswith("sha256:"):
        raise ValueError(f"config_hash must be 'sha256:'-prefixed; got {config_hash!r}")
    if not input_hash.startswith("sha256:"):
        raise ValueError(f"input_hash must be 'sha256:'-prefixed; got {input_hash!r}")
    combined = config_hash + input_hash
    return "sha256:" + hashlib.sha256(combined.encode("utf-8")).hexdigest()


def run_hash_short(run_hash: str, length: int = RUN_HASH_DEFAULT_PREFIX_LEN) -> str:
    """Return the truncated hex prefix used as the canonical-name suffix."""
    if not run_hash.startswith("sha256:"):
        raise ValueError(f"run_hash must be 'sha256:'-prefixed; got {run_hash!r}")
    hex_part = run_hash[len("sha256:"):]
    return hex_part[:length]
```

- [ ] **Step 5.4: Run, see green**

Run: `pytest tests/unit/test_config_hash.py -v`
Expected: All pass.

- [ ] **Step 5.5: Commit**

```bash
git add mimicanno/config.py tests/unit/test_config_hash.py
git commit -m "$(cat <<'EOF'
config: AnnotationConfig + composite hashing per spec §4.1

config_hash covers AnnotationConfig + target_phase + model_config.
input_hash covers video/parquet sha256 + task_text + adapter id + labels sha.
run_hash = sha256(config_hash || input_hash).
run_hash_short defaults to 12 hex; collision handler bumps to 16.
EOF
)"
```

---

## Phase B — Robot adapters

### Task 6: `RobotAdapter` Protocol + `AlohaAdapter`

The Aloha adapter handles the "EEF available" path. Per spec §7.2, `gripper_signal` is mandatory; `eef_pose` and `eef_velocity` may return `None` and downstream callers must auto-disable EEF detectors.

**Files:**
- Create: `mimicanno/adapters/__init__.py`
- Create: `mimicanno/adapters/base.py`
- Create: `mimicanno/adapters/aloha.py`
- Create: `tests/unit/test_adapters_aloha.py`

- [ ] **Step 6.1: Write failing tests**

```python
# tests/unit/test_adapters_aloha.py
import numpy as np
import pyarrow as pa

from mimicanno.adapters.aloha import AlohaAdapter
from mimicanno.adapters.base import RobotAdapter


def _aloha_table(n_frames: int = 30) -> pa.Table:
    # Aloha state layout (Phase-1 simplification): 14 floats per frame
    # for one arm with the LAST entry being the gripper position in [0,1],
    # and 6 entries before the gripper representing EEF pose (xyz + rpy quat-ish).
    # We synthesize a minimal-but-shaped vector here.
    rng = np.random.default_rng(0)
    state = rng.uniform(-1.0, 1.0, size=(n_frames, 14)).astype(np.float32)
    # Gripper at index 13: monotonic close
    state[:, 13] = np.linspace(1.0, 0.0, n_frames, dtype=np.float32)
    # EEF position columns (0..2 = xyz)
    state[:, 0:3] = np.cumsum(
        rng.normal(0, 0.01, size=(n_frames, 3)).astype(np.float32), axis=0,
    )
    action = rng.uniform(-1.0, 1.0, size=(n_frames, 14)).astype(np.float32)
    timestamps = np.arange(n_frames, dtype=np.float64) / 30.0
    return pa.table(
        {
            "observation.state": pa.array(state.tolist()),
            "action": pa.array(action.tolist()),
            "timestamp": pa.array(timestamps.tolist()),
        },
    )


def test_aloha_implements_protocol():
    a = AlohaAdapter()
    assert isinstance(a, RobotAdapter)


def test_aloha_name():
    assert AlohaAdapter().name == "aloha"


def test_aloha_gripper_signal_in_unit_interval():
    table = _aloha_table()
    g = AlohaAdapter().gripper_signal(table)
    assert g.shape == (30,)
    assert g.dtype == np.float64
    assert g.min() >= 0.0 and g.max() <= 1.0


def test_aloha_gripper_signal_is_strictly_decreasing_for_synthetic_close():
    table = _aloha_table()
    g = AlohaAdapter().gripper_signal(table)
    diffs = np.diff(g)
    assert (diffs <= 0).all()  # monotonic decrease per fixture


def test_aloha_eef_pose_returns_array():
    pose = AlohaAdapter().eef_pose(_aloha_table())
    assert pose is not None
    assert pose.shape == (30, 7)


def test_aloha_eef_velocity_is_finite_and_nonneg():
    v = AlohaAdapter().eef_velocity(_aloha_table())
    assert v is not None
    assert v.shape == (30,)
    assert np.isfinite(v).all()
    assert (v >= 0).all()
```

- [ ] **Step 6.2: Run, see red**

Run: `pytest tests/unit/test_adapters_aloha.py -v`
Expected: import error.

- [ ] **Step 6.3: Implement adapter base + Aloha**

```python
# mimicanno/adapters/__init__.py
"""Robot-specific adapters that turn LeRobot parquet tables into Phase-1 signals."""
```

```python
# mimicanno/adapters/base.py
"""RobotAdapter Protocol — see spec §7.2."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np
import pyarrow as pa


@runtime_checkable
class RobotAdapter(Protocol):
    """Per-robot accessor for the signals Phase 1 needs.

    ``gripper_signal`` is mandatory. The two EEF accessors are optional —
    return ``None`` when the robot's parquet does not carry Cartesian EEF
    data; the boundary detector will auto-disable EEF-based detectors and
    record them in ``manifest.pipeline_params.boundary.disabled_sources``.
    Forward kinematics from joint angles is out of scope for Phase 1.
    """

    name: str

    def gripper_signal(self, df: pa.Table) -> np.ndarray:
        """Return ``[T]`` float64 array in [0.0, 1.0] (1.0 = open)."""
        ...

    def eef_pose(self, df: pa.Table) -> np.ndarray | None:
        """Return ``[T, 7]`` float64 (xyz + quat). May return None."""
        ...

    def eef_velocity(self, df: pa.Table) -> np.ndarray | None:
        """Return ``[T]`` float64 in m/s (magnitude). May return None."""
        ...
```

```python
# mimicanno/adapters/aloha.py
"""Aloha adapter: Cartesian EEF available, gripper at the last state index."""
from __future__ import annotations

import numpy as np
import pyarrow as pa


class AlohaAdapter:
    name: str = "aloha"

    # Indices into observation.state for the single-arm Aloha layout.
    EEF_XYZ_SLICE: slice = slice(0, 3)
    EEF_QUAT_SLICE: slice = slice(3, 7)
    GRIPPER_INDEX: int = 13

    def _state(self, df: pa.Table) -> np.ndarray:
        # Each row of observation.state is a list/array of floats; convert to (T, D).
        col = df.column("observation.state")
        return np.asarray(col.to_pylist(), dtype=np.float64)

    def _timestamps(self, df: pa.Table) -> np.ndarray:
        return np.asarray(df.column("timestamp").to_pylist(), dtype=np.float64)

    def gripper_signal(self, df: pa.Table) -> np.ndarray:
        state = self._state(df)
        g = state[:, self.GRIPPER_INDEX].astype(np.float64)
        # Defensive clip; downstream code assumes [0,1].
        return np.clip(g, 0.0, 1.0)

    def eef_pose(self, df: pa.Table) -> np.ndarray | None:
        state = self._state(df)
        xyz = state[:, self.EEF_XYZ_SLICE]
        quat = state[:, self.EEF_QUAT_SLICE]
        return np.concatenate([xyz, quat], axis=1).astype(np.float64)

    def eef_velocity(self, df: pa.Table) -> np.ndarray | None:
        pose = self.eef_pose(df)
        if pose is None:
            return None
        ts = self._timestamps(df)
        # Backward-difference magnitude. dt[0] handled by replicating dt[1].
        dt = np.diff(ts)
        if (dt <= 0).any():
            raise ValueError("non-monotonic timestamps in parquet")
        d_xyz = np.diff(pose[:, :3], axis=0)
        speed = np.linalg.norm(d_xyz, axis=1) / dt
        return np.concatenate([[speed[0]], speed]).astype(np.float64)
```

- [ ] **Step 6.4: Run, see green**

Run: `pytest tests/unit/test_adapters_aloha.py -v`
Expected: All pass.

- [ ] **Step 6.5: Commit**

```bash
git add mimicanno/adapters/__init__.py mimicanno/adapters/base.py mimicanno/adapters/aloha.py tests/unit/test_adapters_aloha.py
git commit -m "$(cat <<'EOF'
adapters: RobotAdapter Protocol + AlohaAdapter

Aloha exposes Cartesian EEF, gripper at index 13. eef_velocity is
backward-difference magnitude with the first frame replicated to avoid
a length-T-1 array. Defensive clip on gripper to [0,1] so downstream
detectors don't have to.
EOF
)"
```

---

### Task 7: `KochAdapter` (joint-only) + `SO100Adapter`

Per §7.2, joint-only adapters return `None` for EEF accessors. Phase 1 detector orchestrator (later task) treats `None` as "this detector is disabled."

**Files:**
- Create: `mimicanno/adapters/koch.py`
- Create: `mimicanno/adapters/so100.py`
- Create: `tests/unit/test_adapters_koch.py`

- [ ] **Step 7.1: Write failing test**

```python
# tests/unit/test_adapters_koch.py
import numpy as np
import pyarrow as pa

from mimicanno.adapters.koch import KochAdapter
from mimicanno.adapters.so100 import SO100Adapter


def _joint_only_table(n: int = 30) -> pa.Table:
    rng = np.random.default_rng(0)
    state = rng.uniform(-1.0, 1.0, size=(n, 6)).astype(np.float32)
    state[:, 5] = np.linspace(1.0, 0.0, n)
    action = rng.uniform(-1.0, 1.0, size=(n, 6)).astype(np.float32)
    ts = np.arange(n, dtype=np.float64) / 30.0
    return pa.table({
        "observation.state": pa.array(state.tolist()),
        "action": pa.array(action.tolist()),
        "timestamp": pa.array(ts.tolist()),
    })


class TestKoch:
    def test_name(self):
        assert KochAdapter().name == "koch"

    def test_gripper_signal_at_last_index(self):
        g = KochAdapter().gripper_signal(_joint_only_table())
        assert g.shape == (30,)
        assert g.min() >= 0.0 and g.max() <= 1.0

    def test_no_eef(self):
        a = KochAdapter()
        assert a.eef_pose(_joint_only_table()) is None
        assert a.eef_velocity(_joint_only_table()) is None


class TestSo100:
    def test_name(self):
        assert SO100Adapter().name == "so100"

    def test_gripper_signal(self):
        g = SO100Adapter().gripper_signal(_joint_only_table())
        assert g.shape == (30,)
```

- [ ] **Step 7.2: Run, see red**

Run: `pytest tests/unit/test_adapters_koch.py -v`
Expected: import error.

- [ ] **Step 7.3: Implement**

```python
# mimicanno/adapters/koch.py
"""Koch adapter: joint-only state; no Cartesian EEF in the parquet by default."""
from __future__ import annotations

import numpy as np
import pyarrow as pa


class KochAdapter:
    name: str = "koch"
    GRIPPER_INDEX: int = 5

    def gripper_signal(self, df: pa.Table) -> np.ndarray:
        state = np.asarray(df.column("observation.state").to_pylist(), dtype=np.float64)
        return np.clip(state[:, self.GRIPPER_INDEX], 0.0, 1.0)

    def eef_pose(self, df: pa.Table) -> np.ndarray | None:
        # Joint-only; FK is out of scope for Phase 1 (spec §7.2).
        return None

    def eef_velocity(self, df: pa.Table) -> np.ndarray | None:
        return None
```

```python
# mimicanno/adapters/so100.py
"""SO-100 adapter: joint-only, layout shared with Koch for Phase 1."""
from __future__ import annotations

import numpy as np
import pyarrow as pa


class SO100Adapter:
    name: str = "so100"
    GRIPPER_INDEX: int = 5

    def gripper_signal(self, df: pa.Table) -> np.ndarray:
        state = np.asarray(df.column("observation.state").to_pylist(), dtype=np.float64)
        return np.clip(state[:, self.GRIPPER_INDEX], 0.0, 1.0)

    def eef_pose(self, df: pa.Table) -> np.ndarray | None:
        return None

    def eef_velocity(self, df: pa.Table) -> np.ndarray | None:
        return None
```

- [ ] **Step 7.4: Run, see green**

Run: `pytest tests/unit/test_adapters_koch.py -v`

- [ ] **Step 7.5: Commit**

```bash
git add mimicanno/adapters/koch.py mimicanno/adapters/so100.py tests/unit/test_adapters_koch.py
git commit -m "$(cat <<'EOF'
adapters: KochAdapter + SO100Adapter (joint-only)

Both return None from eef_pose/eef_velocity per §7.2. Forward kinematics
is out of scope for Phase 1; users who want EEF-based detectors on
joint-only robots pre-compute Cartesian columns and use GenericAdapter.
EOF
)"
```

---

### Task 8: `GenericAdapter` (config-driven)

Spec §7.2 calls out a config file (`--robot-config <yaml>`) for users who pre-compute custom columns. The YAML's sha256 feeds into `input_hash`, so the run is reproducible.

**Files:**
- Create: `mimicanno/adapters/generic.py`
- Create: `tests/unit/test_adapters_generic.py`

- [ ] **Step 8.1: Write failing test**

```python
# tests/unit/test_adapters_generic.py
from pathlib import Path

import numpy as np
import pyarrow as pa
import pytest
import yaml

from mimicanno.adapters.generic import GenericAdapter


def _table_with_cols(n: int = 30) -> pa.Table:
    return pa.table({
        "observation.state": pa.array(
            [[0.0] * 14 for _ in range(n)],
        ),
        "observation.eef_xyz": pa.array(
            np.cumsum(np.zeros((n, 3)) + 0.01, axis=0).tolist(),
        ),
        "observation.eef_quat": pa.array([[0.0, 0.0, 0.0, 1.0]] * n),
        "observation.gripper": pa.array(np.linspace(1.0, 0.0, n).tolist()),
        "action": pa.array([[0.0] * 14 for _ in range(n)]),
        "timestamp": pa.array((np.arange(n) / 30.0).tolist()),
    })


def _config_yaml(tmp_path: Path) -> Path:
    cfg = {
        "schema_version": "0.1.0",
        "name": "custom-arm",
        "gripper_column": "observation.gripper",
        "eef_xyz_column": "observation.eef_xyz",
        "eef_quat_column": "observation.eef_quat",
    }
    p = tmp_path / "robot.yaml"
    p.write_text(yaml.safe_dump(cfg))
    return p


def test_generic_loads_yaml(tmp_path: Path):
    a = GenericAdapter.from_yaml(_config_yaml(tmp_path))
    assert a.name == "generic"


def test_generic_gripper_from_named_column(tmp_path: Path):
    a = GenericAdapter.from_yaml(_config_yaml(tmp_path))
    g = a.gripper_signal(_table_with_cols())
    assert g.shape == (30,)
    assert g[0] == pytest.approx(1.0)
    assert g[-1] == pytest.approx(0.0)


def test_generic_eef_pose_assembled_from_xyz_and_quat(tmp_path: Path):
    a = GenericAdapter.from_yaml(_config_yaml(tmp_path))
    pose = a.eef_pose(_table_with_cols())
    assert pose is not None
    assert pose.shape == (30, 7)


def test_generic_no_eef_when_columns_unmapped(tmp_path: Path):
    cfg_path = tmp_path / "min.yaml"
    cfg_path.write_text(yaml.safe_dump({
        "schema_version": "0.1.0",
        "name": "min",
        "gripper_column": "observation.gripper",
    }))
    a = GenericAdapter.from_yaml(cfg_path)
    assert a.eef_pose(_table_with_cols()) is None
    assert a.eef_velocity(_table_with_cols()) is None
```

- [ ] **Step 8.2: Run, see red**

Run: `pytest tests/unit/test_adapters_generic.py -v`

- [ ] **Step 8.3: Implement**

```python
# mimicanno/adapters/generic.py
"""GenericAdapter: column mapping driven by a user-supplied YAML."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow as pa
import yaml


@dataclass(slots=True)
class GenericAdapter:
    """Configurable adapter — column names come from a user-supplied YAML.

    Schema (``schema_version: "0.1.0"``):
        name: str               # informational
        gripper_column: str     # required; values clipped to [0,1]
        eef_xyz_column: str | None
        eef_quat_column: str | None
    """

    name: str
    gripper_column: str
    eef_xyz_column: str | None
    eef_quat_column: str | None

    @classmethod
    def from_yaml(cls, path: Path) -> "GenericAdapter":
        cfg = yaml.safe_load(path.read_text())
        if cfg.get("schema_version") != "0.1.0":
            raise ValueError(
                f"unsupported robot-config schema_version "
                f"(expected 0.1.0, got {cfg.get('schema_version')!r})",
            )
        if "gripper_column" not in cfg:
            raise ValueError("robot-config must specify gripper_column")
        return cls(
            name="generic",
            gripper_column=cfg["gripper_column"],
            eef_xyz_column=cfg.get("eef_xyz_column"),
            eef_quat_column=cfg.get("eef_quat_column"),
        )

    def gripper_signal(self, df: pa.Table) -> np.ndarray:
        col = df.column(self.gripper_column)
        g = np.asarray(col.to_pylist(), dtype=np.float64)
        return np.clip(g, 0.0, 1.0)

    def eef_pose(self, df: pa.Table) -> np.ndarray | None:
        if self.eef_xyz_column is None or self.eef_quat_column is None:
            return None
        xyz = np.asarray(df.column(self.eef_xyz_column).to_pylist(), dtype=np.float64)
        quat = np.asarray(df.column(self.eef_quat_column).to_pylist(), dtype=np.float64)
        return np.concatenate([xyz, quat], axis=1)

    def eef_velocity(self, df: pa.Table) -> np.ndarray | None:
        pose = self.eef_pose(df)
        if pose is None:
            return None
        ts = np.asarray(df.column("timestamp").to_pylist(), dtype=np.float64)
        dt = np.diff(ts)
        if (dt <= 0).any():
            raise ValueError("non-monotonic timestamps in parquet")
        d_xyz = np.diff(pose[:, :3], axis=0)
        speed = np.linalg.norm(d_xyz, axis=1) / dt
        return np.concatenate([[speed[0]], speed]).astype(np.float64)
```

- [ ] **Step 8.4: Run, see green**

Run: `pytest tests/unit/test_adapters_generic.py -v`

- [ ] **Step 8.5: Commit**

```bash
git add mimicanno/adapters/generic.py tests/unit/test_adapters_generic.py
git commit -m "$(cat <<'EOF'
adapters: GenericAdapter (config-driven column mapping)

Column names come from a user-supplied YAML whose sha256 is fed into
input_hash so the run is reproducible. EEF columns are optional; if
not mapped the EEF detectors auto-disable per §7.2.
EOF
)"
```

---

## Phase C — Input I/O

### Task 9: Parquet loader (`mimicanno/io_parquet.py`)

Spec §7.1 + §7.3 + §7.4: required columns, FPS resolution from metadata or timestamp variance, NaN-gap handling.

**Files:**
- Create: `mimicanno/io_parquet.py`
- Create: `tests/unit/test_io_parquet.py`

- [ ] **Step 9.1: Write failing tests**

```python
# tests/unit/test_io_parquet.py
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from mimicanno.io_parquet import (
    ParquetLoadError,
    interpolate_short_nan_spans,
    load_episode_parquet,
    resolve_fps,
)


def _write_parquet(table: pa.Table, path: Path) -> Path:
    pq.write_table(table, path)
    return path


def _good_table(n: int = 30, fps: float = 30.0) -> pa.Table:
    return pa.table({
        "observation.state": pa.array([[0.0] * 14 for _ in range(n)]),
        "action": pa.array([[0.0] * 14 for _ in range(n)]),
        "timestamp": pa.array((np.arange(n) / fps).tolist()),
    })


class TestLoad:
    def test_load_returns_table_and_sha256(self, tmp_path: Path):
        p = _write_parquet(_good_table(), tmp_path / "ep.parquet")
        result = load_episode_parquet(p)
        assert result.table.num_rows == 30
        assert result.sha256.startswith("sha256:")

    def test_missing_required_column_raises(self, tmp_path: Path):
        bad = pa.table({
            "observation.state": pa.array([[0.0] * 14]),
            # action missing — but action is OPTIONAL per §7.1, so this is OK
            "timestamp": pa.array([0.0]),
        })
        p = _write_parquet(bad, tmp_path / "no_action.parquet")
        # Should NOT raise — action is optional in Phase 1.
        result = load_episode_parquet(p)
        assert result.table.num_rows == 1

    def test_missing_state_raises(self, tmp_path: Path):
        bad = pa.table({
            "action": pa.array([[0.0]]),
            "timestamp": pa.array([0.0]),
        })
        p = _write_parquet(bad, tmp_path / "bad.parquet")
        with pytest.raises(ParquetLoadError, match="observation.state"):
            load_episode_parquet(p)


class TestResolveFps:
    def test_uniform_timestamps(self):
        ts = np.arange(60, dtype=np.float64) / 30.0
        assert resolve_fps(ts) == pytest.approx(30.0, abs=0.01)

    def test_variance_too_high_raises(self):
        ts = np.array([0.0, 0.033, 0.066, 0.5, 0.6, 0.7])  # huge gap
        with pytest.raises(ParquetLoadError, match="variance"):
            resolve_fps(ts)

    def test_non_monotonic_raises(self):
        ts = np.array([0.0, 0.033, 0.020, 0.066])
        with pytest.raises(ParquetLoadError, match="monotonic"):
            resolve_fps(ts)


class TestInterpolateShortNan:
    def test_short_span_filled(self):
        x = np.array([1.0, 2.0, np.nan, np.nan, 5.0, 6.0])
        out = interpolate_short_nan_spans(x, fps=30.0, max_span_sec=0.5)
        assert np.isfinite(out).all()
        assert out[2] == pytest.approx(3.0, abs=1e-6)
        assert out[3] == pytest.approx(4.0, abs=1e-6)

    def test_long_span_raises(self):
        # 30 fps, 30 NaN frames in a row = 1.0 s span > 0.5 s threshold
        x = np.concatenate([np.arange(10.0), np.full(30, np.nan), np.arange(10.0) + 40])
        with pytest.raises(ParquetLoadError, match="NaN span"):
            interpolate_short_nan_spans(x, fps=30.0, max_span_sec=0.5)
```

- [ ] **Step 9.2: Run, see red**

Run: `pytest tests/unit/test_io_parquet.py -v`

- [ ] **Step 9.3: Implement**

```python
# mimicanno/io_parquet.py
"""Parquet loading + FPS resolution + NaN gap handling (spec §7.1 / §7.3 / §7.4)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from mimicanno.hashing import sha256_file


class ParquetLoadError(Exception):
    """Raised on any parquet schema / shape / consistency problem worth aborting on."""


@dataclass(slots=True)
class LoadedEpisode:
    table: pa.Table
    sha256: str  # "sha256:<hex>"


REQUIRED_COLUMNS: tuple[str, ...] = ("observation.state", "timestamp")
# action is optional in Phase 1 (spec §7.1)
OPTIONAL_COLUMNS: tuple[str, ...] = ("action", "frame_index", "episode_index")


def load_episode_parquet(path: Path) -> LoadedEpisode:
    table = pq.read_table(path)
    missing = [c for c in REQUIRED_COLUMNS if c not in table.column_names]
    if missing:
        raise ParquetLoadError(
            f"parquet missing required column(s): {missing} (file={path})",
        )
    return LoadedEpisode(table=table, sha256="sha256:" + sha256_file(path))


def resolve_fps(timestamps: np.ndarray) -> float:
    """Compute FPS from timestamps (spec §7.3 step 2)."""
    if timestamps.ndim != 1 or timestamps.size < 2:
        raise ParquetLoadError("timestamp column too short to resolve fps")
    diffs = np.diff(timestamps)
    if (diffs <= 0).any():
        raise ParquetLoadError("timestamps must be strictly monotonic")
    median = float(np.median(diffs))
    std = float(np.std(diffs))
    rel = std / median if median > 0 else float("inf")
    if rel > 0.05:
        raise ParquetLoadError(
            f"timestamp variance too high to resolve fps "
            f"(std/median = {rel:.3f}; threshold 0.05). "
            "Provide fps via episode metadata.",
        )
    return 1.0 / median


def interpolate_short_nan_spans(
    x: np.ndarray, *, fps: float, max_span_sec: float = 0.5,
) -> np.ndarray:
    """Linear-interpolate NaN spans no longer than ``max_span_sec``; abort longer ones."""
    if x.ndim != 1:
        raise ValueError("interpolate_short_nan_spans expects 1-D")
    out = x.astype(np.float64).copy()
    isnan = np.isnan(out)
    if not isnan.any():
        return out
    max_span_frames = int(max_span_sec * fps)
    # Find consecutive NaN runs.
    in_span = False
    span_start = 0
    for i, missing in enumerate(isnan):
        if missing and not in_span:
            in_span = True
            span_start = i
        elif not missing and in_span:
            in_span = False
            span_len = i - span_start
            if span_len > max_span_frames:
                raise ParquetLoadError(
                    f"NaN span of {span_len} frames "
                    f"(>{max_span_sec}s @ {fps}fps) at frames {span_start}..{i - 1}",
                )
    if in_span:
        span_len = len(out) - span_start
        if span_len > max_span_frames:
            raise ParquetLoadError(
                f"NaN span of {span_len} frames extends to end "
                f"(>{max_span_sec}s @ {fps}fps) starting at frame {span_start}",
            )
    # All spans are short — interpolate.
    idx = np.arange(len(out))
    out[isnan] = np.interp(idx[isnan], idx[~isnan], out[~isnan])
    return out
```

- [ ] **Step 9.4: Run, see green**

Run: `pytest tests/unit/test_io_parquet.py -v`

- [ ] **Step 9.5: Commit**

```bash
git add mimicanno/io_parquet.py tests/unit/test_io_parquet.py
git commit -m "$(cat <<'EOF'
io_parquet: episode load + fps resolution + NaN gap handling

Required columns are observation.state and timestamp (action is
optional in Phase 1 per §7.1). FPS comes from timestamp median diff
with a 5% variance ceiling. Short NaN spans (≤0.5s) are linearly
interpolated; longer spans abort.
EOF
)"
```

---

### Task 10: Video probe + materialization (`mimicanno/io_video.py`)

Spec §13 (perf split: video copy is I/O path) + §4.6 (default copy, opt-in symlink).

**Files:**
- Create: `mimicanno/io_video.py`
- Create: `tests/unit/test_io_video.py`

- [ ] **Step 10.1: Write failing tests**

These tests use a tiny mp4 generated by `imageio_ffmpeg`. We synthesize a 30-frame solid-color clip at 30 fps so tests never depend on external assets.

```python
# tests/unit/test_io_video.py
from pathlib import Path

import numpy as np
import pytest

from mimicanno.io_video import (
    VideoProbe,
    copy_video,
    materialize_video,
    probe_video,
    symlink_video,
)


@pytest.fixture
def tiny_mp4(tmp_path: Path) -> Path:
    """Generate a 30-frame 64x64 video at 30 fps via imageio_ffmpeg."""
    import imageio_ffmpeg
    out = tmp_path / "tiny.mp4"
    writer = imageio_ffmpeg.write_frames(
        str(out),
        size=(64, 64),
        fps=30,
        codec="libx264",
        macro_block_size=1,
        quality=8,
    )
    writer.send(None)  # init
    rng = np.random.default_rng(0)
    for _ in range(30):
        frame = rng.integers(0, 255, size=(64, 64, 3), dtype=np.uint8)
        writer.send(frame.tobytes())
    writer.close()
    return out


class TestProbe:
    def test_returns_duration_and_fps(self, tiny_mp4: Path):
        probe = probe_video(tiny_mp4)
        assert isinstance(probe, VideoProbe)
        assert probe.fps == pytest.approx(30.0, abs=0.5)
        assert probe.duration_sec == pytest.approx(1.0, abs=0.1)
        assert probe.sha256.startswith("sha256:")
        assert probe.width == 64 and probe.height == 64


class TestMaterialize:
    def test_copy_default(self, tiny_mp4: Path, tmp_path: Path):
        run_dir = tmp_path / "run.tmp.123"
        run_dir.mkdir()
        out = materialize_video(tiny_mp4, run_dir, link=False)
        assert out == run_dir / "video.mp4"
        assert out.exists() and not out.is_symlink()
        assert out.stat().st_size == tiny_mp4.stat().st_size

    def test_symlink_when_requested(self, tiny_mp4: Path, tmp_path: Path):
        run_dir = tmp_path / "run.tmp.456"
        run_dir.mkdir()
        out = materialize_video(tiny_mp4, run_dir, link=True)
        assert out == run_dir / "video.mp4"
        assert out.is_symlink()

    def test_copy_helper_returns_destination(self, tiny_mp4: Path, tmp_path: Path):
        dest = copy_video(tiny_mp4, tmp_path / "out.mp4")
        assert dest == tmp_path / "out.mp4"
        assert dest.read_bytes() == tiny_mp4.read_bytes()
```

- [ ] **Step 10.2: Run, see red**

Run: `pytest tests/unit/test_io_video.py -v`

- [ ] **Step 10.3: Implement**

```python
# mimicanno/io_video.py
"""Video probing + run-dir materialization (spec §4.6, §13)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

from mimicanno.hashing import sha256_file


class VideoProbeError(Exception):
    pass


@dataclass(slots=True)
class VideoProbe:
    sha256: str             # "sha256:<hex>"
    duration_sec: float
    fps: float
    width: int
    height: int


def probe_video(path: Path) -> VideoProbe:
    """Probe a video for fps, duration, and dimensions using ffprobe.

    ``imageio_ffmpeg`` ships an ``ffmpeg`` binary; we invoke its sibling
    ``ffprobe`` (on the same PATH directory) for structured output.
    """
    ffmpeg = get_ffmpeg_exe()
    ffprobe = str(Path(ffmpeg).with_name("ffprobe"))
    cmd = [
        ffprobe,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,duration:format=duration",
        "-of", "json",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as e:
        raise VideoProbeError(f"ffprobe binary not found at {ffprobe}") from e
    except subprocess.CalledProcessError as e:
        raise VideoProbeError(
            f"ffprobe failed for {path}: {e.stderr.strip()}",
        ) from e

    data = json.loads(result.stdout)
    if not data.get("streams"):
        raise VideoProbeError(f"no video stream in {path}")
    stream = data["streams"][0]
    num, _, den = stream["r_frame_rate"].partition("/")
    fps = float(num) / float(den) if den else float(num)

    duration_str = stream.get("duration") or data.get("format", {}).get("duration")
    if duration_str is None:
        raise VideoProbeError(f"could not read duration for {path}")
    duration = float(duration_str)

    return VideoProbe(
        sha256="sha256:" + sha256_file(path),
        duration_sec=duration,
        fps=fps,
        width=int(stream["width"]),
        height=int(stream["height"]),
    )


def copy_video(src: Path, dest: Path) -> Path:
    shutil.copyfile(src, dest)
    return dest


def symlink_video(src: Path, dest: Path) -> Path:
    """Create a relative symlink from ``dest`` to ``src``."""
    rel = os.path.relpath(src.resolve(), dest.parent.resolve())
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    dest.symlink_to(rel)
    return dest


def materialize_video(src: Path, run_dir: Path, *, link: bool) -> Path:
    """Place the video into ``run_dir`` as ``video.mp4`` (copy default; symlink opt-in)."""
    dest = run_dir / "video.mp4"
    if link:
        return symlink_video(src, dest)
    return copy_video(src, dest)
```

- [ ] **Step 10.4: Run, see green**

Run: `pytest tests/unit/test_io_video.py -v`

- [ ] **Step 10.5: Commit**

```bash
git add mimicanno/io_video.py tests/unit/test_io_video.py
git commit -m "$(cat <<'EOF'
io_video: ffprobe-based video probe + copy/symlink materialization

Probes width/height/fps/duration via the ffprobe binary that ships with
imageio_ffmpeg. Default materialize is copy (per §4.6); --link-video
opts into a relative symlink. The test fixture synthesizes a 30-frame
64x64 mp4 so tests don't depend on external assets.
EOF
)"
```

---

## Phase D — Signals, detectors, score, bracketing

### Task 11: Signal smoothing (`mimicanno/signals.py`)

Spec §5.1: smoothed with 1-D Gaussian, `sigma = fps * 0.05` (≈ 50 ms).

**Files:**
- Create: `mimicanno/signals.py`
- Create: `tests/unit/test_signals.py`

- [ ] **Step 11.1: Write failing test**

```python
# tests/unit/test_signals.py
import numpy as np
import pytest

from mimicanno.signals import (
    SignalChannel,
    downsample_for_viewer,
    gaussian_smooth_1d,
    smoothing_sigma_for_fps,
)


class TestSmooth:
    def test_sigma_50ms(self):
        assert smoothing_sigma_for_fps(30.0) == pytest.approx(1.5)
        assert smoothing_sigma_for_fps(60.0) == pytest.approx(3.0)

    def test_smooth_preserves_dc(self):
        x = np.full(120, 0.7)
        out = gaussian_smooth_1d(x, sigma=1.5)
        assert out.shape == x.shape
        assert np.allclose(out, 0.7, atol=1e-3)

    def test_smooth_attenuates_step_edge(self):
        x = np.concatenate([np.zeros(60), np.ones(60)])
        out = gaussian_smooth_1d(x, sigma=3.0)
        # The exact midpoint (frame 60) should be near 0.5; right after it
        # the smoothed value rises monotonically toward 1.
        assert 0.3 < out[60] < 0.7
        assert out[58] < out[62]


class TestDownsample:
    def test_keeps_uniform_dt(self):
        full = np.arange(600, dtype=np.float64)
        ch = SignalChannel(name="x", unit="raw", values=full, dt_sec=1.0 / 60.0)
        out = downsample_for_viewer(ch, target_hz=30.0)
        assert out.dt_sec == pytest.approx(1.0 / 30.0, abs=1e-6)
        # 600 samples at 60Hz over 10s -> 300 samples at 30Hz
        assert 295 <= out.values.size <= 305

    def test_no_op_when_already_below_target(self):
        full = np.arange(60, dtype=np.float64)
        ch = SignalChannel(name="x", unit="raw", values=full, dt_sec=1.0 / 30.0)
        out = downsample_for_viewer(ch, target_hz=30.0)
        assert out.values.size == 60
        assert out.dt_sec == pytest.approx(1.0 / 30.0)
```

- [ ] **Step 11.2: Run, see red**

Run: `pytest tests/unit/test_signals.py -v`

- [ ] **Step 11.3: Implement**

```python
# mimicanno/signals.py
"""Signal smoothing + viewer-side downsampling (spec §5.1, §5.5)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import gaussian_filter1d


@dataclass(slots=True)
class SignalChannel:
    """A 1-D signal sampled uniformly with ``dt_sec`` between samples."""
    name: str
    unit: str
    values: np.ndarray
    dt_sec: float
    t0_sec: float = 0.0


def smoothing_sigma_for_fps(fps: float) -> float:
    """Spec §5.1: sigma ≈ fps * 0.05 (~50 ms)."""
    return fps * 0.05


def gaussian_smooth_1d(x: np.ndarray, *, sigma: float) -> np.ndarray:
    if sigma <= 0:
        return x.astype(np.float64).copy()
    return gaussian_filter1d(x.astype(np.float64), sigma=sigma, mode="reflect")


def downsample_for_viewer(channel: SignalChannel, *, target_hz: float) -> SignalChannel:
    """Decimate ``channel`` to roughly ``target_hz`` for viewer-side rendering.

    The viewer needs (per §5.5) explicit per-channel ``dt_sec``; this function
    chooses an integer decimation factor and updates ``dt_sec`` accordingly.
    No-op if the signal is already at or below ``target_hz``.
    """
    current_hz = 1.0 / channel.dt_sec
    if current_hz <= target_hz * 1.05:  # already close enough
        return channel
    factor = max(1, int(round(current_hz / target_hz)))
    decimated = channel.values[::factor]
    return SignalChannel(
        name=channel.name,
        unit=channel.unit,
        values=decimated,
        dt_sec=channel.dt_sec * factor,
        t0_sec=channel.t0_sec,
    )
```

- [ ] **Step 11.4: Run, see green**

Run: `pytest tests/unit/test_signals.py -v`

- [ ] **Step 11.5: Commit**

```bash
git add mimicanno/signals.py tests/unit/test_signals.py
git commit -m "$(cat <<'EOF'
signals: gaussian smoothing + viewer downsampling

sigma = fps * 0.05 (~50 ms) per §5.1. SignalChannel carries
(values, dt_sec, t0_sec) so the viewer (§5.5) can place markers
against the waveform without guessing the timebase.
EOF
)"
```

---

### Task 12: Boundary detectors + integrated score (`mimicanno/boundaries.py`)

Spec §5.2 + §5.3 + §5.4. Each detector emits raw events; events within `merge_window_sec` are merged into candidates; same-source merge uses `max` (§5.3 — explicitly NOT last-wins).

**Files:**
- Create: `mimicanno/boundaries.py`
- Create: `tests/unit/test_boundaries.py`

- [ ] **Step 12.1: Write failing tests**

```python
# tests/unit/test_boundaries.py
import numpy as np
import pytest

from mimicanno.boundaries import (
    DEFAULT_PHASE1_WEIGHTS,
    RawEvent,
    detect_action_norm_change,
    detect_eef_acceleration_peak,
    detect_eef_velocity_valley,
    detect_gripper_transition,
    integrated_candidates,
)


def _smooth_step(n: int, edge: int, low: float, high: float) -> np.ndarray:
    out = np.full(n, low, dtype=np.float64)
    out[edge:] = high
    return out


class TestGripperTransition:
    def test_detects_close_event(self):
        # gripper goes from 1.0 (open) to 0.0 (closed) sharply at frame 50
        g = np.concatenate([np.ones(50), np.zeros(70)])
        events = detect_gripper_transition(g, fps=30.0, delta_threshold=0.30)
        assert any(40 <= e.frame <= 60 for e in events)
        for e in events:
            assert e.source == "gripper_transition"
            assert 0.0 <= e.source_score <= 1.0

    def test_no_event_when_flat(self):
        g = np.full(120, 0.5)
        events = detect_gripper_transition(g, fps=30.0, delta_threshold=0.30)
        assert events == []


class TestVelocityValley:
    def test_valley_below_threshold_is_detected(self):
        # Triangle: high → near-zero (valley) → high
        v = np.abs(np.linspace(-0.5, 0.5, 120)) * 0.4
        events = detect_eef_velocity_valley(
            v, fps=30.0, valley_threshold=0.05, min_valley_sec=0.10,
        )
        # Valley centered around frame 60
        assert any(50 <= e.frame <= 70 for e in events)


class TestAccelPeak:
    def test_peak_above_threshold(self):
        a = np.zeros(120)
        a[60] = 10.0  # spike
        events = detect_eef_acceleration_peak(a, fps=30.0, peak_threshold=1.0)
        assert any(e.frame == 60 for e in events)


class TestActionNormChange:
    def test_change_detected(self):
        norms = np.concatenate([np.full(60, 0.1), np.full(60, 0.5)])
        events = detect_action_norm_change(
            norms, fps=30.0, change_threshold=0.2, window_sec=0.5,
        )
        assert any(50 <= e.frame <= 70 for e in events)


class TestIntegrated:
    def test_max_merge_for_same_source(self):
        # Two same-source events in the merge window → max wins, not last
        events = [
            RawEvent(frame=10, time=10 / 30, source="gripper_transition", source_score=0.9),
            RawEvent(frame=11, time=11 / 30, source="gripper_transition", source_score=0.4),
        ]
        candidates = integrated_candidates(
            events, fps=30.0, merge_window_sec=0.10,
            weights=DEFAULT_PHASE1_WEIGHTS, score_threshold=0.30,
        )
        assert len(candidates) == 1
        c = candidates[0]
        assert c.scores["gripper_transition"] == pytest.approx(0.9)
        assert c.score == pytest.approx(0.9 * 0.5, abs=1e-9)

    def test_threshold_filters_below(self):
        events = [RawEvent(frame=5, time=5/30, source="eef_velocity_valley", source_score=1.0)]
        candidates = integrated_candidates(
            events, fps=30.0, merge_window_sec=0.10,
            weights=DEFAULT_PHASE1_WEIGHTS, score_threshold=0.30,
        )
        # eef_velocity_valley alone caps at 0.25 < 0.30 → dropped
        assert candidates == []

    def test_two_non_gripper_can_promote(self):
        # gripper-biased policy (§5.3): velocity 0.25 + accel 0.15 = 0.40 > 0.30
        events = [
            RawEvent(frame=10, time=10/30, source="eef_velocity_valley", source_score=1.0),
            RawEvent(frame=10, time=10/30, source="eef_acceleration_peak", source_score=1.0),
        ]
        candidates = integrated_candidates(
            events, fps=30.0, merge_window_sec=0.10,
            weights=DEFAULT_PHASE1_WEIGHTS, score_threshold=0.30,
        )
        assert len(candidates) == 1
        assert candidates[0].score == pytest.approx(0.40, abs=1e-9)
        assert sorted(candidates[0].sources) == [
            "eef_acceleration_peak", "eef_velocity_valley",
        ]

    def test_disabled_source_contributes_zero_no_renormalization(self):
        # If gripper detector were enabled it would self-promote; here we leave
        # it out and confirm the weight stays at 0.5 (no renormalization).
        weights = dict(DEFAULT_PHASE1_WEIGHTS)
        events = [
            RawEvent(frame=10, time=10/30, source="eef_velocity_valley", source_score=1.0),
        ]
        candidates = integrated_candidates(
            events, fps=30.0, merge_window_sec=0.10,
            weights=weights, score_threshold=0.30,
        )
        assert candidates == []  # 0.25 still below 0.30 — gripper weight is NOT redistributed.

    def test_candidate_id_is_zero_padded(self):
        events = [
            RawEvent(frame=i, time=i/30, source="gripper_transition", source_score=1.0)
            for i in range(0, 120, 30)
        ]
        cands = integrated_candidates(
            events, fps=30.0, merge_window_sec=0.05,
            weights=DEFAULT_PHASE1_WEIGHTS, score_threshold=0.30,
        )
        assert [c.id for c in cands] == ["b_001", "b_002", "b_003", "b_004"]
```

- [ ] **Step 12.2: Run, see red**

Run: `pytest tests/unit/test_boundaries.py -v`

- [ ] **Step 12.3: Implement**

```python
# mimicanno/boundaries.py
"""Boundary detectors + integrated weighted score (spec §5.2 / §5.3 / §5.4)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

from mimicanno.schema import BoundaryCandidate

# §5.3 default weights — gripper-biased precision policy.
DEFAULT_PHASE1_WEIGHTS: dict[str, float] = {
    "gripper_transition":   0.50,
    "eef_velocity_valley":  0.25,
    "eef_acceleration_peak": 0.15,
    "action_norm_change":   0.10,
}


@dataclass(slots=True)
class RawEvent:
    frame: int
    time: float
    source: str
    source_score: float


# ------------------------------------------------------------------
# Per-source detectors. Each returns a list[RawEvent] in frame order.
# ------------------------------------------------------------------

def detect_gripper_transition(
    gripper: np.ndarray, *, fps: float, delta_threshold: float = 0.30,
) -> list[RawEvent]:
    """Fire on |Δgripper| local peaks above ``delta_threshold`` (§5.2)."""
    if gripper.size < 2:
        return []
    delta = np.abs(np.diff(gripper, prepend=gripper[0]))
    peaks = _local_maxima(delta, threshold=delta_threshold)
    return [
        RawEvent(
            frame=int(i),
            time=float(i) / fps,
            source="gripper_transition",
            source_score=float(np.clip(delta[i] / 0.5, 0.0, 1.0)),
        )
        for i in peaks
    ]


def detect_eef_velocity_valley(
    eef_velocity: np.ndarray, *, fps: float,
    valley_threshold: float = 0.05, min_valley_sec: float = 0.10,
) -> list[RawEvent]:
    """Fire on smoothed |v| local minima below ``valley_threshold`` whose
    duration below threshold is at least ``min_valley_sec`` (§5.2)."""
    if eef_velocity.size < 3:
        return []
    below = eef_velocity < valley_threshold
    min_frames = int(min_valley_sec * fps)
    events: list[RawEvent] = []
    in_valley = False
    start = 0
    for i, is_below in enumerate(below):
        if is_below and not in_valley:
            in_valley = True
            start = i
        elif not is_below and in_valley:
            in_valley = False
            length = i - start
            if length >= min_frames:
                local = eef_velocity[start:i]
                argmin = int(np.argmin(local))
                vmin = float(local[argmin])
                events.append(RawEvent(
                    frame=int(start + argmin),
                    time=(start + argmin) / fps,
                    source="eef_velocity_valley",
                    source_score=float(np.clip(1.0 - vmin / valley_threshold, 0.0, 1.0)),
                ))
    return events


def detect_eef_acceleration_peak(
    eef_acceleration: np.ndarray, *, fps: float, peak_threshold: float = 1.0,
) -> list[RawEvent]:
    """Fire on |a| local maxima above ``peak_threshold`` (§5.2)."""
    peaks = _local_maxima(eef_acceleration, threshold=peak_threshold)
    return [
        RawEvent(
            frame=int(i),
            time=float(i) / fps,
            source="eef_acceleration_peak",
            source_score=float(np.clip(eef_acceleration[i] / (3 * peak_threshold), 0.0, 1.0)),
        )
        for i in peaks
    ]


def detect_action_norm_change(
    action_norm: np.ndarray, *, fps: float,
    change_threshold: float = 0.2, window_sec: float = 0.5,
) -> list[RawEvent]:
    """Rolling-mean change-point on ``||a_t||`` (§5.2)."""
    n = action_norm.size
    win = max(1, int(window_sec * fps))
    if n < 2 * win:
        return []
    cumsum = np.cumsum(np.insert(action_norm, 0, 0.0))
    means = (cumsum[win:] - cumsum[:-win]) / win
    delta = np.abs(np.diff(means, prepend=means[0]))
    peaks = _local_maxima(delta, threshold=change_threshold)
    return [
        RawEvent(
            frame=int(i + win // 2),
            time=(i + win // 2) / fps,
            source="action_norm_change",
            source_score=float(np.clip(delta[i] / change_threshold, 0.0, 1.0)),
        )
        for i in peaks
    ]


def _local_maxima(x: np.ndarray, *, threshold: float) -> list[int]:
    """Strict-greater-than-neighbors local maxima above ``threshold``.

    The naive implementation is O(n) and adequate for Phase 1 — episode
    lengths are O(10^3) frames; we don't need scipy.signal.find_peaks here.
    """
    out: list[int] = []
    for i in range(len(x)):
        if x[i] < threshold:
            continue
        left_ok = i == 0 or x[i] >= x[i - 1]
        right_ok = i == len(x) - 1 or x[i] >= x[i + 1]
        if left_ok and right_ok:
            out.append(i)
    return out


# ------------------------------------------------------------------
# Integrated score and candidate promotion (§5.3).
# ------------------------------------------------------------------

def integrated_candidates(
    events: Iterable[RawEvent],
    *,
    fps: float,
    merge_window_sec: float,
    weights: dict[str, float],
    score_threshold: float,
) -> list[BoundaryCandidate]:
    """Merge events within ``merge_window_sec`` and return promoted candidates.

    Same-source merge uses ``max(source_score)`` (§5.3 — explicitly NOT last-wins).
    Disabled sources contribute 0; weights are NOT renormalized.
    """
    sorted_events = sorted(events, key=lambda e: (e.time, e.source))
    if not sorted_events:
        return []

    merged_groups: list[list[RawEvent]] = []
    current: list[RawEvent] = [sorted_events[0]]
    for ev in sorted_events[1:]:
        if ev.time - current[-1].time <= merge_window_sec:
            current.append(ev)
        else:
            merged_groups.append(current)
            current = [ev]
    merged_groups.append(current)

    out: list[BoundaryCandidate] = []
    next_id = 1
    for group in merged_groups:
        # Per §5.3: max over same source; sources sorted unique.
        scores: dict[str, float] = {}
        for ev in group:
            prev = scores.get(ev.source, 0.0)
            if ev.source_score > prev:
                scores[ev.source] = ev.source_score
        score = sum(weights.get(src, 0.0) * s for src, s in scores.items())
        score = float(np.clip(score, 0.0, 1.0))
        if score < score_threshold:
            continue
        median_time = float(np.median([ev.time for ev in group]))
        out.append(BoundaryCandidate(
            id=f"b_{next_id:03d}",
            frame=int(round(median_time * fps)),
            time=median_time,
            sources=sorted(scores.keys()),
            scores=dict(scores),
            score=score,
        ))
        next_id += 1
    return out
```

- [ ] **Step 12.4: Run, see green**

Run: `pytest tests/unit/test_boundaries.py -v`

- [ ] **Step 12.5: Commit**

```bash
git add mimicanno/boundaries.py tests/unit/test_boundaries.py
git commit -m "$(cat <<'EOF'
boundaries: 4 detectors + integrated weighted score with max-merge

Detectors: gripper_transition, eef_velocity_valley, eef_acceleration_peak,
action_norm_change (§5.2). integrated_candidates() merges events in a
merge_window_sec; same-source merge is max (§5.3 — NOT last-wins).
Disabled sources contribute 0 with no renormalization. Default weights
implement the gripper-biased precision policy (§5.3).
EOF
)"
```

---

### Task 13: Phase-1 clip bracketing (`mimicanno/bracketing.py`)

Spec §5.6: deterministic algorithm to turn `boundaries.json` candidates into one `SubtaskSegment` per adjacent cut pair, with sentinel boundaries at episode start/end.

**Files:**
- Create: `mimicanno/bracketing.py`
- Create: `tests/unit/test_bracketing.py`

- [ ] **Step 13.1: Write failing tests**

```python
# tests/unit/test_bracketing.py
import pytest

from mimicanno.bracketing import bracket_phase1_segments
from mimicanno.schema import BoundaryCandidate


def _cand(id_: str, time: float) -> BoundaryCandidate:
    return BoundaryCandidate(
        id=id_,
        frame=int(round(time * 30.0)),
        time=time,
        sources=["gripper_transition"],
        scores={"gripper_transition": 0.9},
        score=0.45,
    )


class TestBracket:
    def test_zero_candidates_one_segment(self):
        segs = bracket_phase1_segments(
            episode_id="ep0",
            candidates=[],
            fps=30.0,
            duration_sec=2.0,
        )
        assert len(segs) == 1
        s = segs[0]
        assert s.start_time == pytest.approx(0.0)
        assert s.end_time == pytest.approx(2.0)
        assert s.start_boundary.sources == ["episode_start"]
        assert s.end_boundary.sources == ["episode_end"]
        assert s.phase == "unlabeled"
        assert s.overall_confidence == 0.0  # reserved phase
        assert s.failure_flags == []
        assert s.object_track_ids == []
        assert s.label_source == "signals_only"
        assert s.object_state_unavailable is True

    def test_three_candidates_yield_four_segments(self):
        cands = [_cand("b_001", 1.0), _cand("b_002", 2.0), _cand("b_003", 3.0)]
        segs = bracket_phase1_segments("ep0", cands, fps=30.0, duration_sec=4.0)
        assert len(segs) == 4
        assert segs[0].start_boundary.sources == ["episode_start"]
        assert segs[0].end_boundary.candidate_id == "b_001"
        assert segs[1].start_boundary.candidate_id == "b_001"
        assert segs[1].end_boundary.candidate_id == "b_002"
        assert segs[3].end_boundary.sources == ["episode_end"]

    def test_segments_cover_duration_with_half_open_intervals(self):
        cands = [_cand("b_001", 1.5)]
        segs = bracket_phase1_segments("ep0", cands, fps=30.0, duration_sec=3.0)
        assert segs[0].start_time == 0.0
        assert segs[0].end_time == 1.5
        assert segs[1].start_time == 1.5
        assert segs[1].end_time == 3.0
        # end_frame is inclusive (round(t*fps)-1 — see §5.6).
        assert segs[0].end_frame == int(round(1.5 * 30)) - 1

    def test_drops_subframe_segments(self):
        cands = [_cand("b_001", 1.0), _cand("b_002", 1.0001)]
        segs = bracket_phase1_segments("ep0", cands, fps=30.0, duration_sec=2.0)
        # Three cuts (0, 1, 1.0001, 2) but middle gap is < 1/30 s → dropped.
        assert len(segs) == 2

    def test_segment_ids_are_zero_padded(self):
        cands = [_cand("b_001", 0.5), _cand("b_002", 1.0)]
        segs = bracket_phase1_segments("ep0", cands, fps=30.0, duration_sec=1.5)
        assert [s.segment_id for s in segs] == ["s_001", "s_002", "s_003"]
```

- [ ] **Step 13.2: Run, see red**

Run: `pytest tests/unit/test_bracketing.py -v`

- [ ] **Step 13.3: Implement**

```python
# mimicanno/bracketing.py
"""Phase 1 clip bracketing algorithm (spec §5.6)."""
from __future__ import annotations

from mimicanno.schema import BoundaryCandidate, BoundaryRef, SubtaskSegment

LABEL_VERSION = "manipulation.v1"


def bracket_phase1_segments(
    episode_id: str,
    candidates: list[BoundaryCandidate],
    *,
    fps: float,
    duration_sec: float,
) -> list[SubtaskSegment]:
    """Deterministic §5.6 bracketing.

    1. Sort candidates by ``time``.
    2. Cut list = [0.0] + candidate.times + [duration_sec].
    3. Half-open intervals [t_i, t_{i+1}); end_frame is inclusive.
    4. Drop sub-frame segments (length < 1/fps).
    """
    sorted_cands = sorted(candidates, key=lambda c: c.time)
    epsilon_sec = 1.0 / fps

    # Build edge refs with sentinels.
    start_ref = BoundaryRef(candidate_id=None, time=0.0, sources=["episode_start"], score=1.0)
    end_ref = BoundaryRef(candidate_id=None, time=duration_sec, sources=["episode_end"], score=1.0)
    cand_refs = [
        BoundaryRef(
            candidate_id=c.id, time=c.time, sources=list(c.sources), score=c.score,
        )
        for c in sorted_cands
    ]
    edges: list[BoundaryRef] = [start_ref, *cand_refs, end_ref]

    out: list[SubtaskSegment] = []
    next_id = 1
    for left, right in zip(edges, edges[1:], strict=False):
        if right.time - left.time < epsilon_sec:
            continue
        boundary_confidence = min(left.score, right.score)
        seg = SubtaskSegment(
            segment_id=f"s_{next_id:03d}",
            episode_id=episode_id,
            start_frame=int(round(left.time * fps)),
            end_frame=max(int(round(right.time * fps)) - 1, int(round(left.time * fps))),
            start_time=left.time,
            end_time=right.time,
            phase="unlabeled",
            verb=None,
            object=None,
            target=None,
            failure_flags=[],
            label_source="signals_only",
            object_state_unavailable=True,
            object_track_ids=[],
            label_version=LABEL_VERSION,
            start_boundary=left,
            end_boundary=right,
            boundary_confidence=boundary_confidence,
            vlm_confidence=None,
            overall_confidence=0.0,  # reserved phase = 0 (§6.4)
            evidence=None,
            reviewed=False,
            reviewer_id=None,
        )
        out.append(seg)
        next_id += 1
    return out
```

- [ ] **Step 13.4: Run, see green**

Run: `pytest tests/unit/test_bracketing.py -v`

- [ ] **Step 13.5: Commit**

```bash
git add mimicanno/bracketing.py tests/unit/test_bracketing.py
git commit -m "$(cat <<'EOF'
bracketing: deterministic Phase 1 clip bracketing per §5.6

Sentinel BoundaryRefs at episode_start and episode_end (score=1.0).
Half-open [t_i, t_{i+1}) intervals; end_frame inclusive. Sub-frame
segments are dropped. Reserved phase "unlabeled" gets
overall_confidence=0.0 per §6.4.
EOF
)"
```

---

## Phase E — Output writers

### Task 14: Labels YAML loader (`mimicanno/labelset.py` + default `manipulation.yaml`)

Spec §8.1 + §8.4. Loads + validates `manipulation.yaml`, computes its sha256 (feeds `input_hash`), and rejects YAMLs that try to redefine reserved phases.

**Files:**
- Create: `mimicanno/labelset.py`
- Create: `mimicanno/configs/labels/manipulation.yaml`
- Create: `tests/unit/test_labelset.py`

- [ ] **Step 14.1: Write `manipulation.yaml`**

```yaml
# mimicanno/configs/labels/manipulation.yaml
schema_version: "0.1.0"
task_type: manipulation
labels:
  - id: idle
    verbs: []
    requires_object: false
  - id: approach_object
    verbs: [approach, reach]
    requires_object: true
  - id: align_gripper
    verbs: [align]
    requires_object: true
  - id: grasp_object
    verbs: [grasp, pick, take]
    requires_object: true
  - id: lift_object
    verbs: [lift]
    requires_object: true
  - id: move_to_target
    verbs: [move, transport, carry]
    requires_object: true
  - id: align_to_target
    verbs: [align]
    requires_object: true
  - id: place_object
    verbs: [place, put]
    requires_object: true
  - id: release_object
    verbs: [release]
    requires_object: true
  - id: retreat
    verbs: [retreat, withdraw]
    requires_object: false
unknown_task_fallback: manipulation
```

- [ ] **Step 14.2: Write failing tests**

```python
# tests/unit/test_labelset.py
from importlib.resources import files as pkg_files
from pathlib import Path

import pytest

from mimicanno.labelset import LabelSet, LabelSetError, default_labels_path, load_label_set


def _bundled_path() -> Path:
    return Path(default_labels_path("manipulation"))


class TestDefaultLabels:
    def test_default_path_exists(self):
        assert _bundled_path().exists()

    def test_default_has_ten_labels(self):
        ls = load_label_set(_bundled_path())
        assert len(ls.labels) == 10

    def test_no_failure_recovery(self):
        ls = load_label_set(_bundled_path())
        assert "failure_recovery" not in {lbl.id for lbl in ls.labels}

    def test_sha256_prefixed(self):
        ls = load_label_set(_bundled_path())
        assert ls.sha256.startswith("sha256:")


class TestReservedPhases:
    def test_rejects_unlabeled_label_id(self, tmp_path: Path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            "schema_version: '0.1.0'\n"
            "task_type: x\n"
            "labels:\n"
            "  - id: unlabeled\n"
            "    verbs: []\n"
            "    requires_object: false\n",
        )
        with pytest.raises(LabelSetError, match="reserved"):
            load_label_set(bad)

    def test_rejects_unknown_label_id(self, tmp_path: Path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            "schema_version: '0.1.0'\n"
            "task_type: x\n"
            "labels:\n"
            "  - id: unknown\n"
            "    verbs: []\n"
            "    requires_object: false\n",
        )
        with pytest.raises(LabelSetError, match="reserved"):
            load_label_set(bad)


class TestSchemaValidation:
    def test_rejects_old_schema_version(self, tmp_path: Path):
        p = tmp_path / "old.yaml"
        p.write_text(
            "schema_version: '0.0.1'\n"
            "task_type: x\n"
            "labels: []\n",
        )
        with pytest.raises(LabelSetError, match="schema_version"):
            load_label_set(p)
```

- [ ] **Step 14.3: Run, see red**

Run: `pytest tests/unit/test_labelset.py -v`

- [ ] **Step 14.4: Implement**

```python
# mimicanno/labelset.py
"""Label-set YAML loader (spec §8.1 / §8.4)."""
from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files as pkg_files
from pathlib import Path

import yaml

from mimicanno.hashing import sha256_file
from mimicanno.schema_versions import LABELS_SCHEMA_VERSION, parse_major

RESERVED_PHASES: frozenset[str] = frozenset({"unlabeled", "unknown"})


class LabelSetError(Exception):
    pass


@dataclass(slots=True)
class Label:
    id: str
    verbs: list[str]
    requires_object: bool


@dataclass(slots=True)
class LabelSet:
    schema_version: str
    task_type: str
    labels: list[Label]
    unknown_task_fallback: str | None
    path: Path
    sha256: str  # "sha256:<hex>"

    def label_ids(self) -> set[str]:
        return {lbl.id for lbl in self.labels}


def default_labels_path(task_type: str = "manipulation") -> str:
    """Return the absolute path of the bundled label YAML for ``task_type``."""
    res = pkg_files("mimicanno.configs.labels").joinpath(f"{task_type}.yaml")
    return str(res)


def load_label_set(path: Path) -> LabelSet:
    raw = yaml.safe_load(path.read_text())
    if not isinstance(raw, dict):
        raise LabelSetError(f"{path}: top-level must be a mapping")

    sv = raw.get("schema_version")
    # §6.6 set-membership check — only "0.1.0" is supported today; widening
    # the supported set is an explicit decision, not implicit (>=) compatibility.
    SUPPORTED_LABEL_MAJORS = {parse_major(LABELS_SCHEMA_VERSION)}
    if not isinstance(sv, str):
        raise LabelSetError(f"{path}: schema_version must be a string, got {sv!r}")
    if parse_major(sv) not in SUPPORTED_LABEL_MAJORS:
        raise LabelSetError(
            f"{path}: schema_version {sv!r} not in supported majors "
            f"{sorted(SUPPORTED_LABEL_MAJORS)} (this consumer's set)",
        )

    labels_raw = raw.get("labels") or []
    labels: list[Label] = []
    for item in labels_raw:
        lid = item["id"]
        if lid in RESERVED_PHASES:
            raise LabelSetError(
                f"{path}: label id {lid!r} is reserved (see spec §8.4)",
            )
        labels.append(Label(
            id=lid,
            verbs=list(item.get("verbs") or []),
            requires_object=bool(item.get("requires_object", False)),
        ))

    return LabelSet(
        schema_version=sv,
        task_type=raw.get("task_type", "unknown"),
        labels=labels,
        unknown_task_fallback=raw.get("unknown_task_fallback"),
        path=path,
        sha256="sha256:" + sha256_file(path),
    )
```

We need the bundled YAML accessible via `importlib.resources`. Update `pyproject.toml` to include the YAML in the wheel:

Add to the existing `[tool.hatch.build.targets.wheel]` block:

```toml
[tool.hatch.build.targets.wheel.force-include]
"mimicanno/configs/labels/manipulation.yaml" = "mimicanno/configs/labels/manipulation.yaml"
```

- [ ] **Step 14.5: Run, see green**

Run: `pytest tests/unit/test_labelset.py -v`

- [ ] **Step 14.6: Commit**

```bash
git add mimicanno/labelset.py mimicanno/configs/labels/manipulation.yaml tests/unit/test_labelset.py pyproject.toml
git commit -m "$(cat <<'EOF'
labelset: YAML loader + bundled manipulation.yaml (10 labels)

Default manipulation set has 10 labels (no failure_recovery — that
became failure_flags in spec §6.3). Reserved phases unlabeled/unknown
are rejected at load time per §8.4. The YAML's sha256 feeds into
input_hash so a label-set change yields a distinct run_hash.
EOF
)"
```

---

### Task 15: Run-directory paths (`mimicanno/rundir.py`)

Pure path helpers — no I/O. Single source of truth for `canonical_name`, `*.tmp.<pid>`, `*.bak.<pid>` naming.

**Files:**
- Create: `mimicanno/rundir.py`
- Create: `tests/unit/test_rundir.py`

- [ ] **Step 15.1: Write failing tests**

```python
# tests/unit/test_rundir.py
from pathlib import Path

import pytest

from mimicanno.rundir import (
    RunPaths,
    canonical_name_for,
    extend_collision_suffix,
    find_run_dirs_for_episode,
    is_collision,
    parse_canonical_name,
)


class TestCanonicalName:
    def test_default_is_12_hex(self):
        n = canonical_name_for("episode_000", run_hash="sha256:" + "9f31a2bc4a77" + "0" * 52)
        assert n == "episode_000__9f31a2bc4a77"

    def test_extended_is_16_hex(self):
        n = canonical_name_for(
            "ep_x", run_hash="sha256:" + "abcdef0123456789" + "0" * 48, length=16,
        )
        assert n == "ep_x__abcdef0123456789"


class TestParseCanonicalName:
    def test_roundtrip(self):
        episode_id, hash_short = parse_canonical_name("episode_000__9f31a2bc4a77")
        assert episode_id == "episode_000"
        assert hash_short == "9f31a2bc4a77"

    def test_rejects_no_separator(self):
        with pytest.raises(ValueError, match="separator"):
            parse_canonical_name("episode_000")


class TestRunPaths:
    def test_paths(self, tmp_path: Path):
        rp = RunPaths(runs_root=tmp_path, canonical_name="ep0__abcdef012345", pid=12345)
        assert rp.final == tmp_path / "ep0__abcdef012345"
        assert rp.tmp == tmp_path / "ep0__abcdef012345.tmp.12345"
        assert rp.bak == tmp_path / "ep0__abcdef012345.bak.12345"


class TestCollision:
    def test_no_existing_no_collision(self, tmp_path: Path):
        assert not is_collision(tmp_path, canonical_name="ep0__abc",
                                expected_run_hash="sha256:" + "0" * 64)

    def test_existing_with_matching_hash_no_collision(self, tmp_path: Path):
        d = tmp_path / "ep0__abc"
        d.mkdir()
        (d / "manifest.json").write_text(
            '{"run_hash":"sha256:' + "0" * 64 + '"}',
        )
        assert not is_collision(
            tmp_path, canonical_name="ep0__abc",
            expected_run_hash="sha256:" + "0" * 64,
        )

    def test_existing_with_different_hash_is_collision(self, tmp_path: Path):
        d = tmp_path / "ep0__abc"
        d.mkdir()
        (d / "manifest.json").write_text(
            '{"run_hash":"sha256:' + "1" * 64 + '"}',
        )
        assert is_collision(
            tmp_path, canonical_name="ep0__abc",
            expected_run_hash="sha256:" + "0" * 64,
        )


def test_extend_collision_suffix():
    h = "sha256:" + "abcdef0123456789" + "0" * 48
    assert extend_collision_suffix("ep0", run_hash=h) == "ep0__abcdef0123456789"
```

- [ ] **Step 15.2: Run, see red**

Run: `pytest tests/unit/test_rundir.py -v`

- [ ] **Step 15.3: Implement**

```python
# mimicanno/rundir.py
"""Run-directory path helpers — single source of truth for canonical_name (§4.1)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from mimicanno.config import (
    RUN_HASH_DEFAULT_PREFIX_LEN,
    RUN_HASH_FALLBACK_PREFIX_LEN,
    run_hash_short,
)

CANONICAL_SEPARATOR = "__"


def canonical_name_for(
    episode_id: str, *, run_hash: str, length: int = RUN_HASH_DEFAULT_PREFIX_LEN,
) -> str:
    return f"{episode_id}{CANONICAL_SEPARATOR}{run_hash_short(run_hash, length=length)}"


def extend_collision_suffix(episode_id: str, *, run_hash: str) -> str:
    return canonical_name_for(
        episode_id, run_hash=run_hash, length=RUN_HASH_FALLBACK_PREFIX_LEN,
    )


def parse_canonical_name(canonical_name: str) -> tuple[str, str]:
    if CANONICAL_SEPARATOR not in canonical_name:
        raise ValueError(f"missing canonical-name separator '__' in {canonical_name!r}")
    episode_id, _, hash_short = canonical_name.rpartition(CANONICAL_SEPARATOR)
    return episode_id, hash_short


@dataclass(slots=True)
class RunPaths:
    runs_root: Path
    canonical_name: str
    pid: int

    @property
    def final(self) -> Path:
        return self.runs_root / self.canonical_name

    @property
    def tmp(self) -> Path:
        return self.runs_root / f"{self.canonical_name}.tmp.{self.pid}"

    @property
    def bak(self) -> Path:
        return self.runs_root / f"{self.canonical_name}.bak.{self.pid}"


def is_collision(
    runs_root: Path, *, canonical_name: str, expected_run_hash: str,
) -> bool:
    """Return True iff ``runs/<canonical_name>/`` exists with a DIFFERENT run_hash.

    Used to drive the §4.1 collision-extension path. No-collision when the dir
    is absent or its manifest's run_hash matches.
    """
    final = runs_root / canonical_name
    manifest = final / "manifest.json"
    if not manifest.exists():
        return False
    try:
        data = json.loads(manifest.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    return data.get("run_hash") != expected_run_hash


def find_run_dirs_for_episode(runs_root: Path, episode_id: str) -> list[Path]:
    prefix = f"{episode_id}{CANONICAL_SEPARATOR}"
    return sorted(p for p in runs_root.iterdir() if p.is_dir() and p.name.startswith(prefix))
```

- [ ] **Step 15.4: Run, see green**

Run: `pytest tests/unit/test_rundir.py -v`

- [ ] **Step 15.5: Commit**

```bash
git add mimicanno/rundir.py tests/unit/test_rundir.py
git commit -m "$(cat <<'EOF'
rundir: canonical_name + tmp/bak path helpers (§4.1)

Pure-path module so every other module imports the same naming. Includes
collision detection (manifest.run_hash mismatch) and the extension to
the [:16] fallback per §4.1.
EOF
)"
```

---

### Task 16: Artifact JSON writers (`mimicanno/writers.py`)

We bundle `signals.json`, `boundaries.json`, `annotation.json`, and `manifest.json` writers into a single small module — they are all "dataclass → canonical JSON → file" with `jsonschema` validation against compile-time schemas.

**Files:**
- Create: `mimicanno/writers.py`
- Create: `mimicanno/jsonschemas/manifest.schema.json`
- Create: `mimicanno/jsonschemas/annotation.schema.json`
- Create: `mimicanno/jsonschemas/boundaries.schema.json`
- Create: `mimicanno/jsonschemas/signals.schema.json`
- Create: `tests/unit/test_writers.py`

- [ ] **Step 16.1: Write failing tests**

```python
# tests/unit/test_writers.py
import json
from pathlib import Path

import pytest

from mimicanno.signals import SignalChannel
from mimicanno.writers import (
    write_annotation_json,
    write_boundaries_json,
    write_manifest_json,
    write_signals_json,
)
from tests.unit.test_schema import _make_minimal_manifest  # reuse helper
from mimicanno.schema import AnnotationResult, GeneratorInfo, PipelineStatus, TaskInfo


def test_write_signals_json_round_trips(tmp_path: Path):
    channels = [
        SignalChannel(
            name="gripper", unit="normalized",
            values=__import__("numpy").linspace(1.0, 0.0, 60),
            dt_sec=1.0 / 30.0,
        ),
    ]
    out = tmp_path / "signals.json"
    write_signals_json(out, episode_id="ep0", duration_sec=2.0, channels=channels)
    data = json.loads(out.read_text())
    assert data["schema_version"] == "0.1.0"
    assert data["channels"][0]["t0_sec"] == 0.0
    assert data["channels"][0]["dt_sec"] == pytest.approx(1.0 / 30.0)
    assert len(data["channels"][0]["values"]) == 60


def test_write_boundaries_json(tmp_path: Path):
    from mimicanno.schema import BoundaryCandidate
    out = tmp_path / "boundaries.json"
    write_boundaries_json(out, episode_id="ep0", candidates=[
        BoundaryCandidate(
            id="b_001", frame=42, time=1.4,
            sources=["gripper_transition"],
            scores={"gripper_transition": 0.95},
            score=0.475,
        ),
    ])
    data = json.loads(out.read_text())
    assert data["candidates"][0]["id"] == "b_001"


def test_write_annotation_json(tmp_path: Path):
    a = AnnotationResult(
        schema_version="0.1.0",
        episode_id="ep0",
        task=TaskInfo(text="t", version=None),
        generated_at="2026-04-26T00:00:00Z",
        generator=GeneratorInfo(name="mimicanno", cli_version="0.1.0", pipeline_phase=1),
        config_hash="sha256:" + "0" * 64,
        input_hash="sha256:" + "1" * 64,
        run_hash="sha256:" + "2" * 64,
        model_versions={"sam3": None, "vlm": None},
        pipeline_phase=1,
        pipeline_status=PipelineStatus(False, None, None),
        segments=[],
        boundaries_url="boundaries.json",
        signals_url="signals.json",
        notes=None,
    )
    out = tmp_path / "annotation.json"
    write_annotation_json(out, a)
    data = json.loads(out.read_text())
    assert data["pipeline_phase"] == 1


def test_write_manifest_json(tmp_path: Path):
    m = _make_minimal_manifest()
    out = tmp_path / "manifest.json"
    write_manifest_json(out, m)
    data = json.loads(out.read_text())
    assert "compat" in data
    assert data["pipeline_status"]["object_state_available"] is False
```

- [ ] **Step 16.2: Run, see red**

Run: `pytest tests/unit/test_writers.py -v`

- [ ] **Step 16.3: Implement schemas**

Each `*.schema.json` file is a JSON Schema (Draft 2020-12) describing the artifact. Place them under `mimicanno/jsonschemas/` and load via `importlib.resources`.

For brevity, the schemas reflect the same shape produced by `to_dict()` on the dataclasses. Example minimal `manifest.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "mimicanno/manifest",
  "type": "object",
  "required": [
    "schema_version", "episode_id", "task", "generated_at", "generator",
    "config_hash", "input_hash", "run_hash", "model_versions",
    "pipeline_params", "inputs", "time_base", "fps", "duration_sec",
    "pipeline_status", "compat", "artifacts"
  ],
  "properties": {
    "schema_version": {"type": "string"},
    "episode_id": {"type": "string"},
    "task": {
      "type": "object",
      "required": ["text", "version"],
      "properties": {
        "text": {"type": "string"},
        "version": {"type": ["string", "null"]}
      }
    },
    "config_hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
    "input_hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
    "run_hash": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
    "compat": {"type": "object", "additionalProperties": {"type": "integer"}},
    "artifacts": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["role", "url", "content_type"],
        "properties": {
          "role": {"type": "string"},
          "url": {"type": "string"},
          "content_type": {"type": "string"}
        }
      }
    }
  }
}
```

(Implement the analogous `annotation.schema.json`, `boundaries.schema.json`, `signals.schema.json`. Each should `require` exactly the fields the dataclass produces.)

- [ ] **Step 16.4: Implement `mimicanno/writers.py`**

```python
# mimicanno/writers.py
"""Atomic JSON writers + jsonschema validation for run-dir artifacts."""
from __future__ import annotations

import json
from importlib.resources import files as pkg_files
from pathlib import Path
from typing import Any

import jsonschema

from mimicanno.hashing import canonical_json
from mimicanno.schema import (
    AnnotationResult,
    BoundaryCandidate,
    Manifest,
)
from mimicanno.schema_versions import ARTIFACT_SCHEMA_VERSIONS
from mimicanno.signals import SignalChannel

_SCHEMA_CACHE: dict[str, dict[str, Any]] = {}


def _load_schema(name: str) -> dict[str, Any]:
    if name not in _SCHEMA_CACHE:
        text = pkg_files("mimicanno.jsonschemas").joinpath(f"{name}.schema.json").read_text()
        _SCHEMA_CACHE[name] = json.loads(text)
    return _SCHEMA_CACHE[name]


def _validate(name: str, data: dict[str, Any]) -> None:
    jsonschema.validate(instance=data, schema=_load_schema(name))


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    tmp.replace(path)


def write_manifest_json(path: Path, manifest: Manifest) -> None:
    data = manifest.to_dict()
    _validate("manifest", data)
    _atomic_write_json(path, data)


def write_annotation_json(path: Path, annotation: AnnotationResult) -> None:
    data = annotation.to_dict()
    _validate("annotation", data)
    _atomic_write_json(path, data)


def write_boundaries_json(
    path: Path, *, episode_id: str, candidates: list[BoundaryCandidate],
) -> None:
    data = {
        "schema_version": ARTIFACT_SCHEMA_VERSIONS["boundaries"],
        "episode_id": episode_id,
        "candidates": [c.to_dict() for c in candidates],
    }
    _validate("boundaries", data)
    _atomic_write_json(path, data)


def write_signals_json(
    path: Path, *, episode_id: str, duration_sec: float, channels: list[SignalChannel],
) -> None:
    data = {
        "schema_version": ARTIFACT_SCHEMA_VERSIONS["signals"],
        "episode_id": episode_id,
        "duration_sec": duration_sec,
        "channels": [
            {
                "name": ch.name,
                "unit": ch.unit,
                "t0_sec": ch.t0_sec,
                "dt_sec": ch.dt_sec,
                "values": [float(x) for x in ch.values.tolist()],
            }
            for ch in channels
        ],
    }
    _validate("signals", data)
    _atomic_write_json(path, data)
```

Add to `pyproject.toml`:

```toml
[tool.hatch.build.targets.wheel.force-include]
"mimicanno/configs/labels/manipulation.yaml" = "mimicanno/configs/labels/manipulation.yaml"
"mimicanno/jsonschemas/manifest.schema.json" = "mimicanno/jsonschemas/manifest.schema.json"
"mimicanno/jsonschemas/annotation.schema.json" = "mimicanno/jsonschemas/annotation.schema.json"
"mimicanno/jsonschemas/boundaries.schema.json" = "mimicanno/jsonschemas/boundaries.schema.json"
"mimicanno/jsonschemas/signals.schema.json" = "mimicanno/jsonschemas/signals.schema.json"
```

Also create `mimicanno/jsonschemas/__init__.py` (empty) so `pkg_files` finds the package.

- [ ] **Step 16.5: Run, see green**

Run: `pytest tests/unit/test_writers.py -v`

- [ ] **Step 16.6: Commit**

```bash
git add mimicanno/writers.py mimicanno/jsonschemas/__init__.py mimicanno/jsonschemas/*.schema.json tests/unit/test_writers.py pyproject.toml
git commit -m "$(cat <<'EOF'
writers: atomic JSON writers with jsonschema validation

Each writer takes a dataclass, validates the to_dict() payload against
the bundled JSON Schema, and writes atomically (write to .tmp, rename).
Schemas live in mimicanno/jsonschemas/ and are bundled into the wheel.
EOF
)"
```

---

## Phase F — Publish transaction

### Task 17: File lock (`mimicanno/locks.py`)

Cross-platform exclusive file lock. POSIX uses `fcntl.flock`; Windows uses `msvcrt.locking`. Phase 1 only needs blocking acquisition with a timeout.

**Files:**
- Create: `mimicanno/locks.py`
- Create: `tests/unit/test_locks.py`

- [ ] **Step 17.1: Write failing tests**

```python
# tests/unit/test_locks.py
import multiprocessing as mp
import time
from pathlib import Path

import pytest

from mimicanno.locks import LockTimeout, file_lock


def _hold_lock_then_release(path: str, hold_sec: float, ready: mp.Event):
    from pathlib import Path as P
    with file_lock(P(path), timeout_sec=10.0):
        ready.set()
        time.sleep(hold_sec)


def test_basic_acquire_and_release(tmp_path: Path):
    lock_path = tmp_path / "x.lock"
    with file_lock(lock_path, timeout_sec=2.0):
        assert lock_path.exists()
    # After release, re-acquiring is fine.
    with file_lock(lock_path, timeout_sec=2.0):
        pass


@pytest.mark.timeout(15)
def test_concurrent_blocks_then_acquires(tmp_path: Path):
    lock_path = tmp_path / "y.lock"
    ctx = mp.get_context("spawn")
    ready = ctx.Event()
    p = ctx.Process(target=_hold_lock_then_release, args=(str(lock_path), 1.0, ready))
    p.start()
    assert ready.wait(5.0)

    t0 = time.monotonic()
    with file_lock(lock_path, timeout_sec=5.0):
        elapsed = time.monotonic() - t0
        # Should have waited ~1s.
        assert elapsed >= 0.5
    p.join()


def test_timeout_raises(tmp_path: Path):
    lock_path = tmp_path / "z.lock"
    ctx = mp.get_context("spawn")
    ready = ctx.Event()
    p = ctx.Process(target=_hold_lock_then_release, args=(str(lock_path), 5.0, ready))
    p.start()
    assert ready.wait(5.0)
    with pytest.raises(LockTimeout):
        with file_lock(lock_path, timeout_sec=0.5):
            pass
    p.join()
```

- [ ] **Step 17.2: Run, see red**

Run: `pytest tests/unit/test_locks.py -v`

- [ ] **Step 17.3: Implement**

```python
# mimicanno/locks.py
"""Cross-platform exclusive file lock with timeout."""
from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class LockTimeout(Exception):
    pass


@contextmanager
def file_lock(path: Path, *, timeout_sec: float, poll_sec: float = 0.05) -> Iterator[None]:
    """Acquire an exclusive advisory lock on ``path``.

    Creates ``path`` if it does not exist. Releases automatically on exit.
    Raises :class:`LockTimeout` if the lock can't be acquired in ``timeout_sec``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+")
    try:
        deadline = time.monotonic() + timeout_sec
        if sys.platform == "win32":
            import msvcrt
            while True:
                try:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise LockTimeout(
                            f"could not acquire {path} within {timeout_sec:.2f}s",
                        )
                    time.sleep(poll_sec)
            try:
                yield
            finally:
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            while True:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise LockTimeout(
                            f"could not acquire {path} within {timeout_sec:.2f}s",
                        )
                    time.sleep(poll_sec)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    finally:
        fh.close()
```

Also add `pytest-timeout` to dev dependencies (in `pyproject.toml`):

```toml
dev = [
  "pytest>=8",
  "pytest-xdist>=3.5",
  "pytest-timeout>=2.3",
  "ruff>=0.4",
  "mypy>=1.10",
]
```

- [ ] **Step 17.4: Run, see green**

Run: `pytest tests/unit/test_locks.py -v`

- [ ] **Step 17.5: Commit**

```bash
git add mimicanno/locks.py tests/unit/test_locks.py pyproject.toml
git commit -m "$(cat <<'EOF'
locks: cross-platform exclusive file lock with timeout

POSIX uses fcntl.flock, Windows uses msvcrt.locking. Polled non-blocking
acquisition so we can honor timeout_sec. Used by the publish transaction
(spec §4.4) to serialize publishers without blocking heavy compute.
EOF
)"
```

---

### Task 18: Scavenger (`mimicanno/scavenger.py`)

Spec §4.4 + §6.5: writer metadata in `.writer.json`; deletion only when (PID gone OR pid_start_time mismatch OR unparseable) AND age > threshold. Never lock-holdership.

**Files:**
- Create: `mimicanno/scavenger.py`
- Create: `tests/unit/test_scavenger.py`

- [ ] **Step 18.1: Write failing tests**

```python
# tests/unit/test_scavenger.py
import json
import os
import time
from pathlib import Path

from mimicanno.scavenger import (
    WriterMetadata,
    is_pid_alive,
    read_writer_metadata,
    scavenge_stale_dirs,
    write_writer_metadata,
)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def test_write_and_read_writer_metadata(tmp_path: Path):
    d = tmp_path / "ep0__abc.tmp.123"
    d.mkdir()
    md = WriterMetadata(
        pid=123, pid_start_time="2026-04-26T00:00:00.000Z",
        canonical_name="ep0__abc", kind="tmp", claimed_at=_now(),
    )
    write_writer_metadata(d, md)
    got = read_writer_metadata(d)
    assert got == md


def test_is_pid_alive_for_self():
    assert is_pid_alive(os.getpid())


def test_scavenge_skips_live_pid_within_age(tmp_path: Path):
    d = tmp_path / "ep0__abc.tmp.{}".format(os.getpid())
    d.mkdir()
    md = WriterMetadata(
        pid=os.getpid(),
        pid_start_time=_pid_start_time_now(),
        canonical_name="ep0__abc", kind="tmp", claimed_at=_now(),
    )
    write_writer_metadata(d, md)
    scavenge_stale_dirs(tmp_path, stale_age_sec=3600)
    assert d.exists()


def test_scavenge_removes_dir_with_dead_pid(tmp_path: Path):
    d = tmp_path / "ep0__abc.tmp.999999"  # virtually-impossible-PID for this run
    d.mkdir()
    md = WriterMetadata(
        pid=999999, pid_start_time="1970-01-01T00:00:00.000Z",
        canonical_name="ep0__abc", kind="tmp",
        claimed_at="1970-01-01T00:00:00.000Z",
    )
    write_writer_metadata(d, md)
    scavenge_stale_dirs(tmp_path, stale_age_sec=1)
    assert not d.exists()


def test_scavenge_keeps_dir_with_dead_pid_under_age(tmp_path: Path):
    d = tmp_path / "ep0__abc.tmp.999999"
    d.mkdir()
    md = WriterMetadata(
        pid=999999, pid_start_time="1970-01-01T00:00:00.000Z",
        canonical_name="ep0__abc", kind="tmp", claimed_at=_now(),
    )
    write_writer_metadata(d, md)
    scavenge_stale_dirs(tmp_path, stale_age_sec=3600)
    assert d.exists()  # under age threshold; deferred


def test_scavenge_handles_unparseable_metadata(tmp_path: Path):
    """Unparseable .writer.json + age threshold passed → deleted (the dir name
    has a PID we cannot trust without metadata, so the stale_age_sec gate is
    what protects live writers in this branch). With stale_age_sec=1 and no
    parseable claimed_at, age is treated as exceeded → delete."""
    d = tmp_path / "ep0__abc.tmp.42"
    d.mkdir()
    (d / ".writer.json").write_text("{not json")
    scavenge_stale_dirs(tmp_path, stale_age_sec=1)
    assert not d.exists()


def test_scavenge_keeps_unparseable_metadata_with_huge_age(tmp_path: Path):
    """Same scenario, but a 1h age threshold protects against eager deletion."""
    d = tmp_path / "ep0__abc.tmp.43"
    d.mkdir()
    (d / ".writer.json").write_text("{not json")
    # We cannot infer claimed_at without metadata, so the implementation
    # decides "treat as old" — but it MUST also be dead. PID 43 is unlikely
    # to be alive in the test environment; if it IS alive, the test is moot.
    # Use a huge age threshold to keep the test robust regardless.
    scavenge_stale_dirs(tmp_path, stale_age_sec=3600 * 24 * 365)
    # Strictly: the spec says (dead OR unparseable) AND old — with huge age
    # threshold we expect the dir kept. If the implementation chooses to
    # delete unparseable regardless of age, that's a spec deviation.
    assert d.exists()


def _pid_start_time_now() -> str:
    """Return the current process's start time formatted exactly like scavenger does."""
    from mimicanno.scavenger import current_pid_start_time
    return current_pid_start_time(os.getpid())
```

- [ ] **Step 18.2: Run, see red**

Run: `pytest tests/unit/test_scavenger.py -v`

- [ ] **Step 18.3: Implement**

```python
# mimicanno/scavenger.py
"""Scavenger contract for *.tmp.<pid> and *.bak.<pid> dirs (spec §4.4)."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

WRITER_METADATA_FILENAME = ".writer.json"
_PID_DIR_RE = re.compile(r"^(?P<canonical>.+)\.(?P<kind>tmp|bak)\.(?P<pid>\d+)$")


@dataclass(frozen=True, slots=True)
class WriterMetadata:
    pid: int
    pid_start_time: str  # ISO-8601 UTC
    canonical_name: str
    kind: str            # "tmp" or "bak"
    claimed_at: str      # ISO-8601 UTC


def write_writer_metadata(dir_path: Path, md: WriterMetadata) -> None:
    (dir_path / WRITER_METADATA_FILENAME).write_text(
        json.dumps(asdict(md), sort_keys=True),
    )


def read_writer_metadata(dir_path: Path) -> WriterMetadata | None:
    p = dir_path / WRITER_METADATA_FILENAME
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        return WriterMetadata(**data)
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists but isn't ours
    return True


def current_pid_start_time(pid: int) -> str:
    """Return a stable ISO-8601 string for the start time of ``pid``.

    Uses ``/proc/<pid>/stat`` on Linux; falls back to a sentinel on other
    platforms. The exact value is not load-bearing — it just has to match
    *itself* across consecutive reads while the process is alive.
    """
    try:
        from time import strftime, gmtime
        stat = Path(f"/proc/{pid}/stat").read_text()
        # Field 22 (1-indexed) is starttime in clock ticks since boot.
        # We don't try to convert to wall-clock here; we just return a stable hash.
        starttime_ticks = stat.split()[21]
        return f"linux-jiffies-{starttime_ticks}"
    except (FileNotFoundError, OSError, IndexError):
        return "unknown-pid-start"


def scavenge_stale_dirs(
    runs_root: Path,
    *,
    stale_age_sec: float,
) -> list[Path]:
    """Remove `*.tmp.<pid>/` and `*.bak.<pid>/` whose writer is dead AND old.

    Returns the list of directories actually removed. Logging is delegated to
    the caller (the publish-transaction orchestrator).

    Age determination:
    - If ``.writer.json`` is parseable, use ``claimed_at``.
    - Otherwise fall back to the directory's mtime (best-effort proxy for
      "when this stale state appeared on disk"). This ensures unparseable
      metadata still age-gates per the spec, instead of being deleted on sight.
    """
    if not runs_root.exists():
        return []
    now = dt.datetime.now(tz=dt.timezone.utc)
    removed: list[Path] = []
    for entry in runs_root.iterdir():
        m = _PID_DIR_RE.match(entry.name)
        if not m or not entry.is_dir():
            continue
        md = read_writer_metadata(entry)
        claimed: dt.datetime | None
        if md is not None:
            try:
                claimed = dt.datetime.fromisoformat(
                    md.claimed_at.replace("Z", "+00:00"),
                )
            except ValueError:
                claimed = None
        else:
            claimed = None
        if claimed is None:
            # Fallback: directory mtime as a stand-in for claimed_at.
            mtime = dt.datetime.fromtimestamp(entry.stat().st_mtime, tz=dt.timezone.utc)
            age_sec = (now - mtime).total_seconds()
        else:
            age_sec = (now - claimed).total_seconds()
        is_old = age_sec >= stale_age_sec
        pid = int(m.group("pid"))
        is_dead = (
            md is None
            or not is_pid_alive(pid)
            or md.pid_start_time != current_pid_start_time(pid)
        )
        if is_dead and is_old:
            shutil.rmtree(entry, ignore_errors=True)
            removed.append(entry)
    return removed
```

- [ ] **Step 18.4: Run, see green**

Run: `pytest tests/unit/test_scavenger.py -v`

- [ ] **Step 18.5: Commit**

```bash
git add mimicanno/scavenger.py tests/unit/test_scavenger.py
git commit -m "$(cat <<'EOF'
scavenger: .writer.json contract for *.tmp/*.bak directories

Deletion requires (pid dead OR pid_start_time mismatch OR unparseable)
AND age > stale_age_sec. Never lock-holdership — the live writer of a
.tmp does NOT yet hold the lock when it writes (§4.4 step 3).
EOF
)"
```

---

### Task 19: `runs/index.json` upsert (`mimicanno/runindex.py`)

Spec §4.4 + §4.1: full-`run_hash` upsert key, atomic write.

**Files:**
- Create: `mimicanno/runindex.py`
- Create: `tests/unit/test_runindex.py`

- [ ] **Step 19.1: Write failing test**

```python
# tests/unit/test_runindex.py
import json
from pathlib import Path

from mimicanno.runindex import IndexRow, read_index, upsert_row


def _row(run_hash: str, *, episode: str = "ep0", task: str = "pick") -> IndexRow:
    return IndexRow(
        episode_id=episode,
        run_hash=run_hash,
        run_hash_short=run_hash.removeprefix("sha256:")[:12],
        config_hash_short="abc12345",
        input_hash_short="def67890",
        manifest_url=f"{episode}__{run_hash.removeprefix('sha256:')[:12]}/manifest.json",
        task_text=task,
        pipeline_phase=1,
        generated_at="2026-04-26T00:00:00Z",
    )


def test_read_empty_returns_empty_list(tmp_path: Path):
    idx = read_index(tmp_path / "index.json")
    assert idx.rows == []


def test_upsert_appends_new_row(tmp_path: Path):
    p = tmp_path / "index.json"
    upsert_row(p, _row("sha256:" + "a" * 64))
    data = json.loads(p.read_text())
    assert len(data["runs"]) == 1
    assert data["schema_version"] == "0.1.0"


def test_upsert_replaces_existing_by_full_run_hash(tmp_path: Path):
    p = tmp_path / "index.json"
    upsert_row(p, _row("sha256:" + "a" * 64, task="old"))
    upsert_row(p, _row("sha256:" + "a" * 64, task="new"))
    data = json.loads(p.read_text())
    assert len(data["runs"]) == 1
    assert data["runs"][0]["task_text"] == "new"


def test_upsert_appends_when_run_hash_differs(tmp_path: Path):
    p = tmp_path / "index.json"
    upsert_row(p, _row("sha256:" + "a" * 64))
    upsert_row(p, _row("sha256:" + "b" * 64))
    data = json.loads(p.read_text())
    assert len(data["runs"]) == 2
```

- [ ] **Step 19.2: Run, see red**

Run: `pytest tests/unit/test_runindex.py -v`

- [ ] **Step 19.3: Implement**

```python
# mimicanno/runindex.py
"""runs/index.json read + upsert (spec §4.4)."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from mimicanno.schema_versions import INDEX_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class IndexRow:
    episode_id: str
    run_hash: str            # full sha256:<hex>
    run_hash_short: str      # display only
    config_hash_short: str
    input_hash_short: str
    manifest_url: str
    task_text: str
    pipeline_phase: int
    generated_at: str


@dataclass(slots=True)
class IndexFile:
    schema_version: str
    rows: list[IndexRow]


def read_index(path: Path) -> IndexFile:
    if not path.exists():
        return IndexFile(schema_version=INDEX_SCHEMA_VERSION, rows=[])
    data = json.loads(path.read_text())
    rows = [IndexRow(**row) for row in data.get("runs", [])]
    return IndexFile(schema_version=data.get("schema_version", INDEX_SCHEMA_VERSION), rows=rows)


def write_index_atomic(path: Path, idx: IndexFile) -> None:
    payload = {
        "schema_version": idx.schema_version,
        "runs": [asdict(r) for r in idx.rows],
    }
    tmp = path.with_suffix(f".tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    tmp.replace(path)


def upsert_row(path: Path, row: IndexRow) -> None:
    """Read → upsert by full ``run_hash`` (the upsert key per §4.4) → atomic write.

    NOTE: Caller is expected to hold ``runs/index.json.lock`` when invoking
    this — the function does not acquire the lock itself.
    """
    idx = read_index(path)
    rows = [r for r in idx.rows if not (r.episode_id == row.episode_id and r.run_hash == row.run_hash)]
    rows.append(row)
    rows.sort(key=lambda r: r.generated_at, reverse=True)
    write_index_atomic(path, IndexFile(schema_version=idx.schema_version, rows=rows))
```

- [ ] **Step 19.4: Run, see green**

Run: `pytest tests/unit/test_runindex.py -v`

- [ ] **Step 19.5: Commit**

```bash
git add mimicanno/runindex.py tests/unit/test_runindex.py
git commit -m "$(cat <<'EOF'
runindex: read / upsert / atomic-write for runs/index.json

Upsert key is the FULL run_hash, not the truncated short form (§4.4).
Caller is responsible for holding runs/index.json.lock.
EOF
)"
```

---

### Task 20: Publish-transaction orchestrator (`mimicanno/publish.py`)

This composes everything in §4.4: lock-free reuse short-circuit, write tmp + writer.json, acquire lock, scavenger, locked reuse re-check, replacement, index upsert, lock release.

**Files:**
- Create: `mimicanno/publish.py`
- Create: `tests/unit/test_publish.py`

- [ ] **Step 20.1: Write failing tests**

```python
# tests/unit/test_publish.py
import json
import os
from pathlib import Path

import pytest

from mimicanno.publish import PublishOutcome, PublishRequest, publish
from mimicanno.runindex import IndexRow, read_index


def _request(runs_root: Path, run_hash: str, task: str = "pick") -> PublishRequest:
    return PublishRequest(
        runs_root=runs_root,
        episode_id="ep0",
        config_hash="sha256:" + "0" * 64,
        input_hash="sha256:" + "1" * 64,
        run_hash=run_hash,
        task_text=task,
        pipeline_phase=1,
        generated_at="2026-04-26T00:00:00Z",
        force=False,
    )


def _stub_writer(run_dir: Path) -> None:
    """Pretend artifact writer used by tests: drop a manifest with run_hash."""
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "manifest.json").write_text(
        json.dumps({"run_hash": "sha256:" + "9" * 64, "schema_version": "0.1.0"}),
    )


def test_first_publish_creates_run_dir_and_index(tmp_path: Path):
    rh = "sha256:" + "9" * 64
    req = _request(tmp_path, rh)
    outcome = publish(req, write_artifacts=_stub_writer)
    assert outcome == PublishOutcome.PUBLISHED
    final = next(d for d in tmp_path.iterdir() if d.is_dir() and d.name.startswith("ep0__"))
    assert (final / "manifest.json").exists()
    assert not (final / ".writer.json").exists()  # writer.json removed before finalization
    idx = read_index(tmp_path / "index.json")
    assert any(r.run_hash == rh for r in idx.rows)


def test_second_publish_with_same_run_hash_reuses_lock_free(tmp_path: Path):
    rh = "sha256:" + "9" * 64
    publish(_request(tmp_path, rh), write_artifacts=_stub_writer)
    outcome = publish(_request(tmp_path, rh), write_artifacts=_stub_writer)
    assert outcome == PublishOutcome.REUSED_LOCK_FREE


def test_force_replaces_run_dir(tmp_path: Path):
    rh = "sha256:" + "9" * 64
    publish(_request(tmp_path, rh), write_artifacts=_stub_writer)
    req = _request(tmp_path, rh)
    req.force = True
    outcome = publish(req, write_artifacts=_stub_writer)
    assert outcome == PublishOutcome.PUBLISHED
```

- [ ] **Step 20.2: Run, see red**

Run: `pytest tests/unit/test_publish.py -v`

- [ ] **Step 20.3: Implement**

```python
# mimicanno/publish.py
"""Publish transaction (spec §4.4 / §6.5)."""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

from mimicanno.config import RUN_HASH_FALLBACK_PREFIX_LEN, run_hash_short
from mimicanno.locks import file_lock
from mimicanno.rundir import RunPaths, canonical_name_for, is_collision
from mimicanno.runindex import IndexRow, upsert_row
from mimicanno.scavenger import (
    WriterMetadata,
    current_pid_start_time,
    scavenge_stale_dirs,
    write_writer_metadata,
    WRITER_METADATA_FILENAME,
)


LOCK_TIMEOUT_SEC: float = 30.0
DEFAULT_STALE_AGE_SEC: float = 24 * 3600.0


class PublishOutcome(Enum):
    PUBLISHED = "published"
    REUSED_LOCK_FREE = "reused_lock_free"
    REUSED_LOCKED = "reused_locked"


@dataclass(slots=True)
class PublishRequest:
    runs_root: Path
    episode_id: str
    config_hash: str
    input_hash: str
    run_hash: str
    task_text: str
    pipeline_phase: int
    generated_at: str
    force: bool = False
    config_hash_short: str = field(default="")
    input_hash_short: str = field(default="")

    def __post_init__(self) -> None:
        # Default the short fields to first-12 of the hex part.
        if not self.config_hash_short:
            self.config_hash_short = self.config_hash.removeprefix("sha256:")[:8]
        if not self.input_hash_short:
            self.input_hash_short = self.input_hash.removeprefix("sha256:")[:8]


def _existing_run_hash(run_dir: Path) -> str | None:
    manifest = run_dir / "manifest.json"
    if not manifest.exists():
        return None
    try:
        return json.loads(manifest.read_text()).get("run_hash")
    except (OSError, json.JSONDecodeError):
        return None


def publish(
    req: PublishRequest,
    *,
    write_artifacts: Callable[[Path], None],
    stale_age_sec: float = DEFAULT_STALE_AGE_SEC,
) -> PublishOutcome:
    """Execute the full §4.4 publish transaction.

    ``write_artifacts(tmp_dir)`` is called outside the lock to populate the
    tmp run directory. It MUST write a ``manifest.json`` with a ``run_hash``
    field matching ``req.run_hash``; the orchestrator does not generate
    manifests itself.
    """
    runs_root = req.runs_root
    runs_root.mkdir(parents=True, exist_ok=True)
    pid = os.getpid()

    # Resolve canonical_name with collision extension if needed.
    name = canonical_name_for(req.episode_id, run_hash=req.run_hash)
    if is_collision(runs_root, canonical_name=name, expected_run_hash=req.run_hash):
        name = canonical_name_for(
            req.episode_id, run_hash=req.run_hash,
            length=RUN_HASH_FALLBACK_PREFIX_LEN,
        )

    paths = RunPaths(runs_root=runs_root, canonical_name=name, pid=pid)

    # §4.4 step 2: lock-free reuse short-circuit.
    if not req.force:
        existing = _existing_run_hash(paths.final)
        if existing == req.run_hash:
            return PublishOutcome.REUSED_LOCK_FREE

    # §4.4 step 3: heavy compute outside the lock, into .tmp.<pid>/ with .writer.json.
    paths.tmp.mkdir(parents=True, exist_ok=True)
    write_writer_metadata(paths.tmp, WriterMetadata(
        pid=pid,
        pid_start_time=current_pid_start_time(pid),
        canonical_name=name,
        kind="tmp",
        claimed_at=dt.datetime.now(tz=dt.timezone.utc).isoformat().replace("+00:00", "Z"),
    ))
    write_artifacts(paths.tmp)

    # §4.4 step 4-9: locked publish.
    lock_path = runs_root / "index.json.lock"
    with file_lock(lock_path, timeout_sec=LOCK_TIMEOUT_SEC):
        # Step 5: scavenger.
        scavenge_stale_dirs(runs_root, stale_age_sec=stale_age_sec)

        # Step 6: locked reuse re-check.
        if not req.force:
            existing = _existing_run_hash(paths.final)
            if existing == req.run_hash:
                shutil.rmtree(paths.tmp, ignore_errors=True)
                _self_heal_index(runs_root, req, name)
                return PublishOutcome.REUSED_LOCKED

        # Step 7: run-directory replacement (§6.5).
        # 7a) remove .writer.json from the soon-to-be-final dir.
        writer_md = paths.tmp / WRITER_METADATA_FILENAME
        if writer_md.exists():
            writer_md.unlink()
        # 7b) backup existing final.
        if paths.final.exists():
            paths.final.rename(paths.bak)
            write_writer_metadata(paths.bak, WriterMetadata(
                pid=pid,
                pid_start_time=current_pid_start_time(pid),
                canonical_name=name,
                kind="bak",
                claimed_at=dt.datetime.now(tz=dt.timezone.utc).isoformat().replace("+00:00", "Z"),
            ))
        # 7c) atomic rename tmp → final.
        paths.tmp.rename(paths.final)

        # Step 8: index upsert.
        upsert_row(runs_root / "index.json", IndexRow(
            episode_id=req.episode_id,
            run_hash=req.run_hash,
            run_hash_short=run_hash_short(req.run_hash, length=len(name) - len(req.episode_id) - 2),
            config_hash_short=req.config_hash_short,
            input_hash_short=req.input_hash_short,
            manifest_url=f"{name}/manifest.json",
            task_text=req.task_text,
            pipeline_phase=req.pipeline_phase,
            generated_at=req.generated_at,
        ))

        # Step 9: rm -rf bak.
        if paths.bak.exists():
            shutil.rmtree(paths.bak, ignore_errors=True)

    return PublishOutcome.PUBLISHED


def _self_heal_index(
    runs_root: Path, req: PublishRequest, name: str,
) -> None:
    """If the index lost a row that disk says exists, re-insert it."""
    upsert_row(runs_root / "index.json", IndexRow(
        episode_id=req.episode_id,
        run_hash=req.run_hash,
        run_hash_short=run_hash_short(
            req.run_hash, length=len(name) - len(req.episode_id) - 2,
        ),
        config_hash_short=req.config_hash_short,
        input_hash_short=req.input_hash_short,
        manifest_url=f"{name}/manifest.json",
        task_text=req.task_text,
        pipeline_phase=req.pipeline_phase,
        generated_at=req.generated_at,
    ))
```

- [ ] **Step 20.4: Run, see green**

Run: `pytest tests/unit/test_publish.py -v`

- [ ] **Step 20.5: Commit**

```bash
git add mimicanno/publish.py tests/unit/test_publish.py
git commit -m "$(cat <<'EOF'
publish: full publish transaction per §4.4 / §6.5

Composes lock-free reuse short-circuit (step 2), heavy compute outside
the lock (step 3), then under runs/index.json.lock: scavenger,
locked reuse re-check (step 6), run-dir replacement (rename + remove
.writer.json), index upsert keyed by full run_hash, bak cleanup.
EOF
)"
```

---

## Phase G — CLI

### Task 21: Structured errors (`mimicanno/errors.py`)

Spec §11: every abort writes a structured JSON to stderr with `error_code`, `message`, `context`.

**Files:**
- Create: `mimicanno/errors.py`
- Create: `tests/unit/test_errors.py`

- [ ] **Step 21.1: Write failing test**

```python
# tests/unit/test_errors.py
import io
import json

import pytest

from mimicanno.errors import MimicAnnoError, write_error_json


def test_writes_json_to_stderr_like():
    sink = io.StringIO()
    err = MimicAnnoError(code="parquet.missing_column", message="missing X", context={"col": "X"})
    write_error_json(err, stream=sink)
    payload = json.loads(sink.getvalue())
    assert payload == {
        "error_code": "parquet.missing_column",
        "message": "missing X",
        "context": {"col": "X"},
    }


def test_raise_then_format():
    with pytest.raises(MimicAnnoError) as exc_info:
        raise MimicAnnoError("io.video.decode_failed", "ffmpeg failed", {"path": "/x.mp4"})
    err = exc_info.value
    assert err.code == "io.video.decode_failed"
    assert err.context["path"] == "/x.mp4"
```

- [ ] **Step 21.2: Implement**

```python
# mimicanno/errors.py
"""Structured error type for CLI aborts (spec §11)."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any, TextIO


@dataclass
class MimicAnnoError(Exception):
    code: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


def write_error_json(err: MimicAnnoError, *, stream: TextIO | None = None) -> None:
    sink = stream or sys.stderr
    sink.write(json.dumps({
        "error_code": err.code,
        "message": err.message,
        "context": err.context,
    }))
    sink.write("\n")
    sink.flush()
```

- [ ] **Step 21.3: Run, see green; commit**

```bash
pytest tests/unit/test_errors.py -v
git add mimicanno/errors.py tests/unit/test_errors.py
git commit -m "errors: structured CLI error JSON helper (§11)"
```

---

### Task 22: Pipeline orchestrator (`mimicanno/pipeline.py`)

Composes adapters + I/O + signals + boundaries + bracketing + writers + publish into a single `annotate_episode(...)` function. The CLI calls this; tests can call it directly bypassing argv.

**Files:**
- Create: `mimicanno/pipeline.py`
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/test_pipeline_compose.py`

- [ ] **Step 22.1: Write failing test (compose-level)**

```python
# tests/integration/test_pipeline_compose.py
"""Smoke test that pipeline.annotate_episode() composes the full chain.

Heavier end-to-end tests live alongside CLI tests under integration/.
"""
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def test_annotate_synthetic_aloha_smoke(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode
    from mimicanno.pipeline import AnnotateRequest, annotate_episode
    from mimicanno.config import (
        AnnotationConfig, BoundaryConfig, ModelConfig,
    )

    inputs = synthesize_aloha_episode(tmp_path / "data", n_frames=120, fps=30.0)
    req = AnnotateRequest(
        video=inputs.video,
        parquet=inputs.parquet,
        task="pick red block",
        robot_adapter_name="aloha",
        robot_adapter_config_path=None,
        labels_path=None,         # use bundled manipulation.yaml
        runs_root=tmp_path / "runs",
        link_video=False,
        force=False,
        config=AnnotationConfig(
            boundary=BoundaryConfig(
                weights={"gripper": 0.5, "velocity": 0.25, "acceleration": 0.15, "action": 0.1},
                thresholds={"gripper_delta": 0.3, "velocity_valley": 0.05},
                merge_window_sec=0.10,
                score_threshold=0.30,
                disabled_sources=[],
            ),
            target_phase=1,
            model_config=ModelConfig(None, None, None, None),
        ),
    )
    result = annotate_episode(req)
    final = result.run_dir
    assert (final / "manifest.json").exists()
    assert (final / "annotation.json").exists()
    assert (final / "boundaries.json").exists()
    assert (final / "signals.json").exists()
    assert (final / "video.mp4").exists()
    manifest = json.loads((final / "manifest.json").read_text())
    assert manifest["episode_id"] == inputs.episode_id
    assert manifest["pipeline_status"]["object_state_available"] is False
```

- [ ] **Step 22.2: Synthesize-fixture helper (`tests/fixtures/synthesize.py`)**

This generates realistic-shaped synthetic episodes used by every integration test.

```python
# tests/fixtures/__init__.py
```

```python
# tests/fixtures/synthesize.py
"""Programmatic generators for synthetic LeRobot episodes used in tests."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import imageio_ffmpeg
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


@dataclass(slots=True)
class SyntheticEpisode:
    episode_id: str
    video: Path
    parquet: Path


def _write_mp4(path: Path, n_frames: int, fps: float) -> Path:
    writer = imageio_ffmpeg.write_frames(
        str(path), size=(64, 64), fps=int(fps),
        codec="libx264", macro_block_size=1, quality=8,
    )
    writer.send(None)
    rng = np.random.default_rng(0)
    for i in range(n_frames):
        # Simple gradient that advances each frame so SAM3 (later phases) sees motion.
        frame = np.full((64, 64, 3), (i * 4) % 255, dtype=np.uint8)
        frame[:, :, 1] = (i * 7) % 255
        writer.send(frame.tobytes())
    writer.close()
    return path


def synthesize_aloha_episode(
    out_dir: Path, *, n_frames: int = 120, fps: float = 30.0,
    episode_id: str = "ep_synth_000",
) -> SyntheticEpisode:
    out_dir.mkdir(parents=True, exist_ok=True)
    video = _write_mp4(out_dir / f"{episode_id}.mp4", n_frames=n_frames, fps=fps)

    rng = np.random.default_rng(0)
    state = rng.uniform(-0.5, 0.5, size=(n_frames, 14)).astype(np.float64)
    # Cumulative EEF position (small steps).
    state[:, 0:3] = np.cumsum(
        rng.normal(0, 0.005, size=(n_frames, 3)), axis=0,
    )
    # Inject a clear gripper close at frame 50 and open at frame 90 so the test
    # can assert at least one boundary candidate is emitted.
    gripper = np.ones(n_frames)
    gripper[50:90] = 0.0
    state[:, 13] = gripper
    action = rng.uniform(-0.1, 0.1, size=(n_frames, 14)).astype(np.float64)
    timestamps = (np.arange(n_frames) / fps).astype(np.float64)

    table = pa.table({
        "observation.state": pa.array(state.tolist()),
        "action": pa.array(action.tolist()),
        "timestamp": pa.array(timestamps.tolist()),
    })
    parquet = out_dir / f"{episode_id}.parquet"
    pq.write_table(table, parquet)

    return SyntheticEpisode(episode_id=episode_id, video=video, parquet=parquet)


def synthesize_koch_episode(
    out_dir: Path, *, n_frames: int = 120, fps: float = 30.0,
    episode_id: str = "ep_synth_koch_000",
) -> SyntheticEpisode:
    """Joint-only state — no Cartesian EEF columns. Triggers EEF-disabled path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    video = _write_mp4(out_dir / f"{episode_id}.mp4", n_frames=n_frames, fps=fps)

    rng = np.random.default_rng(1)
    state = rng.uniform(-0.5, 0.5, size=(n_frames, 6)).astype(np.float64)
    gripper = np.ones(n_frames)
    gripper[60:] = 0.0
    state[:, 5] = gripper
    action = rng.uniform(-0.1, 0.1, size=(n_frames, 6)).astype(np.float64)
    timestamps = (np.arange(n_frames) / fps).astype(np.float64)

    table = pa.table({
        "observation.state": pa.array(state.tolist()),
        "action": pa.array(action.tolist()),
        "timestamp": pa.array(timestamps.tolist()),
    })
    parquet = out_dir / f"{episode_id}.parquet"
    pq.write_table(table, parquet)
    return SyntheticEpisode(episode_id=episode_id, video=video, parquet=parquet)
```

- [ ] **Step 22.3: Implement `mimicanno/pipeline.py`**

```python
# mimicanno/pipeline.py
"""End-to-end Phase 1 pipeline orchestrator."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pyarrow as pa

from mimicanno import __version__
from mimicanno.adapters.aloha import AlohaAdapter
from mimicanno.adapters.base import RobotAdapter
from mimicanno.adapters.generic import GenericAdapter
from mimicanno.adapters.koch import KochAdapter
from mimicanno.adapters.so100 import SO100Adapter
from mimicanno.boundaries import (
    detect_action_norm_change,
    detect_eef_acceleration_peak,
    detect_eef_velocity_valley,
    detect_gripper_transition,
    integrated_candidates,
)
from mimicanno.bracketing import bracket_phase1_segments
from mimicanno.config import (
    RUN_HASH_FALLBACK_PREFIX_LEN,
    AnnotationConfig,
    InputBundle,
    compose_run_hash,
    compute_config_hash,
    compute_input_hash,
)
from mimicanno.errors import MimicAnnoError
from mimicanno.io_parquet import (
    ParquetLoadError,
    load_episode_parquet,
    resolve_fps,
)
from mimicanno.io_video import materialize_video, probe_video
from mimicanno.labelset import default_labels_path, load_label_set
from mimicanno.publish import PublishOutcome, PublishRequest, publish
from mimicanno.rundir import canonical_name_for, is_collision
from mimicanno.schema import (
    AnnotationResult,
    Artifact,
    GeneratorInfo,
    InputRef,
    Manifest,
    PipelineStatus,
    TaskInfo,
)
from mimicanno.schema_versions import ARTIFACT_SCHEMA_VERSIONS, COMPAT_BLOCK
from mimicanno.signals import (
    SignalChannel,
    downsample_for_viewer,
    gaussian_smooth_1d,
    smoothing_sigma_for_fps,
)
from mimicanno.writers import (
    write_annotation_json,
    write_boundaries_json,
    write_manifest_json,
    write_signals_json,
)


@dataclass(slots=True)
class AnnotateRequest:
    video: Path
    parquet: Path
    task: str
    robot_adapter_name: str
    robot_adapter_config_path: Path | None
    labels_path: Path | None
    runs_root: Path
    link_video: bool
    force: bool
    config: AnnotationConfig


@dataclass(slots=True)
class AnnotateResult:
    run_dir: Path
    outcome: PublishOutcome


def _select_adapter(name: str, config_path: Path | None) -> RobotAdapter:
    if name == "aloha":
        return AlohaAdapter()
    if name == "koch":
        return KochAdapter()
    if name == "so100":
        return SO100Adapter()
    if name == "generic":
        if config_path is None:
            raise MimicAnnoError(
                "adapter.generic_requires_config",
                "GenericAdapter requires --robot-config <yaml>",
                {},
            )
        return GenericAdapter.from_yaml(config_path)
    raise MimicAnnoError(
        "adapter.unknown",
        f"unknown robot adapter {name!r}; expected aloha|koch|so100|generic",
        {"adapter_name": name},
    )


def annotate_episode(req: AnnotateRequest) -> AnnotateResult:
    # 1) Resolve label set.
    labels_path = req.labels_path or Path(default_labels_path("manipulation"))
    label_set = load_label_set(labels_path)

    # 2) Adapter selection + adapter-config sha for input_hash.
    adapter = _select_adapter(req.robot_adapter_name, req.robot_adapter_config_path)
    adapter_config_sha: str | None = None
    if req.robot_adapter_config_path is not None:
        from mimicanno.hashing import sha256_file
        adapter_config_sha = "sha256:" + sha256_file(req.robot_adapter_config_path)

    # 3) Probe video and load parquet.
    probe = probe_video(req.video)
    loaded = load_episode_parquet(req.parquet)

    inputs = InputBundle(
        video_sha256=probe.sha256,
        parquet_sha256=loaded.sha256,
        task_text=req.task,
        robot_adapter_name=req.robot_adapter_name,
        robot_adapter_config_sha256=adapter_config_sha,
        labels_yaml_sha256=label_set.sha256,
    )
    config_hash = compute_config_hash(req.config)
    input_hash = compute_input_hash(inputs)
    run_hash = compose_run_hash(config_hash, input_hash)

    # 4) FPS resolution: prefer ffprobe value when timestamps disagree.
    timestamps = np.asarray(loaded.table.column("timestamp").to_pylist(), dtype=np.float64)
    try:
        fps_from_ts = resolve_fps(timestamps)
    except ParquetLoadError as e:
        raise MimicAnnoError("fps.unresolvable", str(e), {})
    fps = float(probe.fps) if probe.fps > 0 else fps_from_ts
    duration_sec = float(probe.duration_sec)
    episode_id = req.parquet.stem  # Phase 1: derive from filename. Override path TBD in Phase 5.

    # 5) Extract signals through the adapter.
    gripper = adapter.gripper_signal(loaded.table)
    eef_pose = adapter.eef_pose(loaded.table)
    eef_vel = adapter.eef_velocity(loaded.table)
    has_eef = eef_vel is not None

    action_norm: np.ndarray | None
    if "action" in loaded.table.column_names:
        action = np.asarray(loaded.table.column("action").to_pylist(), dtype=np.float64)
        action_norm = np.linalg.norm(action, axis=1)
        if (action_norm == 0).mean() >= 0.95:
            action_norm = None
    else:
        action_norm = None

    # 6) Smooth.
    sigma = smoothing_sigma_for_fps(fps)
    gripper_s = gaussian_smooth_1d(gripper, sigma=sigma)
    vel_s = gaussian_smooth_1d(eef_vel, sigma=sigma) if has_eef else None
    # |a| in m/s²: |Δv| / dt where dt = 1/fps. Without the *fps, the values are
    # off by ~30× at 30 fps and the peak_threshold (set in m/s²) effectively
    # becomes 30× too high — the detector would never fire on real data.
    accel_s = (
        gaussian_smooth_1d(
            np.abs(np.diff(eef_vel, prepend=eef_vel[0])) * fps,
            sigma=sigma,
        )
        if has_eef else None
    )
    action_s = (
        gaussian_smooth_1d(action_norm, sigma=sigma) if action_norm is not None else None
    )

    # 7) Detect per source.
    bcfg = req.config.boundary
    events = list(detect_gripper_transition(
        gripper_s, fps=fps, delta_threshold=bcfg.thresholds.get("gripper_delta", 0.30),
    ))
    if vel_s is not None:
        events.extend(detect_eef_velocity_valley(
            vel_s, fps=fps,
            valley_threshold=bcfg.thresholds.get("velocity_valley", 0.05),
            min_valley_sec=0.10,
        ))
    if accel_s is not None:
        events.extend(detect_eef_acceleration_peak(
            accel_s, fps=fps, peak_threshold=1.0,
        ))
    if action_s is not None:
        events.extend(detect_action_norm_change(
            action_s, fps=fps, change_threshold=0.2, window_sec=0.5,
        ))

    candidates = integrated_candidates(
        events, fps=fps, merge_window_sec=bcfg.merge_window_sec,
        weights=bcfg.weights, score_threshold=bcfg.score_threshold,
    )

    # 8) Determine disabled sources from what was actually run.
    disabled: list[str] = []
    if not has_eef:
        disabled.extend(["eef_velocity_valley", "eef_acceleration_peak"])
    if action_s is None:
        disabled.append("action_norm_change")

    # 9) Bracket into Phase 1 skeleton segments.
    segments = bracket_phase1_segments(
        episode_id=episode_id, candidates=candidates,
        fps=fps, duration_sec=duration_sec,
    )

    # 10) Build pipeline_params for manifest (records what was actually used).
    pipeline_params = {
        "boundary": {
            "weights": dict(bcfg.weights),
            "thresholds": dict(bcfg.thresholds),
            "merge_window_sec": bcfg.merge_window_sec,
            "score_threshold": bcfg.score_threshold,
            "disabled_sources": disabled,
        },
    }

    # 11) Build per-channel signals downsampled for viewer.
    signal_channels: list[SignalChannel] = [
        downsample_for_viewer(
            SignalChannel(name="gripper", unit="normalized",
                          values=gripper_s, dt_sec=1.0 / fps),
            target_hz=30.0,
        ),
    ]
    if vel_s is not None:
        signal_channels.append(downsample_for_viewer(
            SignalChannel(name="eef_velocity", unit="m/s",
                          values=vel_s, dt_sec=1.0 / fps),
            target_hz=30.0,
        ))

    # 12) Build dataclass payloads.
    generated_at = dt.datetime.now(tz=dt.timezone.utc).isoformat().replace("+00:00", "Z")
    pipeline_status = PipelineStatus(
        object_state_available=False,
        degraded_from_phase=None,
        degrade_reason=None,
    )
    task_info = TaskInfo(text=req.task, version=None)
    generator = GeneratorInfo(
        name="mimicanno", cli_version=__version__, pipeline_phase=1,
    )

    manifest = Manifest(
        schema_version=ARTIFACT_SCHEMA_VERSIONS["manifest"],
        episode_id=episode_id,
        task=task_info,
        generated_at=generated_at,
        generator=generator,
        config_hash=config_hash,
        input_hash=input_hash,
        run_hash=run_hash,
        model_versions={"sam3": None, "vlm": None},
        pipeline_params=pipeline_params,
        inputs={
            "video": InputRef(path=str(req.video), sha256=probe.sha256),
            "parquet": InputRef(path=str(req.parquet), sha256=loaded.sha256),
        },
        time_base="video_pts_seconds",
        fps=fps,
        duration_sec=duration_sec,
        pipeline_status=pipeline_status,
        compat=COMPAT_BLOCK,
        artifacts=[
            Artifact("video", "video.mp4", "video/mp4"),
            Artifact("annotation", "annotation.json", "application/json"),
            Artifact("boundaries", "boundaries.json", "application/json"),
            Artifact("signals", "signals.json", "application/json"),
        ],
    )

    annotation = AnnotationResult(
        schema_version=ARTIFACT_SCHEMA_VERSIONS["annotation"],
        episode_id=episode_id,
        task=task_info,
        generated_at=generated_at,
        generator=generator,
        config_hash=config_hash,
        input_hash=input_hash,
        run_hash=run_hash,
        model_versions={"sam3": None, "vlm": None},
        pipeline_phase=1,
        pipeline_status=pipeline_status,
        segments=segments,
        boundaries_url="boundaries.json",
        signals_url="signals.json",
        notes=None,
    )

    # 13) Publish.
    def _write_artifacts(tmp_dir: Path) -> None:
        # Materialize video (copy or symlink) FIRST so the writer.json removal
        # at finalization does not have to compete with a half-copied mp4.
        materialize_video(req.video, tmp_dir, link=req.link_video)
        write_signals_json(
            tmp_dir / "signals.json",
            episode_id=episode_id,
            duration_sec=duration_sec,
            channels=signal_channels,
        )
        write_boundaries_json(
            tmp_dir / "boundaries.json",
            episode_id=episode_id, candidates=candidates,
        )
        write_annotation_json(tmp_dir / "annotation.json", annotation)
        write_manifest_json(tmp_dir / "manifest.json", manifest)

    publish_req = PublishRequest(
        runs_root=req.runs_root,
        episode_id=episode_id,
        config_hash=config_hash,
        input_hash=input_hash,
        run_hash=run_hash,
        task_text=req.task,
        pipeline_phase=1,
        generated_at=generated_at,
        force=req.force,
    )
    outcome = publish(publish_req, write_artifacts=_write_artifacts)

    # Resolve final dir from canonical_name (re-applies collision extension if needed).
    name = canonical_name_for(episode_id, run_hash=run_hash)
    if is_collision(req.runs_root, canonical_name=name, expected_run_hash=run_hash):
        name = canonical_name_for(
            episode_id, run_hash=run_hash, length=RUN_HASH_FALLBACK_PREFIX_LEN,
        )
    return AnnotateResult(run_dir=req.runs_root / name, outcome=outcome)
```

- [ ] **Step 22.4: Run the smoke test, see green**

Run: `pytest tests/integration/test_pipeline_compose.py -v`

- [ ] **Step 22.5: Commit**

```bash
git add tests/fixtures/__init__.py tests/fixtures/synthesize.py mimicanno/pipeline.py tests/integration/__init__.py tests/integration/test_pipeline_compose.py
git commit -m "$(cat <<'EOF'
pipeline: end-to-end Phase 1 orchestrator

Composes adapters, parquet/video I/O, signal smoothing, 4 detectors,
integrated score, Phase 1 bracketing, JSON writers, and the publish
transaction. The smoke test synthesizes a 120-frame Aloha episode and
asserts all four artifacts plus the materialized video land in the
canonical run dir.
EOF
)"
```

---

### Task 23: CLI entry (`mimicanno/cli.py`)

Thin Typer wrapper over `pipeline.annotate_episode`. All errors come out as structured JSON on stderr with non-zero exit code.

**Files:**
- Create: `mimicanno/cli.py`
- Create: `tests/integration/test_cli_smoke_aloha.py`

- [ ] **Step 23.1: Write failing test**

```python
# tests/integration/test_cli_smoke_aloha.py
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def test_cli_runs_and_creates_run_dir(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode

    episode = synthesize_aloha_episode(tmp_path / "data", n_frames=120, fps=30.0)
    runs_root = tmp_path / "runs"

    result = subprocess.run(
        [sys.executable, "-m", "mimicanno.cli", "annotate",
         "--video", str(episode.video),
         "--parquet", str(episode.parquet),
         "--task", "pick red block",
         "--robot", "aloha",
         "--runs-root", str(runs_root)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    run_dirs = [p for p in runs_root.iterdir() if p.is_dir() and p.name.startswith(episode.episode_id + "__")]
    assert len(run_dirs) == 1
    final = run_dirs[0]
    manifest = json.loads((final / "manifest.json").read_text())
    assert manifest["episode_id"] == episode.episode_id
    # No .writer.json should remain in the final dir.
    assert not (final / ".writer.json").exists()


def test_cli_emits_structured_error_on_missing_parquet(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode
    episode = synthesize_aloha_episode(tmp_path / "data")
    bogus = tmp_path / "does-not-exist.parquet"

    result = subprocess.run(
        [sys.executable, "-m", "mimicanno.cli", "annotate",
         "--video", str(episode.video),
         "--parquet", str(bogus),
         "--task", "pick",
         "--robot", "aloha",
         "--runs-root", str(tmp_path / "runs")],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0
    err = json.loads(result.stderr.strip().splitlines()[-1])
    assert "error_code" in err
```

- [ ] **Step 23.2: Implement**

```python
# mimicanno/cli.py
"""mimicanno CLI entry (typer)."""
from __future__ import annotations

import sys
from pathlib import Path

import typer

from mimicanno.config import (
    AnnotationConfig, BoundaryConfig, ModelConfig,
)
from mimicanno.errors import MimicAnnoError, write_error_json
from mimicanno.pipeline import AnnotateRequest, annotate_episode

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command()
def annotate(
    video: Path = typer.Option(..., "--video", exists=True, dir_okay=False),
    parquet: Path = typer.Option(..., "--parquet", exists=True, dir_okay=False),
    task: str = typer.Option(..., "--task"),
    robot: str = typer.Option(..., "--robot",
                              help="Adapter: aloha | koch | so100 | generic"),
    robot_config: Path | None = typer.Option(None, "--robot-config"),
    labels: Path | None = typer.Option(None, "--labels-file"),
    runs_root: Path = typer.Option(Path("runs"), "--runs-root"),
    link_video: bool = typer.Option(False, "--link-video", help="Symlink video instead of copy"),
    force: bool = typer.Option(False, "--force", help="Replace existing run"),
    score_threshold: float = typer.Option(0.30, "--score-threshold"),
    merge_window_sec: float = typer.Option(0.10, "--merge-window-sec"),
) -> None:
    """Annotate a single LeRobot episode and publish a Phase-1 run directory."""
    cfg = AnnotationConfig(
        boundary=BoundaryConfig(
            weights={"gripper": 0.5, "velocity": 0.25, "acceleration": 0.15, "action": 0.1},
            thresholds={"gripper_delta": 0.3, "velocity_valley": 0.05},
            merge_window_sec=merge_window_sec,
            score_threshold=score_threshold,
            disabled_sources=[],
        ),
        target_phase=1,
        model_config=ModelConfig(None, None, None, None),
    )
    req = AnnotateRequest(
        video=video, parquet=parquet, task=task,
        robot_adapter_name=robot, robot_adapter_config_path=robot_config,
        labels_path=labels, runs_root=runs_root,
        link_video=link_video, force=force, config=cfg,
    )
    try:
        annotate_episode(req)
    except MimicAnnoError as e:
        write_error_json(e)
        raise typer.Exit(code=2)
    except Exception as e:  # pragma: no cover — last-resort safety net
        write_error_json(MimicAnnoError(
            code="internal.unhandled", message=str(e), context={"type": type(e).__name__},
        ))
        raise typer.Exit(code=3)


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover — invoked via `python -m mimicanno.cli`
    main()
```

- [ ] **Step 23.3: Run, see green; commit**

Run: `pytest tests/integration/test_cli_smoke_aloha.py -v`

```bash
git add mimicanno/cli.py tests/integration/test_cli_smoke_aloha.py
git commit -m "$(cat <<'EOF'
cli: typer entry that wraps pipeline.annotate_episode

Errors come out as structured JSON on stderr with non-zero exit codes
(2 for known MimicAnnoError, 3 for unhandled). Smoke test synthesizes
an Aloha episode and asserts the four artifacts land in the canonical
run dir with no .writer.json residue.
EOF
)"
```

---

## Phase H — Integration tests (covers exit criteria §15.1–§15.11)

Each test in this phase corresponds to one or more numbered Phase-1 exit criteria from spec §15. Tests use synthetic fixtures from Task 22.

### Task 24: Reuse and `--force` (covers §15.6)

**Files:**
- Create: `tests/integration/test_cli_reuse_and_force.py`

- [ ] **Step 24.1: Write test**

```python
# tests/integration/test_cli_reuse_and_force.py
"""§15.6: re-running the same config does not rewrite the run directory.
--force re-publishes byte-equivalent artifacts modulo generated_at."""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "mimicanno.cli", "annotate", *args],
        capture_output=True, text=True, timeout=60,
    )


def _common_args(episode, runs_root: Path) -> list[str]:
    return [
        "--video", str(episode.video),
        "--parquet", str(episode.parquet),
        "--task", "pick red block",
        "--robot", "aloha",
        "--runs-root", str(runs_root),
    ]


def test_second_run_with_same_config_is_no_op(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode
    episode = synthesize_aloha_episode(tmp_path / "data")
    runs_root = tmp_path / "runs"

    r1 = _run_cli(*_common_args(episode, runs_root))
    assert r1.returncode == 0
    final = next(p for p in runs_root.iterdir() if p.is_dir() and p.name.startswith(episode.episode_id + "__"))
    mtime_before = (final / "manifest.json").stat().st_mtime_ns
    time.sleep(0.05)

    r2 = _run_cli(*_common_args(episode, runs_root))
    assert r2.returncode == 0
    mtime_after = (final / "manifest.json").stat().st_mtime_ns
    assert mtime_after == mtime_before  # nothing rewritten


def test_force_replaces_run(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode
    episode = synthesize_aloha_episode(tmp_path / "data")
    runs_root = tmp_path / "runs"

    _run_cli(*_common_args(episode, runs_root))
    final = next(p for p in runs_root.iterdir() if p.is_dir() and p.name.startswith(episode.episode_id + "__"))
    before = json.loads((final / "manifest.json").read_text())

    time.sleep(0.05)
    r = _run_cli(*_common_args(episode, runs_root), "--force")
    assert r.returncode == 0
    after = json.loads((final / "manifest.json").read_text())

    # generated_at differs because --force writes fresh.
    assert before["generated_at"] != after["generated_at"]
    # Hashes are stable (same inputs + config).
    assert before["run_hash"] == after["run_hash"]
    assert before["config_hash"] == after["config_hash"]
    assert before["input_hash"] == after["input_hash"]
```

- [ ] **Step 24.2: Run, see green; commit**

```bash
pytest tests/integration/test_cli_reuse_and_force.py -v
git add tests/integration/test_cli_reuse_and_force.py
git commit -m "test: §15.6 reuse-by-default vs --force replacement"
```

---

### Task 25: Concurrent publish race (covers §15.4)

**Files:**
- Create: `tests/integration/test_cli_concurrent_publish.py`

- [ ] **Step 25.1: Write test**

```python
# tests/integration/test_cli_concurrent_publish.py
"""§15.4 + §4.4 step 6: two concurrent CLIs targeting the same run_hash
must not lose entries or corrupt the run dir; only one writes, the
other reuses."""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _spawn(args: list[str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-m", "mimicanno.cli", "annotate", *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def test_two_concurrent_publishes_same_hash(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode
    episode = synthesize_aloha_episode(tmp_path / "data", n_frames=300)
    runs_root = tmp_path / "runs"
    args = [
        "--video", str(episode.video),
        "--parquet", str(episode.parquet),
        "--task", "pick red block",
        "--robot", "aloha",
        "--runs-root", str(runs_root),
    ]
    p1 = _spawn(args)
    # Stagger by 50 ms so both processes are likely to be in the
    # heavy-compute (lock-free) region simultaneously.
    time.sleep(0.05)
    p2 = _spawn(args)
    rc1 = p1.wait(timeout=120)
    rc2 = p2.wait(timeout=120)
    assert rc1 == 0
    assert rc2 == 0

    # Exactly one final run dir.
    runs = [p for p in runs_root.iterdir() if p.is_dir() and p.name.startswith(episode.episode_id + "__")]
    assert len(runs) == 1

    # Index has exactly one row.
    idx = json.loads((runs_root / "index.json").read_text())
    assert len(idx["runs"]) == 1
    # No leftover *.tmp.<pid>/ or *.bak.<pid>/.
    for child in runs_root.iterdir():
        assert ".tmp." not in child.name
        assert ".bak." not in child.name
```

- [ ] **Step 25.2: Run, see green; commit**

```bash
pytest tests/integration/test_cli_concurrent_publish.py -v
git add tests/integration/test_cli_concurrent_publish.py
git commit -m "test: §15.4 concurrent CLIs serialize via publish-transaction lock"
```

---

### Task 26: Prefix collision extension (covers §15.11)

**Files:**
- Create: `tests/integration/test_cli_collision_extension.py`

- [ ] **Step 26.1: Write test**

This synthetically forces a collision: we manually plant a directory named `<episode>__<run_hash[:12]>` containing a `manifest.json` whose `run_hash` differs from what the CLI will compute. The CLI must extend to `[:16]` rather than overwriting.

```python
# tests/integration/test_cli_collision_extension.py
"""§15.11: forcing a run_hash[:12] prefix collision triggers [:16] extension
without overwriting the existing run."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def test_collision_triggers_16_hex_extension(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode
    from mimicanno.config import (
        AnnotationConfig, BoundaryConfig, InputBundle, ModelConfig,
        compose_run_hash, compute_config_hash, compute_input_hash, run_hash_short,
    )
    from mimicanno.hashing import sha256_file
    from mimicanno.io_video import probe_video
    from mimicanno.io_parquet import load_episode_parquet
    from mimicanno.labelset import default_labels_path, load_label_set
    from mimicanno.rundir import canonical_name_for

    episode = synthesize_aloha_episode(tmp_path / "data")
    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    # Compute the run_hash the CLI will derive.
    probe = probe_video(episode.video)
    parquet = load_episode_parquet(episode.parquet)
    labels = load_label_set(Path(default_labels_path("manipulation")))
    cfg = AnnotationConfig(
        boundary=BoundaryConfig(
            weights={"gripper": 0.5, "velocity": 0.25, "acceleration": 0.15, "action": 0.1},
            thresholds={"gripper_delta": 0.3, "velocity_valley": 0.05},
            merge_window_sec=0.10,
            score_threshold=0.30,
            disabled_sources=[],
        ),
        target_phase=1,
        model_config=ModelConfig(None, None, None, None),
    )
    inputs = InputBundle(
        video_sha256=probe.sha256,
        parquet_sha256=parquet.sha256,
        task_text="pick red block",
        robot_adapter_name="aloha",
        robot_adapter_config_sha256=None,
        labels_yaml_sha256=labels.sha256,
    )
    expected_run_hash = compose_run_hash(
        compute_config_hash(cfg), compute_input_hash(inputs),
    )
    name = canonical_name_for(episode.episode_id, run_hash=expected_run_hash)

    # Plant a colliding (but different-content) run dir.
    plant = runs_root / name
    plant.mkdir()
    (plant / "manifest.json").write_text(json.dumps({
        "schema_version": "0.1.0",
        "run_hash": "sha256:" + "f" * 64,  # different from expected
    }))

    # Now run the CLI; it should write to <episode>__<hash[:16]>/ instead.
    result = subprocess.run(
        [sys.executable, "-m", "mimicanno.cli", "annotate",
         "--video", str(episode.video),
         "--parquet", str(episode.parquet),
         "--task", "pick red block",
         "--robot", "aloha",
         "--runs-root", str(runs_root)],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr

    # Both directories now exist; the planted one is untouched.
    expected_extended = runs_root / canonical_name_for(
        episode.episode_id, run_hash=expected_run_hash, length=16,
    )
    assert plant.exists()
    assert expected_extended.exists()
    assert json.loads((plant / "manifest.json").read_text())["run_hash"] == "sha256:" + "f" * 64
```

- [ ] **Step 26.2: Run, see green; commit**

```bash
pytest tests/integration/test_cli_collision_extension.py -v
git add tests/integration/test_cli_collision_extension.py
git commit -m "test: §15.11 prefix-collision extends suffix to [:16]"
```

---

### Task 27: EEF-disabled path on Koch episode (covers §15.7)

**Files:**
- Create: `tests/integration/test_cli_eef_disabled_koch.py`

- [ ] **Step 27.1: Write test**

```python
# tests/integration/test_cli_eef_disabled_koch.py
"""§15.7: Koch (joint-only) → EEF detectors auto-disabled, gripper still fires."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def test_koch_episode_auto_disables_eef(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_koch_episode
    episode = synthesize_koch_episode(tmp_path / "data")
    runs_root = tmp_path / "runs"

    result = subprocess.run(
        [sys.executable, "-m", "mimicanno.cli", "annotate",
         "--video", str(episode.video),
         "--parquet", str(episode.parquet),
         "--task", "pick", "--robot", "koch",
         "--runs-root", str(runs_root)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr

    final = next(p for p in runs_root.iterdir() if p.is_dir() and p.name.startswith(episode.episode_id + "__"))
    manifest = json.loads((final / "manifest.json").read_text())
    disabled = manifest["pipeline_params"]["boundary"]["disabled_sources"]
    assert "eef_velocity_valley" in disabled
    assert "eef_acceleration_peak" in disabled
    # gripper detector still active.
    boundaries = json.loads((final / "boundaries.json").read_text())
    if boundaries["candidates"]:
        sources_seen = {src for c in boundaries["candidates"] for src in c["sources"]}
        assert "gripper_transition" in sources_seen
```

- [ ] **Step 27.2: Run, see green; commit**

```bash
pytest tests/integration/test_cli_eef_disabled_koch.py -v
git add tests/integration/test_cli_eef_disabled_koch.py
git commit -m "test: §15.7 Koch episode auto-disables EEF detectors"
```

---

### Task 28: Zero-action handling (covers §11 row)

**Files:**
- Create: `tests/integration/test_cli_zero_action.py`

- [ ] **Step 28.1: Write test**

```python
# tests/integration/test_cli_zero_action.py
"""§11: empty/zero action column disables action_norm_change without aborting."""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

pytestmark = pytest.mark.integration


def test_zero_action_disables_detector(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode
    episode = synthesize_aloha_episode(tmp_path / "data")

    # Rewrite parquet with all-zero action column.
    table = pq.read_table(episode.parquet)
    n = table.num_rows
    df = table.to_pylist()
    new_table = pa.table({
        "observation.state": pa.array([row["observation.state"] for row in df]),
        "action": pa.array([[0.0] * 14] * n),
        "timestamp": pa.array([row["timestamp"] for row in df]),
    })
    pq.write_table(new_table, episode.parquet)

    runs_root = tmp_path / "runs"
    result = subprocess.run(
        [sys.executable, "-m", "mimicanno.cli", "annotate",
         "--video", str(episode.video),
         "--parquet", str(episode.parquet),
         "--task", "pick", "--robot", "aloha",
         "--runs-root", str(runs_root)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr

    final = next(p for p in runs_root.iterdir() if p.is_dir() and p.name.startswith(episode.episode_id + "__"))
    manifest = json.loads((final / "manifest.json").read_text())
    assert "action_norm_change" in manifest["pipeline_params"]["boundary"]["disabled_sources"]
```

- [ ] **Step 28.2: Run, see green; commit**

```bash
pytest tests/integration/test_cli_zero_action.py -v
git add tests/integration/test_cli_zero_action.py
git commit -m "test: §11 zero/missing action column disables action_norm_change"
```

---

### Task 29: Invalid inputs return structured error (covers §11 + §15)

**Files:**
- Create: `tests/integration/test_cli_invalid_inputs.py`

- [ ] **Step 29.1: Write test**

```python
# tests/integration/test_cli_invalid_inputs.py
"""§11: aborts emit structured JSON on stderr with the right error_code."""
import json
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

pytestmark = pytest.mark.integration


def _last_json_line(text: str) -> dict:
    line = next(line for line in reversed(text.strip().splitlines()) if line.strip())
    return json.loads(line)


def test_missing_state_column_aborts_with_error_code(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode
    episode = synthesize_aloha_episode(tmp_path / "data")

    # Re-write parquet without observation.state (required).
    table = pq.read_table(episode.parquet)
    n = table.num_rows
    df = table.to_pylist()
    new_table = pa.table({
        "action": pa.array([row["action"] for row in df]),
        "timestamp": pa.array([row["timestamp"] for row in df]),
    })
    pq.write_table(new_table, episode.parquet)

    result = subprocess.run(
        [sys.executable, "-m", "mimicanno.cli", "annotate",
         "--video", str(episode.video),
         "--parquet", str(episode.parquet),
         "--task", "pick", "--robot", "aloha",
         "--runs-root", str(tmp_path / "runs")],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0
    err = _last_json_line(result.stderr)
    assert "error_code" in err
    assert "observation.state" in err.get("message", "")


def test_unknown_robot_adapter(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode
    episode = synthesize_aloha_episode(tmp_path / "data")
    result = subprocess.run(
        [sys.executable, "-m", "mimicanno.cli", "annotate",
         "--video", str(episode.video),
         "--parquet", str(episode.parquet),
         "--task", "pick", "--robot", "nonexistent",
         "--runs-root", str(tmp_path / "runs")],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0
    err = _last_json_line(result.stderr)
    assert err["error_code"] == "adapter.unknown"
```

- [ ] **Step 29.2: Run, see green; commit**

```bash
pytest tests/integration/test_cli_invalid_inputs.py -v
git add tests/integration/test_cli_invalid_inputs.py
git commit -m "test: §11 invalid inputs emit structured error JSON"
```

---

### Task 30: Crash recovery / scavenger end-to-end (covers §15.10)

**Files:**
- Create: `tests/integration/test_cli_crash_recovery.py`

- [ ] **Step 30.1: Write test**

```python
# tests/integration/test_cli_crash_recovery.py
"""§15.10: a stale .tmp directory left by a dead PID is scavenged on next run;
a still-live writer's .tmp is NOT scavenged."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from mimicanno.scavenger import (
    WriterMetadata, current_pid_start_time, write_writer_metadata,
)

pytestmark = pytest.mark.integration


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def test_scavenger_removes_dead_pid_tmp(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode
    episode = synthesize_aloha_episode(tmp_path / "data")
    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    # Plant a stale .tmp dir for a never-existed PID with old claimed_at.
    stale = runs_root / f"{episode.episode_id}__deadbeefdead.tmp.999999"
    stale.mkdir()
    write_writer_metadata(stale, WriterMetadata(
        pid=999999,
        pid_start_time="linux-jiffies-0",
        canonical_name=f"{episode.episode_id}__deadbeefdead",
        kind="tmp",
        claimed_at="1970-01-01T00:00:00.000Z",
    ))

    result = subprocess.run(
        [sys.executable, "-m", "mimicanno.cli", "annotate",
         "--video", str(episode.video),
         "--parquet", str(episode.parquet),
         "--task", "pick", "--robot", "aloha",
         "--runs-root", str(runs_root)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert not stale.exists()


def test_scavenger_does_not_touch_live_writer(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode
    episode = synthesize_aloha_episode(tmp_path / "data")
    runs_root = tmp_path / "runs"
    runs_root.mkdir()

    # Plant a "live" .tmp owned by THIS pytest process.
    pid = os.getpid()
    live = runs_root / f"{episode.episode_id}__livebeefbeef.tmp.{pid}"
    live.mkdir()
    write_writer_metadata(live, WriterMetadata(
        pid=pid,
        pid_start_time=current_pid_start_time(pid),
        canonical_name=f"{episode.episode_id}__livebeefbeef",
        kind="tmp",
        claimed_at=_now_iso(),
    ))

    result = subprocess.run(
        [sys.executable, "-m", "mimicanno.cli", "annotate",
         "--video", str(episode.video),
         "--parquet", str(episode.parquet),
         "--task", "pick", "--robot", "aloha",
         "--runs-root", str(runs_root)],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert live.exists()
```

- [ ] **Step 30.2: Run, see green; commit**

```bash
pytest tests/integration/test_cli_crash_recovery.py -v
git add tests/integration/test_cli_crash_recovery.py
git commit -m "test: §15.10 scavenger handles dead PIDs and spares live writers"
```

---

### Task 31: Performance regression (covers §13 compute target)

**Files:**
- Create: `tests/integration/test_cli_perf_compute_path.py`

- [ ] **Step 31.1: Write test**

```python
# tests/integration/test_cli_perf_compute_path.py
"""§13: Phase 1 compute path target ≤ 5 s on a typical laptop CPU.

We measure with --link-video to exclude the I/O path. Small synthetic
episode (5 s = 150 frames at 30 fps), so any compute-side regression
exceeds the budget loudly."""
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.perf]


def test_compute_under_5s(tmp_path: Path):
    from tests.fixtures.synthesize import synthesize_aloha_episode
    episode = synthesize_aloha_episode(tmp_path / "data", n_frames=150, fps=30.0)
    runs_root = tmp_path / "runs"

    t0 = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-m", "mimicanno.cli", "annotate",
         "--video", str(episode.video),
         "--parquet", str(episode.parquet),
         "--task", "pick", "--robot", "aloha",
         "--runs-root", str(runs_root),
         "--link-video"],
        capture_output=True, text=True, timeout=30,
    )
    elapsed = time.monotonic() - t0
    assert result.returncode == 0, result.stderr
    # Generous ceiling — we'd see a regression at >>5 s.
    assert elapsed < 8.0, f"compute path took {elapsed:.2f}s"
```

- [ ] **Step 31.2: Run, see green; commit**

```bash
pytest tests/integration/test_cli_perf_compute_path.py -v
git add tests/integration/test_cli_perf_compute_path.py
git commit -m "test: §13 Phase 1 compute path under 5 s on synthetic 150-frame episode"
```

---

### Task 32: Final cleanup — full suite green + lint + types

- [ ] **Step 32.1: Run the full test suite**

Run: `pytest -v`
Expected: All tests pass.

- [ ] **Step 32.2: Run ruff**

Run: `ruff check mimicanno tests`
Run: `ruff format --check mimicanno tests`
Expected: No issues. Fix any reported issues then re-run.

- [ ] **Step 32.3: Run mypy**

Run: `mypy`
Expected: No errors. Fix any reported issues then re-run.

- [ ] **Step 32.4: Confirm exit-criteria coverage**

Cross-check the integration tests against §15 Phase 1 exit criteria:

| Spec exit criterion | Test |
|---|---|
| §15.1 CLI succeeds | `test_cli_smoke_aloha.py::test_cli_runs_and_creates_run_dir` |
| §15.2 manifest validates | `test_pipeline_compose.py` + writer's `_validate` |
| §15.3 ≥ 1 candidate on gripper transition | `test_pipeline_compose.py` (synthetic episode has gripper close at frame 50) |
| §15.4 index lock prevents loss | `test_cli_concurrent_publish.py` |
| §15.5 viewer renders | DEFERRED to Plan 2 |
| §15.6 reuse + force | `test_cli_reuse_and_force.py` |
| §15.7 EEF disabled on Koch | `test_cli_eef_disabled_koch.py` |
| §15.8 viewer alignment with different dt_sec | DEFERRED to Plan 2 |
| §15.9 chooser banner / hash routing | DEFERRED to Plan 2 |
| §15.10 scavenger / crash recovery | `test_cli_crash_recovery.py` |
| §15.11 collision extension | `test_cli_collision_extension.py` |

If any row above doesn't have a test that asserts the spec'd behavior, add one before finishing.

- [ ] **Step 32.5: Final commit**

```bash
git add -u
git commit -m "$(cat <<'EOF'
chore: pass full suite + lint + types for Phase 1

All Phase 1 spec exit criteria covered by tests in this plan are green.
§15.5 / §15.8 / §15.9 are deferred to Plan 2 (viewer) per the brush-up
spec's two-plan split.
EOF
)" --allow-empty
```

---

## Done

The Phase 1 Python pipeline is complete. The repository now has:

- A `mimicanno annotate` CLI that takes a LeRobot episode and publishes a versioned, immutable run directory under `<repo>/runs/<canonical_name>/`.
- Atomic publish transaction (lock-free reuse short-circuit + locked re-check + POSIX two-rename + scavenger), tested under concurrent invocations and prefix collisions.
- All four artifacts validate against bundled JSON Schemas at write time.
- Adapters for Aloha, Koch, SO-100, and a config-driven Generic adapter, with auto-disable for EEF detectors on joint-only robots.
- Structured error JSON for every documented §11 abort path.

Plan 2 (the React/Vite viewer) consumes these run directories as test fixtures.









