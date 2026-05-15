"""SAM3Runtime._close_all_sessions: sessions のみ閉じてランタイム本体は再利用可能。"""
from __future__ import annotations

from unittest.mock import MagicMock

from mimicanno.object_tracker.sam3_runtime import SAM3Runtime


def _make_runtime_with_sessions(session_ids: list[str]) -> SAM3Runtime:
    """テスト用に open_sessions を直接仕込んだ Runtime を返す。"""
    predictor = MagicMock()
    rt = SAM3Runtime(_predictor=predictor, _device="cpu", _offload_video=False)
    rt._open_sessions = list(session_ids)
    return rt


def test_close_all_sessions_closes_each_open_session() -> None:
    """_close_all_sessions は実際に predictor.handle_request(close_session)
    を各セッション分だけ呼ぶ (回数 + payload を検証)。"""
    rt = _make_runtime_with_sessions(["s1", "s2", "s3"])
    rt._close_all_sessions()

    # 状態
    assert rt._open_sessions == []
    assert rt._predictor is not None  # ランタイム本体は残っている
    assert rt._closed is False  # 再利用可能

    # 実際に sam3 predictor に close_session が3回送られたこと
    close_calls = [
        c for c in rt._predictor.handle_request.call_args_list
        if c.args and c.args[0].get("type") == "close_session"
    ]
    assert len(close_calls) == 3
    assert sorted([c.args[0]["session_id"] for c in close_calls]) == ["s1", "s2", "s3"]


def test_close_all_sessions_idempotent() -> None:
    rt = _make_runtime_with_sessions([])
    rt._close_all_sessions()  # no sessions
    rt._close_all_sessions()  # second call
    assert rt._open_sessions == []
    assert rt._closed is False
    # session が無ければ handle_request は呼ばれない
    assert rt._predictor.handle_request.call_count == 0


def test_close_still_finalizes_runtime() -> None:
    """close() は _close_all_sessions() + 既存の最終処理を両方やる。"""
    rt = _make_runtime_with_sessions(["s1"])
    rt.close()
    assert rt._open_sessions == []
    assert rt._closed is True
    assert rt._predictor is None


def test_close_all_sessions_does_not_drop_predictor() -> None:
    """回帰防止: 誰かが _close_all_sessions に predictor=None を再混入
    したら気づけるようにする。"""
    predictor = MagicMock()
    rt = SAM3Runtime(_predictor=predictor, _device="cpu", _offload_video=False)
    rt._open_sessions = ["s1"]
    rt._close_all_sessions()
    assert rt._predictor is predictor  # 同じインスタンスのまま
