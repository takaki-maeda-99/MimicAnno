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

    def test_object_track_ids_required_list(self):
        # Symmetric guard: object_track_ids=None must also raise TypeError.
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
                failure_flags=[],
                label_source="signals_only",
                object_state_unavailable=True,
                object_track_ids=None,  # type: ignore[arg-type]
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
            name="mimicanno",
            cli_version="0.1.0",
            pipeline_phase=1,
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


class TestDeepJsonify:
    def test_tuples_become_lists(self):
        from mimicanno.schema import _deep_jsonify

        assert _deep_jsonify({"x": (1, 2, 3)}) == {"x": [1, 2, 3]}

    def test_nested_tuple_inside_dict(self):
        from mimicanno.schema import _deep_jsonify

        out = _deep_jsonify({"weights": ("a", ("b", "c"))})
        assert out == {"weights": ["a", ["b", "c"]]}
