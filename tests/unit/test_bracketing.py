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
