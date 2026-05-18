"""Resident license-hygiene audit.

Scans all tracked files for forbidden tokens and fails if any match. The
scan target set is derived from ``git ls-files``, which automatically
respects the project's gitignore policy and excludes submodule contents.

Self-tests at the bottom of this file verify that the regex set still
matches representative positive examples and rejects representative
negative examples — they prevent silent regression of the gate.

The audit module is the **only** tracked file in which the forbidden
literal tokens legitimately appear (inside ``POSITIVE_CASES`` and inside
the regex pattern definitions themselves). It self-excludes from its own
scan via ``p.resolve() == THIS_FILE`` so the broad sweep does not flag
itself.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
THIS_FILE = Path(__file__).resolve()

FORBIDDEN_EXACT = [
    r"\bHaMeR\w*",
    r"\b_HAMER\w*",
    r"\bHamerRaw\w*",
    r"\bMANO\w*",
    r"\bSMPL\w*",
    r"\bFreiHAND\w*",
    r"\bfreihand\w*",
    r"\bpavlakos\w*",
    r"\bvitpose\w*",
    r"\bViTPose\w*",
    r"\bfetch_demo_data\w*",
]
FORBIDDEN_ICASE = [
    r"tue\.mpg\.de",
    r"mpi-inf",
    r"\.hamer\w*",
    r"\bsmpl\w*",
]
FORBIDDEN_HAMER_LOWER = [
    r"(?<![A-Za-z0-9_])hamer\w*",
]
FORBIDDEN_MANO_LOWER = [
    r"\bmano_\w*",
    r"\bmano\.\w*",
    r"/mano(/|$)",
]
FORBIDDEN_COMPOSITE = [
    r"\bmano_vertices\b",
    r"\bhand_vertices\b",
    r"\bmano_betas\b",
    r"\bhand_betas\b",
    r"\bmano_pose\b",
    r"\bhand_pose\b",
]

CASE_SENSITIVE = (
    FORBIDDEN_EXACT
    + FORBIDDEN_HAMER_LOWER
    + FORBIDDEN_MANO_LOWER
    + FORBIDDEN_COMPOSITE
)
CASE_INSENSITIVE = FORBIDDEN_ICASE


def _tracked_paths() -> list[Path]:
    """Return tracked files via ``git ls-files``, excluding this audit module."""
    out = subprocess.check_output(
        ["git", "ls-files"], cwd=REPO_ROOT, text=True
    )
    paths: list[Path] = []
    for rel in out.splitlines():
        p = REPO_ROOT / rel
        if not p.is_file():
            continue
        if p.resolve() == THIS_FILE:
            continue
        paths.append(p)
    return paths


def _scan(text: str) -> list[str]:
    """Return human-readable hit descriptions for any forbidden token match."""
    hits: list[str] = []
    for pat in CASE_SENSITIVE:
        for m in re.finditer(pat, text):
            hits.append(f"{pat} -> {m.group()!r}")
    for pat in CASE_INSENSITIVE:
        for m in re.finditer(pat, text, re.IGNORECASE):
            hits.append(f"{pat} -> {m.group()!r}")
    return hits


def test_repository_is_license_hygiene_clean():
    """Fail if any tracked file contains a forbidden token."""
    report: list[str] = []
    for p in _tracked_paths():
        try:
            text = p.read_text(errors="replace")
        except Exception as exc:  # noqa: BLE001 — capture-and-continue is intentional
            report.append(f"{p}: read failed: {exc}")
            continue
        hits = _scan(text)
        if hits:
            rel = p.relative_to(REPO_ROOT)
            report.append(f"{rel}:")
            for h in hits[:10]:
                report.append(f"  {h}")
    if report:
        pytest.fail("license hygiene violations:\n" + "\n".join(report))


# ---------------------------------------------------------------------------
# Self-tests — verify the regex set still matches the categories it should.
# These cases prevent the gate from silently breaking if patterns drift.
# ---------------------------------------------------------------------------

POSITIVE_CASES = [
    "_HAMER_ROOT = Path('/x')",
    "from hamer.utils import recursive_to",
    "MANO_LEFT = 'left'",
    "MANO_RIGHT_HAND = True",
    "self.smplx_model = build_model()",
    "fetch_demo_data.sh --target",
    "venv: .hamer/bin/python",
    "from mano.layer import LayerThing",
    "https://ps.is.tue.mpg.de/",
    "hand_pose: shape (15, 3, 3)",
    "FreiHAND_v2",
    "pavlakos2024",
    "ViTPose-Large",
    "vitpose_inference",
    "SMPLX_NEUTRAL",
]

NEGATIVE_CASES = [
    "self.adam_betas = (0.9, 0.999)",
    "global_orient = palm_frame(joints, is_right=True)",
    "vertex_count = mesh.n_vertices",
    "humanoid pose model",
    "manometer pressure",
    "manor house",
    "the_<legacy_token>_thing  # synthetic placeholder, contains no real token",
    "MediaPipe Hand Landmarker",
    "Apache 2.0",
]


@pytest.mark.parametrize("case", POSITIVE_CASES)
def test_positive_cases_trigger(case: str):
    """Each POSITIVE case must produce at least one hit."""
    assert _scan(case), f"expected hit for: {case!r}"


@pytest.mark.parametrize("case", NEGATIVE_CASES)
def test_negative_cases_do_not_trigger(case: str):
    """Each NEGATIVE case must produce zero hits (avoids false positives)."""
    hits = _scan(case)
    assert not hits, f"unexpected hits {hits!r} for: {case!r}"
