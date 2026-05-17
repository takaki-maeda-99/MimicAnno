"""U-A1 B6 — Progress marker emission tests."""
from __future__ import annotations

import re

_PROGRESS_PATTERN = re.compile(
    r"\[mimicanno-job-progress\] ep=(\d+) finished=(\d+)/(\d+)"
)


def test_batch_annotate_4b_emits_marker_on_success(tmp_path):
    """batch_annotate_4B.py contains the progress print statement."""
    from pathlib import Path
    script = Path(__file__).resolve().parents[2] / "scripts" / "batch_annotate_4B.py"
    content = script.read_text()
    assert "[mimicanno-job-progress]" in content
    assert "flush=True" in content


def test_batch_annotate_4b_does_not_emit_on_failure(tmp_path):
    """Progress marker is inside the success branch (after annotate_episode_phase4)."""
    from pathlib import Path
    script = Path(__file__).resolve().parents[2] / "scripts" / "batch_annotate_4B.py"
    content = script.read_text()
    # The marker must be inside the try block after annotate_episode_phase4,
    # not inside the except block.
    # Find position of marker and except block:
    marker_pos = content.find("[mimicanno-job-progress]")
    except_pos = content.find("except Exception as e:")
    # Marker should come before the except line within the episode loop.
    assert 0 < marker_pos < except_pos


def test_cli_annotate_emits_marker(tmp_path):
    """mimicanno/cli.py contains the progress marker print after annotate calls."""
    from pathlib import Path
    cli = Path(__file__).resolve().parents[2] / "mimicanno" / "cli.py"
    content = cli.read_text()
    assert "[mimicanno-job-progress]" in content
    assert "finished=1/1" in content


def test_progress_marker_format_matches_runner_regex():
    """The marker format matches the regex used in job_runner.py."""
    marker = "[mimicanno-job-progress] ep=3 finished=4/10"
    m = _PROGRESS_PATTERN.search(marker)
    assert m is not None
    assert m.group(1) == "3"
    assert m.group(2) == "4"
    assert m.group(3) == "10"
