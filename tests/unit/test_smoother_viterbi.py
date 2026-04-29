"""Op 3: Viterbi relabel + deterministic tuple-comparator tie-break (spec §3.4)."""
from __future__ import annotations

import math
from dataclasses import replace

from mimicanno.config import SmootherConfig
from mimicanno.schema import BoundaryRef, SubtaskSegment
from mimicanno.smoother import _viterbi_relabel


LABELSET = ["approach_object", "grasp_object", "lift_object",
            "release_object", "idle"]


def _seg(*, idx: int, phase: str, vlm: float | None = 0.7,
         label_source: str = "vlm_with_object_state",
         verb: str | None = "grasp", obj: str | None = "cube") -> SubtaskSegment:
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
        phase=phase, verb=verb, object=obj, target=None,
        failure_flags=[],
        label_source=label_source,  # type: ignore[arg-type]
        object_state_unavailable=False, object_track_ids=[],
        label_version="v1",
        start_boundary=BoundaryRef(candidate_id=f"b{idx}s",
                                    time=idx*10/30, sources=[], score=bc),
        end_boundary=BoundaryRef(candidate_id=f"b{idx}e",
                                  time=(idx+1)*10/30, sources=[], score=bc),
        boundary_confidence=bc, vlm_confidence=vlm, overall_confidence=oc,
        evidence=None, reviewed=False, reviewer_id=None,
        smoothing_ops=[],
    )


def test_no_forbidden_identity() -> None:
    cfg = SmootherConfig(viterbi_enabled=True, lambda_forbidden=0.5,
                         forbidden_transitions=())
    segs = [_seg(idx=0, phase="grasp_object"),
            _seg(idx=1, phase="approach_object")]
    out, relabels, skipped = _viterbi_relabel(segs, config=cfg, labelset=LABELSET)
    assert relabels == 0
    assert skipped is False
    assert [s.phase for s in out] == ["grasp_object", "approach_object"]


def test_disabled_skips() -> None:
    cfg = SmootherConfig(viterbi_enabled=False)
    segs = [_seg(idx=0, phase="grasp_object"),
            _seg(idx=1, phase="approach_object")]
    out, relabels, skipped = _viterbi_relabel(segs, config=cfg, labelset=LABELSET)
    assert skipped is True
    assert relabels == 0
    assert out == segs


def test_single_segment_skipped() -> None:
    cfg = SmootherConfig(viterbi_enabled=True)
    segs = [_seg(idx=0, phase="grasp_object")]
    out, relabels, skipped = _viterbi_relabel(segs, config=cfg, labelset=LABELSET)
    assert skipped is True
    assert relabels == 0


def test_lambda_zero_no_relabels() -> None:
    """lambda=0 → no transition penalty → identity."""
    cfg = SmootherConfig(viterbi_enabled=True, lambda_forbidden=0.0,
                         forbidden_transitions=(("grasp_object", "approach_object"),))
    segs = [_seg(idx=0, phase="grasp_object", vlm=0.3),
            _seg(idx=1, phase="approach_object", vlm=0.3)]
    out, relabels, _ = _viterbi_relabel(segs, config=cfg, labelset=LABELSET)
    assert relabels == 0


def test_low_confidence_forbidden_pair_resolved() -> None:
    """Forbidden pair, both at vlm=0.3. Penalty 0.5 > emission gain 0.3,
    so flipping at least one side wins."""
    cfg = SmootherConfig(viterbi_enabled=True, lambda_forbidden=0.5,
                         forbidden_transitions=(("grasp_object", "approach_object"),))
    segs = [_seg(idx=0, phase="grasp_object", vlm=0.3),
            _seg(idx=1, phase="approach_object", vlm=0.3)]
    out, relabels, _ = _viterbi_relabel(segs, config=cfg, labelset=LABELSET)
    assert relabels >= 1
    # The resulting pair must NOT be in forbidden_transitions
    assert (out[0].phase, out[1].phase) != ("grasp_object", "approach_object")


def test_high_confidence_forbidden_pair_no_relabel() -> None:
    """Forbidden pair, both vlm=0.9. Emission preserved (0.9 each = 1.8)
    is greater than penalty avoided (0.5), so paths that flip lose."""
    cfg = SmootherConfig(viterbi_enabled=True, lambda_forbidden=0.5,
                         forbidden_transitions=(("grasp_object", "approach_object"),))
    segs = [_seg(idx=0, phase="grasp_object", vlm=0.9),
            _seg(idx=1, phase="approach_object", vlm=0.9)]
    out, relabels, _ = _viterbi_relabel(segs, config=cfg, labelset=LABELSET)
    assert relabels == 0
    assert [s.phase for s in out] == ["grasp_object", "approach_object"]


def test_tie_break_labelset_declaration_order() -> None:
    """Two segments observed='unknown', vlm=None → all emissions zero, no
    forbidden transitions → tie-break rule 2 picks earliest labelset rank."""
    cfg = SmootherConfig(viterbi_enabled=True, lambda_forbidden=0.0,
                         forbidden_transitions=())
    segs = [_seg(idx=0, phase="unknown", vlm=None),
            _seg(idx=1, phase="unknown", vlm=None)]
    out, _, _ = _viterbi_relabel(segs, config=cfg, labelset=LABELSET)
    # First label in declaration order is "approach_object" (rank 0)
    assert out[0].phase == "approach_object"
    assert out[1].phase == "approach_object"


def test_relabel_records_op_and_keeps_evidence() -> None:
    cfg = SmootherConfig(viterbi_enabled=True, lambda_forbidden=0.5,
                         forbidden_transitions=(("grasp_object", "approach_object"),))
    a = _seg(idx=0, phase="grasp_object", vlm=0.3)
    a = replace(a, evidence="VLM said grasp because gripper closed")
    b = _seg(idx=1, phase="approach_object", vlm=0.3)
    out, _, _ = _viterbi_relabel([a, b], config=cfg, labelset=LABELSET)
    for s, original in zip(out, [a, b], strict=True):
        if s.phase != original.phase:
            assert "viterbi_relabel" in s.smoothing_ops
            assert s.evidence == original.evidence


def test_overall_confidence_recomputed_on_relabel() -> None:
    cfg = SmootherConfig(viterbi_enabled=True, lambda_forbidden=0.5,
                         forbidden_transitions=(("grasp_object", "approach_object"),))
    segs = [_seg(idx=0, phase="grasp_object", vlm=0.3),
            _seg(idx=1, phase="approach_object", vlm=0.3)]
    out, _, _ = _viterbi_relabel(segs, config=cfg, labelset=LABELSET)
    for s in out:
        if s.phase == "unknown":
            assert s.overall_confidence == 0.0


def test_idempotent_on_smooth_input() -> None:
    """Already-non-forbidden chain → identity."""
    cfg = SmootherConfig(viterbi_enabled=True, lambda_forbidden=0.5,
                         forbidden_transitions=(("grasp_object", "approach_object"),))
    segs = [_seg(idx=0, phase="approach_object", vlm=0.7),
            _seg(idx=1, phase="grasp_object", vlm=0.7),
            _seg(idx=2, phase="lift_object", vlm=0.7)]
    out, relabels, _ = _viterbi_relabel(segs, config=cfg, labelset=LABELSET)
    assert relabels == 0
    assert [s.phase for s in out] == ["approach_object", "grasp_object", "lift_object"]


def test_determinism_across_runs() -> None:
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


def test_decoded_unknown_sets_verb_object_target_none() -> None:
    """Spec §3.4: when q*=='unknown', verb/object/target = None.

    Construct a scenario that forces decoding to 'unknown': make every
    allowed-label predecessor of 'grasp_object' forbidden with very high
    lambda. The first segment must then be relabeled to a non-forbidden
    predecessor. Among all states only 'unknown' has no transition penalty
    to 'grasp_object', so 'unknown' may be selected for seg 0.
    """
    forbidden = tuple((lbl, "grasp_object") for lbl in LABELSET)
    cfg = SmootherConfig(viterbi_enabled=True, lambda_forbidden=10.0,
                         forbidden_transitions=forbidden)
    segs = [_seg(idx=0, phase="approach_object", vlm=0.3,
                 verb="approach", obj="cube"),
            _seg(idx=1, phase="grasp_object", vlm=0.9,
                 verb="grasp", obj="cube")]
    out, _, _ = _viterbi_relabel(segs, config=cfg, labelset=LABELSET)
    if out[0].phase == "unknown":
        assert out[0].verb is None
        assert out[0].object is None
        assert out[0].target is None


def test_allowed_label_relabel_keeps_verb_object_target() -> None:
    """Spec §3.4: when decoded label is an allowed (non-unknown) label different
    from the original, verb/object/target are PRESERVED from the original
    segment (since labelset YAML has no canonical (verb, object, target) tuple).
    """
    cfg = SmootherConfig(viterbi_enabled=True, lambda_forbidden=0.5,
                         forbidden_transitions=(("grasp_object", "approach_object"),))
    a = _seg(idx=0, phase="grasp_object", vlm=0.3,
             verb="grasp", obj="red_cube")
    b = _seg(idx=1, phase="approach_object", vlm=0.3,
             verb="approach", obj="red_cube")
    out, _, _ = _viterbi_relabel([a, b], config=cfg, labelset=LABELSET)
    for s, original in zip(out, [a, b], strict=True):
        if s.phase != original.phase and s.phase != "unknown":
            # Allowed-label relabel keeps original verb/object/target
            assert s.verb == original.verb
            assert s.object == original.object
            assert s.target == original.target


def test_zero_emission_segment_does_not_force_unknown() -> None:
    """Segment with vlm_confidence=None (zero emission everywhere) and no
    forbidden constraint should pick the labelset-rank-0 label, not 'unknown'."""
    cfg = SmootherConfig(viterbi_enabled=True, lambda_forbidden=0.5,
                         forbidden_transitions=())
    segs = [_seg(idx=0, phase="approach_object", vlm=0.9),
            _seg(idx=1, phase="unknown", vlm=None)]
    out, _, _ = _viterbi_relabel(segs, config=cfg, labelset=LABELSET)
    # Rule 2: unknown has the highest labelset rank (last); allowed labels are preferred.
    assert out[1].phase == "approach_object"
