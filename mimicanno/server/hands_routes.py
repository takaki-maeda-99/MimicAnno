"""Hand pipeline routes — /api/hands/ namespace.

Serves hand pipeline output (signals.json, meta.json, source video) from
``hands_root`` (set via ``mimicanno serve --hands-root``).  When
``hands_root`` is None every route returns 503.

Security:
- episode path parameter is validated to be a single path component with no
  ``..`` traversal.
- video_source from meta.json is resolved relative to ``repo_root``
  (= Path.cwd() at server start) and bounds-checked with is_relative_to().
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse, Response

_LOG = logging.getLogger("mimicanno.server")


def _validate_episode(episode: str) -> Optional[Response]:
    """Return a 400 Response if episode is unsafe, else None."""
    parts = Path(episode).parts
    if len(parts) != 1 or parts[0] in ("", "..") or episode.startswith("/"):
        return JSONResponse(
            {"error": "invalid episode name", "episode": episode}, status_code=400
        )
    return None


def make_hands_router(
    hands_root: Optional[Path],
    repo_root: Path,
) -> APIRouter:
    """Build the /api/hands/ router.

    hands_root=None → every route returns 503 Service Unavailable.
    repo_root is used to resolve and sandbox video_source paths.
    """
    router = APIRouter(prefix="/api/hands")

    def _503() -> Response:
        return JSONResponse({"error": "hands_root not configured"}, status_code=503)

    @router.get("/index.json")
    async def hands_index() -> Response:
        if hands_root is None:
            return _503()
        episodes = []
        for ep_dir in sorted(p for p in hands_root.iterdir() if p.is_dir()):
            meta_path = ep_dir / "meta.json"
            if not meta_path.exists():
                continue
            try:
                meta = json.loads(meta_path.read_text())
            except Exception:
                continue
            signals_path = ep_dir / "signals.json"
            signals_ready = False
            if signals_path.exists():
                try:
                    sig = json.loads(signals_path.read_text())
                    signals_ready = sig.get("schema_version") == 2
                except Exception:
                    signals_ready = False
            ep_id = ep_dir.name
            depth_video_ready = False
            depth_source = meta.get("depth_source")
            if isinstance(depth_source, str) and depth_source:
                depth_meta = meta.get("depth_meta") or {}
                fp = depth_meta.get("frames_processed")
                fs = depth_meta.get("frames_skipped_existing", 0)
                vtf = meta.get("video_total_frames")
                frames_ok = (
                    isinstance(fp, int)
                    and isinstance(fs, int)
                    and isinstance(vtf, int)
                    and fp + fs == vtf
                )
                if frames_ok:
                    depth_path = (repo_root / depth_source / "viz_depth.mp4").resolve()
                    try:
                        if depth_path.is_relative_to(repo_root.resolve()) and depth_path.exists():
                            depth_video_ready = True
                    except ValueError:
                        depth_video_ready = False
            episodes.append({
                "episode_id": ep_id,
                "fps": meta.get("video_fps"),
                "total_frames": meta.get("video_total_frames"),
                "frames_with_hands": meta.get("frames_with_hands"),
                "signals_ready": signals_ready,
                "depth_video_ready": depth_video_ready,
                "video_url": f"{ep_id}/video",
                "signals_url": f"{ep_id}/signals.json",
                "meta_url": f"{ep_id}/meta.json",
            })
        return JSONResponse({"schema_version": "0.1.0", "episodes": episodes})

    @router.get("/{episode}/meta.json")
    async def hands_meta(episode: str) -> Response:
        if hands_root is None:
            return _503()
        bad = _validate_episode(episode)
        if bad:
            return bad
        path = hands_root / episode / "meta.json"
        if not path.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        return Response(path.read_bytes(), media_type="application/json")

    @router.get("/{episode}/signals.json")
    async def hands_signals(episode: str) -> Response:
        if hands_root is None:
            return _503()
        bad = _validate_episode(episode)
        if bad:
            return bad
        path = hands_root / episode / "signals.json"
        if not path.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        return Response(path.read_bytes(), media_type="application/json")

    @router.get("/{episode}/video")
    async def hands_video(episode: str) -> Response:
        if hands_root is None:
            return _503()
        bad = _validate_episode(episode)
        if bad:
            return bad
        meta_path = hands_root / episode / "meta.json"
        if not meta_path.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        try:
            meta = json.loads(meta_path.read_text())
        except Exception:
            return JSONResponse({"error": "meta.json parse error"}, status_code=500)
        video_source = meta.get("video_source")
        if video_source is None:
            return JSONResponse(
                {"error": "meta.json missing video_source"}, status_code=400
            )
        video_path = (repo_root / video_source).resolve()
        try:
            if not video_path.is_relative_to(repo_root.resolve()):
                return JSONResponse(
                    {"error": "video_source outside repo_root"}, status_code=400
                )
        except ValueError:
            return JSONResponse(
                {"error": "video_source outside repo_root"}, status_code=400
            )
        if not video_path.exists():
            return JSONResponse({"error": "video file not found"}, status_code=404)
        return FileResponse(str(video_path), media_type="video/mp4")

    @router.get("/{episode}/depth_video")
    async def hands_depth_video(episode: str) -> Response:
        if hands_root is None:
            return _503()
        bad = _validate_episode(episode)
        if bad:
            return bad
        meta_path = hands_root / episode / "meta.json"
        if not meta_path.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        try:
            meta = json.loads(meta_path.read_text())
        except Exception:
            return JSONResponse({"error": "meta.json parse error"}, status_code=500)
        depth_source = meta.get("depth_source")
        if not isinstance(depth_source, str) or not depth_source:
            return JSONResponse(
                {"error": "meta.json missing depth_source"}, status_code=400
            )
        depth_path = (repo_root / depth_source / "viz_depth.mp4").resolve()
        try:
            if not depth_path.is_relative_to(repo_root.resolve()):
                return JSONResponse(
                    {"error": "depth_source outside repo_root"}, status_code=400
                )
        except ValueError:
            return JSONResponse(
                {"error": "depth_source outside repo_root"}, status_code=400
            )
        if not depth_path.exists():
            return JSONResponse({"error": "viz_depth.mp4 not found"}, status_code=404)
        return FileResponse(str(depth_path), media_type="video/mp4")

    return router
