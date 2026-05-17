"""Phase 6: EditEvent old_value/new_value/pre_edit_overall_confidence round-trip."""
from __future__ import annotations

from mimicanno.schema import EditEvent


def test_p17_back_compat_03_event_loads_with_none_values() -> None:
    # 0.3.0-shaped EditEvent (no old_value/new_value/pre_edit_overall_confidence).
    d = {
        "edit_type": "relabel",
        "segment_id": "seg-001",
        "edited_at": "2026-05-17T15:30:00Z",
        "reviewer": None,
        "client_edit_duration_ms": 420,
    }
    ev = EditEvent.from_dict(d)
    assert ev.old_value is None
    assert ev.new_value is None
    assert ev.pre_edit_overall_confidence is None


def test_p3_labels_event_round_trip_full_4_field_tuple() -> None:
    d = {
        "edit_type": "labels",
        "segment_id": "seg-002",
        "edited_at": "2026-05-17T15:31:00Z",
        "reviewer": None,
        "client_edit_duration_ms": 1000,
        "old_value": {
            "kind": "labels",
            "verb": "approach",
            "object": "cube",
            "target": None,
            "failure_flags": [],
        },
        "new_value": {
            "kind": "labels",
            "verb": "grasp",
            "object": "cube",
            "target": None,
            "failure_flags": [],
        },
    }
    ev = EditEvent.from_dict(d)
    assert ev.old_value == {
        "kind": "labels",
        "verb": "approach",
        "object": "cube",
        "target": None,
        "failure_flags": [],
    }
    assert ev.new_value["verb"] == "grasp"
    # Round-trip through to_dict / from_dict.
    again = EditEvent.from_dict(ev.to_dict())
    assert again == ev


def test_p4_boundary_event_uses_int_frame() -> None:
    d = {
        "edit_type": "boundary",
        "segment_id": "seg-003",
        "edited_at": "2026-05-17T15:32:00Z",
        "reviewer": None,
        "client_edit_duration_ms": None,
        "old_value": {"kind": "boundary", "value": 120},
        "new_value": {"kind": "boundary", "value": 145},
    }
    ev = EditEvent.from_dict(d)
    assert ev.old_value == {"kind": "boundary", "value": 120}
    assert isinstance(ev.new_value["value"], int)


def test_pre_edit_overall_confidence_round_trip() -> None:
    d = {
        "edit_type": "relabel",
        "segment_id": "seg-004",
        "edited_at": "2026-05-17T15:33:00Z",
        "reviewer": None,
        "client_edit_duration_ms": None,
        "old_value": {"kind": "relabel", "value": "approach_object"},
        "new_value": {"kind": "relabel", "value": "grasp_object"},
        "pre_edit_overall_confidence": 0.72,
    }
    ev = EditEvent.from_dict(d)
    assert ev.pre_edit_overall_confidence == 0.72
    assert ev.to_dict()["pre_edit_overall_confidence"] == 0.72


from mimicanno.server.event_builder import build_edit_event


def test_builder_propagates_values() -> None:
    ev = build_edit_event(
        edit_type="relabel",
        segment_id="seg-001",
        client_edit_duration_ms=420,
        reviewer=None,
        old_value={"kind": "relabel", "value": "approach"},
        new_value={"kind": "relabel", "value": "grasp"},
        pre_edit_overall_confidence=0.61,
    )
    assert ev.edit_type == "relabel"
    assert ev.old_value == {"kind": "relabel", "value": "approach"}
    assert ev.new_value == {"kind": "relabel", "value": "grasp"}
    assert ev.pre_edit_overall_confidence == 0.61


def test_builder_rejects_kind_mismatch() -> None:
    import pytest
    with pytest.raises(ValueError, match="kind"):
        build_edit_event(
            edit_type="relabel",
            segment_id="seg-001",
            client_edit_duration_ms=None,
            reviewer=None,
            old_value={"kind": "boundary", "value": 120},  # mismatched
            new_value={"kind": "relabel", "value": "grasp"},
            pre_edit_overall_confidence=None,
        )


def test_builder_existing_call_pattern_still_works() -> None:
    """Existing PATCH repos that haven't been updated for Task 3 yet must still work."""
    ev = build_edit_event(
        edit_type="reviewed",
        segment_id="seg-002",
        client_edit_duration_ms=None,
        reviewer=None,
    )
    assert ev.old_value is None
    assert ev.new_value is None
    assert ev.pre_edit_overall_confidence is None


# ---------------------------------------------------------------------------
# Route-level integration tests: old/new value capture per edit type
# ---------------------------------------------------------------------------

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mimicanno.io import read_annotation_result, read_manifest
from mimicanno.server.app import create_app
from tests.server.conftest import _LOADABLE_RUN_NAME, _build_loadable_fixture


def _client(runs_root: Path) -> TestClient:
    app = create_app(runs_root=runs_root, cors_origins=[])
    return TestClient(app)


@pytest.fixture
def runs_root_with_loadable(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    _build_loadable_fixture(root)
    return root


# Fixture-specific constants derived from annotation.json:
# seg0000: phase="approach_object", reviewed=True, end_frame=24, overall_confidence≈0.949
# seg0001: phase="approach_object", reviewed=True, start_frame=25 (seam with seg0000)
# seg0003: verb="put", object="tape", target="bottle", failure_flags=[]
# seg0004: reviewed=False (used for reviewed toggle tests)
_SEG_ID_0 = "episode_000000__seg0000"
_SEG_ID_1 = "episode_000000__seg0001"
_SEG_ID_3 = "episode_000000__seg0003"
_SEG_ID_4 = "episode_000000__seg0004"
# Boundary between seg0000 (end_frame=24) and seg0001 (start_frame=25):
# canonical seam frame = 25 = left.end_frame + 1 = right.start_frame
_BOUNDARY_ID_0_1 = "episode_000000__seg0001"  # right segment = boundary_id by D-r2 convention


@pytest.mark.parametrize(
    "edit_type,seg_id,url_suffix,body,check_old,check_new",
    [
        # relabel: approach_object → grasp_object
        (
            "relabel",
            _SEG_ID_0,
            f"segments/{_SEG_ID_0}",
            {"phase": "grasp_object"},
            {"kind": "relabel", "value": "approach_object"},
            {"kind": "relabel", "value": "grasp_object"},
        ),
        # reviewed: False → True (seg0004 starts False)
        (
            "reviewed",
            _SEG_ID_4,
            f"segments/{_SEG_ID_4}/reviewed",
            {"reviewed": True},
            {"kind": "reviewed", "value": False},
            {"kind": "reviewed", "value": True},
        ),
        # boundary: seam at frame 25 → 15
        (
            "boundary",
            _BOUNDARY_ID_0_1,
            f"boundaries/{_BOUNDARY_ID_0_1}",
            {"frame": 15},
            {"kind": "boundary", "value": 25},
            {"kind": "boundary", "value": 15},
        ),
        # labels: update verb/object/target/failure_flags on seg0003
        (
            "labels",
            _SEG_ID_3,
            f"segments/{_SEG_ID_3}/labels",
            {"verb": "pick", "object": "tape", "target": None, "failure_flags": []},
            {"kind": "labels", "verb": "put", "object": "tape", "target": "bottle", "failure_flags": []},
            {"kind": "labels", "verb": "pick", "object": "tape", "target": None, "failure_flags": []},
        ),
    ],
)
def test_p1_each_route_records_old_new_value(
    runs_root_with_loadable: Path,
    edit_type: str,
    seg_id: str,
    url_suffix: str,
    body: dict,
    check_old: dict,
    check_new: dict,
) -> None:
    """P1: round-trip — each PATCH route writes old/new value matching the change."""
    root = runs_root_with_loadable
    name = _LOADABLE_RUN_NAME
    rh = read_manifest(root / name / "manifest.json").run_hash

    client = _client(root)
    resp = client.patch(
        f"/api/runs/{name}/{url_suffix}",
        headers={"Content-Type": "application/json", "If-Match": rh},
        content=json.dumps(body),
    )
    assert resp.status_code == 200, f"[{edit_type}] {resp.status_code}: {resp.text}"

    ann = read_annotation_result(root / name / "annotation.json")
    assert len(ann.history) == 1, f"[{edit_type}] history length {len(ann.history)}"
    ev = ann.history[0]
    assert ev.edit_type == edit_type
    assert ev.old_value == check_old, f"[{edit_type}] old_value mismatch: {ev.old_value!r}"
    assert ev.new_value == check_new, f"[{edit_type}] new_value mismatch: {ev.new_value!r}"


def test_p2_old_value_reflects_pre_mutation_state(
    runs_root_with_loadable: Path,
) -> None:
    """P2: old_value is the pre-PATCH phase, NOT the post-PATCH phase.

    P1 already enforces this indirectly (mutate-then-read would carry the new
    phase). P2 is a narrower explicit pin for the relabel path.
    """
    root = runs_root_with_loadable
    name = _LOADABLE_RUN_NAME
    rh = read_manifest(root / name / "manifest.json").run_hash

    client = _client(root)
    resp = client.patch(
        f"/api/runs/{name}/segments/{_SEG_ID_0}",
        headers={"Content-Type": "application/json", "If-Match": rh},
        content=json.dumps({"phase": "grasp_object"}),
    )
    assert resp.status_code == 200, resp.text

    ann = read_annotation_result(root / name / "annotation.json")
    ev = ann.history[-1]
    assert ev.edit_type == "relabel"
    # old_value must be the PRE-PATCH phase (approach_object), not the new one.
    assert ev.old_value == {"kind": "relabel", "value": "approach_object"}
    assert ev.new_value == {"kind": "relabel", "value": "grasp_object"}
    # Segment was actually mutated.
    seg = next(s for s in ann.segments if s.segment_id == _SEG_ID_0)
    assert seg.phase == "grasp_object"


def test_p5_reviewed_noop_does_not_emit_event(
    runs_root_with_loadable: Path,
) -> None:
    """P5: reviewed PATCH with same value short-circuits BEFORE event-build.

    Per spec §4.5: annotation.history length must be unchanged when the
    request is rejected with reviewed_no_change (400).
    """
    root = runs_root_with_loadable
    name = _LOADABLE_RUN_NAME
    rh = read_manifest(root / name / "manifest.json").run_hash

    # seg0000 starts with reviewed=True; PATCH reviewed=True → should 400.
    client = _client(root)
    resp = client.patch(
        f"/api/runs/{name}/segments/{_SEG_ID_0}/reviewed",
        headers={"Content-Type": "application/json", "If-Match": rh},
        content=json.dumps({"reviewed": True}),
    )
    assert resp.status_code == 400, f"expected 400, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body.get("error") == "no_change"

    # History must not have grown.
    ann = read_annotation_result(root / name / "annotation.json")
    assert len(ann.history) == 0, f"history should be empty, got {len(ann.history)} events"
