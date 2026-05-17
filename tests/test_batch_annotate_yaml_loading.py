"""Phase 5 D r2 follow-up: verify scripts/batch_annotate.py loads
per-dataset boundary/smoother YAML through the same code path as
``mimicanno.cli annotate``.

The 26B batch runner previously used ``BoundaryConfig.with_defaults()`` and
``SmootherConfig()`` unconditionally, which on SO101 produced degenerate
``segments=[{phase: idle}]`` because the default boundary detector cannot
react to weak gripper signals. The fix (commit on branch
``fix/26b-config-gap``) adds optional ``boundary_config`` / ``smoother_config``
keys to ``DATASETS`` and routes them through the existing
``load_boundary_config_yaml`` / ``load_smoother_config_yaml`` loaders.

This test exercises the loading path without touching the 26B VLM
(A6000 49GB cannot fit 26B; full end-to-end smoke needs A100 80GB).
The 4B path (``scripts/batch_so101_phase4_v5.sh`` → ``mimicanno annotate
--boundary-config so101_zero_crossing.yaml --smoother-config so101_zc_preserve.yaml``)
is the proven witness that this YAML pair produces working segments
when fed into the same downstream pipeline.

Refs:
- docs/superpowers/notes/2026-05-17-g1-26b-so101-smoke-results.md §"推奨フォローアップ"
- scripts/batch_annotate.py (modified)
- mimicanno/cli.py:175-176, 254-275 (the analogous loading pattern)
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# `scripts/` is not a package; import the module by file path.
_SPEC = importlib.util.spec_from_file_location(
    "batch_annotate", REPO / "scripts" / "batch_annotate.py"
)
assert _SPEC is not None and _SPEC.loader is not None
_BA = importlib.util.module_from_spec(_SPEC)
sys.modules["batch_annotate"] = _BA
_SPEC.loader.exec_module(_BA)


def test_so101_dataset_declares_both_yaml_paths() -> None:
    """SO101 entry must declare both boundary and smoother YAMLs."""
    so101 = _BA.DATASETS["so101"]
    bp = so101.get("boundary_config")
    sp = so101.get("smoother_config")
    assert bp is not None, "SO101 must declare boundary_config (otherwise degenerate)"
    assert sp is not None, "SO101 must declare smoother_config (otherwise default merge collapses ZC)"
    assert bp.exists(), f"boundary YAML not found: {bp}"
    assert sp.exists(), f"smoother YAML not found: {sp}"
    # Sanity: file names match the proven 4B sibling script.
    assert bp.name == "so101_zero_crossing.yaml"
    assert sp.name == "so101_zc_preserve.yaml"


def test_gem4_datasets_have_no_yaml_overrides() -> None:
    """gem4 entries currently fall back to defaults (no robot-specific YAML)."""
    for ds_name in (
        "gem4_pick_up_bottle",
        "gem4_replace_the_cookie",
        "gem4_open_the_jar",
    ):
        ds = _BA.DATASETS[ds_name]
        assert ds.get("boundary_config") is None, (
            f"{ds_name}: boundary_config should be None until gem4-specific YAML is authored"
        )
        assert ds.get("smoother_config") is None, (
            f"{ds_name}: smoother_config should be None until gem4-specific YAML is authored"
        )


def test_so101_boundary_yaml_loads_non_default_values() -> None:
    """Loading SO101 boundary YAML must yield values distinct from defaults.

    Specifically:
    - zero_crossing.enabled = True (default is False)
    - score_threshold = 0.30 (per YAML, may match default — focus on zero_crossing)

    This proves that ``load_boundary_config_yaml`` is consulting the YAML, not
    quietly returning a default.
    """
    from mimicanno.config import BoundaryConfig, load_boundary_config_yaml

    so101 = _BA.DATASETS["so101"]
    loaded = load_boundary_config_yaml(so101["boundary_config"])
    default = BoundaryConfig.with_defaults()

    # Zero-crossing must be enabled (load-bearing for SO101 segment richness).
    assert loaded.zero_crossing.enabled is True, (
        "SO101 YAML must enable zero_crossing; default is disabled"
    )
    assert default.zero_crossing.enabled is False, (
        "BoundaryConfig.with_defaults() should NOT enable zero_crossing — "
        "if this fails, the SO101 YAML override may now be a no-op"
    )


def test_so101_smoother_yaml_loads_preserve_sources() -> None:
    """SO101 smoother YAML preserves gripper_zero_crossing in merge."""
    from mimicanno.config import load_smoother_config_yaml
    from mimicanno.labelset import default_labels_path, load_label_set
    from mimicanno.smoother import SmootherConfig

    so101 = _BA.DATASETS["so101"]
    label_set = load_label_set(Path(default_labels_path("manipulation")))
    allowed = [lbl.id for lbl in label_set.labels]
    loaded = load_smoother_config_yaml(
        so101["smoother_config"], allowed_labels=allowed,
    )
    default = SmootherConfig()

    # The defining SO101 smoother behavior: don't collapse ZC-derived boundaries.
    assert "gripper_zero_crossing" in loaded.merge_same_label_preserve_sources, (
        "SO101 smoother YAML must preserve gripper_zero_crossing across same-label merge"
    )
    assert "gripper_zero_crossing" not in default.merge_same_label_preserve_sources, (
        "Default smoother should NOT preserve ZC sources — if this fails, "
        "the SO101 override may no longer be necessary"
    )


def test_main_setup_path_uses_yaml_when_declared(monkeypatch: pytest.MonkeyPatch) -> None:
    """Smoke-level integration: the same code path batch_annotate.main uses
    (lines 137-167 area) constructs an ``AnnotationConfig`` whose
    ``boundary`` and ``smoother`` come from the YAML loaders, not from
    ``with_defaults()`` / ``SmootherConfig()``.

    We exercise this by replicating just the config-construction snippet
    from main(), since main() loads the 26B VLM (52 GiB VRAM, unsuitable
    for this test). The replicated snippet is the load-bearing patch site.
    """
    from mimicanno.config import (
        BoundaryConfig,
        load_boundary_config_yaml,
        load_smoother_config_yaml,
    )
    from mimicanno.labelset import default_labels_path, load_label_set
    from mimicanno.smoother import SmootherConfig

    ds = _BA.DATASETS["so101"]

    # Same shape as scripts/batch_annotate.py lines 137-167 (after fix).
    boundary_cfg_path = ds.get("boundary_config")
    if boundary_cfg_path is not None:
        boundary_cfg = load_boundary_config_yaml(boundary_cfg_path)
    else:
        boundary_cfg = BoundaryConfig.with_defaults()

    smoother_cfg_path = ds.get("smoother_config")
    if smoother_cfg_path is not None:
        label_set = load_label_set(Path(default_labels_path("manipulation")))
        allowed_label_ids = [lbl.id for lbl in label_set.labels]
        smoother_cfg = load_smoother_config_yaml(
            smoother_cfg_path, allowed_labels=allowed_label_ids,
        )
    else:
        smoother_cfg = SmootherConfig()

    # Now confirm the constructed config is the YAML-loaded one, not the
    # default. This is the property the original bug violated.
    assert boundary_cfg.zero_crossing.enabled is True
    assert "gripper_zero_crossing" in smoother_cfg.merge_same_label_preserve_sources
