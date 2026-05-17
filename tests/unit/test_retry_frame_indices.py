"""Tests for _compute_retry_frame_indices (spec §5.3)."""

from mimicanno.object_tracker.propagator import _compute_retry_frame_indices


def test_typical_case() -> None:
    # n_frames=150, [0.5, 0.25, 0.75] → [75, 37, 112]
    # (int(0.5*150)=75, int(0.25*150)=37, int(0.75*150)=112)
    assert _compute_retry_frame_indices(150, [0.5, 0.25, 0.75]) == [75, 37, 112]


def test_n_frames_zero_returns_empty() -> None:
    assert _compute_retry_frame_indices(0, [0.5, 0.25, 0.75]) == []


def test_n_frames_one_returns_empty() -> None:
    # n_frames=1 means only frame 0 exists; nothing to retry.
    assert _compute_retry_frame_indices(1, [0.5, 0.25, 0.75]) == []


def test_small_n_frames_dedup() -> None:
    # n_frames=3, [0.5, 0.25, 0.75]
    # int(0.5*3)=1, int(0.25*3)=0, int(0.75*3)=2
    # 0 is filtered (it's the initial attempt), dedup leaves [1, 2]
    assert _compute_retry_frame_indices(3, [0.5, 0.25, 0.75]) == [1, 2]


def test_frac_one_clamps_to_n_frames_minus_one() -> None:
    # int(1.0*100)=100 but max valid index is 99
    assert _compute_retry_frame_indices(100, [1.0]) == [99]


def test_negative_frac_clamps_to_zero_then_filtered() -> None:
    # frac=-0.5 → clamp to 0 → equals initial frame → filtered out
    assert _compute_retry_frame_indices(100, [-0.5, 0.5]) == [50]


def test_empty_fractions_returns_empty() -> None:
    assert _compute_retry_frame_indices(100, []) == []


def test_dedup_preserves_order() -> None:
    # [0.5, 0.5, 0.25, 0.25] → first 0.5 wins, first 0.25 wins
    assert _compute_retry_frame_indices(100, [0.5, 0.5, 0.25, 0.25]) == [50, 25]
