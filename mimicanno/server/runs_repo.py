"""Phase 5 A — RunsRepository: read-only access to the runs/ tree.

Centralises:

- artifact allow-list (spec §3.3)
- canonical_name regex check (defence in depth before path resolution)
- ``resolve()`` + ``is_relative_to(root)`` traversal guard (symlinks too)
- 100ms × 3 retry on ``FileNotFoundError`` to absorb the publish dir-gap
  window (spec §3.3 / publish.py:141-165)

The repository never takes the runs/index.json.lock; writers use
``tmp.replace`` semantics (runindex.py:45-47) so torn reads are impossible.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from mimicanno.server.errors import MimicAnnoHTTPError

ARTIFACT_ALLOWLIST: frozenset[str] = frozenset({
    "manifest.json",
    "annotation.json",
    "boundaries.json",
    "signals.json",
    "tracks.json",
    # Phase 5 B r1: `?api=1` viewer mode routes ALL artifact fetches
    # through /api/, including the <video> src. Streamed via FileResponse
    # in routes.py so the 1+ MB mp4 doesn't load into memory.
    "video.mp4",
})

# canonical_name shape: episode_id + "__" + run_hash_short.
# Real names look like `episode_000000__e35061106394` — alphanumerics + underscore.
_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")

_RETRY_COUNT = 3
_RETRY_SLEEP_SEC = 0.1


class RunsRepository:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=False)

    # ---------- index.json ----------

    def read_index(self) -> bytes:
        path = self.root / "index.json"
        last_exc: FileNotFoundError | None = None
        for _ in range(_RETRY_COUNT):
            try:
                return path.read_bytes()
            except FileNotFoundError as exc:
                last_exc = exc
                time.sleep(_RETRY_SLEEP_SEC)
        # All retries exhausted — surface as 404.
        raise MimicAnnoHTTPError(
            status=404, code="index_missing",
            message=f"runs/index.json not found under {self.root}",
        ) from last_exc

    # ---------- artifact ----------

    def open_artifact(
        self, name: str, artifact: str,
    ) -> tuple[Path, bytes | None]:
        """Return ``(resolved_path, manifest_bytes_or_None)``.

        For ``artifact == "manifest.json"`` the bytes are returned so the
        route layer can derive an ETag without re-reading. Other artifacts
        return ``None`` so the route can stream via FileResponse (spec
        §4.1 #20 — large file memory safety).
        """
        if not _NAME_RE.match(name):
            raise MimicAnnoHTTPError(
                status=400, code="invalid_name",
                message=f"canonical_name {name!r} contains invalid characters",
            )
        if artifact not in ARTIFACT_ALLOWLIST:
            raise MimicAnnoHTTPError(
                status=404, code="artifact_not_found",
                message=f"artifact {artifact!r} is not in the allow-list",
            )

        # Traversal guard: resolve and confirm prefix.
        candidate = (self.root / name / artifact).resolve(strict=False)
        if not _is_under(candidate, self.root):
            raise MimicAnnoHTTPError(
                status=404, code="artifact_not_found",
                message="artifact resolved outside runs root",
            )

        # Retry to absorb the publish dir-gap (publish.py:141-165).
        last_exc: FileNotFoundError | None = None
        for _ in range(_RETRY_COUNT):
            try:
                if artifact == "manifest.json":
                    body = candidate.read_bytes()
                    return candidate, body
                # Non-manifest: just check existence; route streams via FileResponse.
                if not candidate.exists():
                    raise FileNotFoundError(candidate)
                return candidate, None
            except FileNotFoundError as exc:
                last_exc = exc
                time.sleep(_RETRY_SLEEP_SEC)

        raise MimicAnnoHTTPError(
            status=404, code="run_not_found",
            message=f"run {name!r} not found (or {artifact} missing)",
        ) from last_exc


def list_run_sets(parent: Path) -> list[dict[str, str]]:
    """Return run-set entries under ``parent``.

    Legacy mode (index.json directly under parent): returns ``[{"name": ".",
    "label": "(root)"}]``.  Multi mode: returns one entry per subdirectory
    that contains an index.json, sorted alphabetically.  Empty dir: ``[]``.
    """
    if (parent / "index.json").exists():
        return [{"name": ".", "label": "(root)"}]
    result: list[dict[str, str]] = []
    for d in sorted(parent.iterdir()):
        if d.is_dir() and (d / "index.json").exists():
            result.append({"name": d.name, "label": d.name})
    return result


def _is_under(path: Path, root: Path) -> bool:
    """``Path.is_relative_to`` wrapper that always works under symlinks."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
