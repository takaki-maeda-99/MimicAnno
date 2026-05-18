import numpy as np
import pytest

from mimicanno.hand_pipeline.pipeline import _palm_frame


def _flat_hand(scale: float = 0.1) -> np.ndarray:
    """21 wrist-centred landmarks lying on the z=0 plane."""
    j = np.zeros((21, 3), dtype=np.float32)
    j[0]  = [0.0, 0.0, 0.0]            # wrist
    j[5]  = [scale,        0.0, 0.0]   # index-MCP
    j[9]  = [scale,  scale * 0.5, 0.0] # middle-MCP
    j[17] = [scale,  scale * 1.0, 0.0] # pinky-MCP
    return j


def test_palm_frame_right_hand_orthonormal():
    R = _palm_frame(_flat_hand(), is_right=True)
    assert R.shape == (3, 3)
    np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-5)
    assert np.linalg.det(R) > 0.99


def test_palm_frame_handedness_flips_normal():
    j = _flat_hand()
    Rr = _palm_frame(j, is_right=True)
    Rl = _palm_frame(j, is_right=False)
    # Column 1 is the palm normal in our convention.
    np.testing.assert_allclose(Rr[:, 1], -Rl[:, 1], atol=1e-5)


def test_palm_frame_column_order():
    """R = [side | normal | forward] with column convention."""
    R = _palm_frame(_flat_hand(), is_right=True)
    side, normal, forward = R[:, 0], R[:, 1], R[:, 2]
    # forward ≈ unit(middle - wrist) = (1, 0.5, 0) normalised, but the
    # final forward axis is re-orthogonalised. Only sign and rough direction:
    assert forward[0] > 0.0   # points along +x family
    assert abs(normal[2]) > 0.9  # mostly along z (palm normal)
    # side is normal × forward, must be unit length
    np.testing.assert_allclose(np.linalg.norm(side), 1.0, atol=1e-5)


def test_palm_frame_degenerate_returns_identity():
    j = np.zeros((21, 3), dtype=np.float32)
    # all landmarks at the origin → cross product zero → degenerate
    R = _palm_frame(j, is_right=True)
    np.testing.assert_allclose(R, np.eye(3, dtype=np.float32))
