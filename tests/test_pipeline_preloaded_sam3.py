"""annotate_episode_phase3: preloaded_sam3_runtime 経路の挙動。

field の存在確認 + 実コードに preloaded_sam3_runtime / _close_all_sessions
の参照があることの spot-check。実モデル経路の e2e は実機 smoke (Task 6) で
カバーする。
"""
from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import MagicMock


def test_preloaded_sam3_field_accessible() -> None:
    """AnnotateRequest に preloaded_sam3_runtime / preloaded_vlm を渡せる。"""
    from mimicanno.pipeline import AnnotateRequest

    fake_sam3 = MagicMock()
    fake_vlm = MagicMock()
    req = AnnotateRequest(
        video=Path("/dev/null"),
        parquet=Path("/dev/null"),
        task="dummy",
        robot_adapter_name="generic",
        robot_adapter_config_path=None,
        labels_path=None,
        runs_root=Path("/tmp/dummy"),
        link_video=False,
        force=True,
        config=MagicMock(),
        preloaded_vlm=fake_vlm,
        preloaded_sam3_runtime=fake_sam3,
    )
    assert req.preloaded_sam3_runtime is fake_sam3
    assert req.preloaded_vlm is fake_vlm


def test_default_request_has_no_preloaded_sam3() -> None:
    """preloaded_sam3_runtime のデフォルトは None。"""
    from mimicanno.pipeline import AnnotateRequest

    req = AnnotateRequest(
        video=Path("/dev/null"),
        parquet=Path("/dev/null"),
        task="dummy",
        robot_adapter_name="generic",
        robot_adapter_config_path=None,
        labels_path=None,
        runs_root=Path("/tmp/dummy"),
        link_video=False,
        force=True,
        config=MagicMock(),
    )
    assert req.preloaded_sam3_runtime is None
    assert req.preloaded_vlm is None


def test_preloaded_sam3_branch_exists_in_pipeline_source() -> None:
    """T2: annotate_episode_phase3 のソースに preloaded_sam3_runtime 分岐と
    _close_all_sessions 呼び出しがあること。e2e コントロールフロー検証は
    Task 6 の実機 smoke で行うため、ここでは静的に branch の存在だけ確認。"""
    from mimicanno import pipeline as P

    src = inspect.getsource(P.annotate_episode_phase3)
    assert "preloaded_sam3_runtime" in src, "preloaded SAM3 branch missing"
    assert "_close_all_sessions" in src, "_close_all_sessions call missing"
    assert "_owns_sam3_runtime" in src, "_owns_sam3_runtime flag missing"
