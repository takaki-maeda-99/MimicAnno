# tests/unit/test_writers.py
import json
from pathlib import Path

import numpy
import pytest

from mimicanno.schema import (
    AnnotationResult,
    BoundaryCandidate,
    GeneratorInfo,
    PipelineStatus,
    TaskInfo,
)
from mimicanno.signals import SignalChannel
from mimicanno.writers import (
    write_annotation_json,
    write_boundaries_json,
    write_manifest_json,
    write_signals_json,
)
from tests.unit.test_schema import _make_minimal_manifest


def test_write_signals_json_round_trips(tmp_path: Path):
    channels = [
        SignalChannel(
            name="gripper",
            unit="normalized",
            values=numpy.linspace(1.0, 0.0, 60),
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
    out = tmp_path / "boundaries.json"
    write_boundaries_json(
        out,
        episode_id="ep0",
        candidates=[
            BoundaryCandidate(
                id="b_001",
                frame=42,
                time=1.4,
                sources=["gripper_transition"],
                scores={"gripper_transition": 0.95},
                score=0.475,
            ),
        ],
    )
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
