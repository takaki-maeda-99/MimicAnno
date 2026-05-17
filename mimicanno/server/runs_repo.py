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

import json
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

    def _read_index_bytes(self, path: Path) -> bytes | None:
        """Read ``path`` with the same retry policy as ``read_index``.

        Returns the file bytes on success; ``None`` if the file is still
        not present after ``_RETRY_COUNT`` attempts. The retry absorbs
        the publish dir-gap window (publish.py:141-165) so a run-set
        that's mid-publish is not silently dropped from the merged listing.
        """
        for _ in range(_RETRY_COUNT):
            try:
                return path.read_bytes()
            except FileNotFoundError:
                time.sleep(_RETRY_SLEEP_SEC)
        return None

    def read_merged_index(self) -> bytes:
        """Merge index.json across root + subdirs.

        Each row is tagged with its origin ``run_set``:
        - rows from ``<root>/index.json`` → ``run_set: "."``
        - rows from ``<root>/<sub>/index.json`` → ``run_set: "<sub>"``

        Read uses the same retry loop as ``read_index`` so a run-set
        whose index is mid-rewrite (visible to ``iterdir`` but momentarily
        missing during ``read_bytes``) is not silently dropped. A run-set
        published entirely after ``iterdir()`` is naturally missed —
        callers needing absolute freshness should re-request. Subdirs without
        index.json or with malformed JSON are silently skipped.
        Empty result: ``{"schema_version":"0.1.0","runs":[]}``.

        Row ordering: root rows first (run_set='.'), then subdirs in
        ``sorted(iterdir())`` order, preserving on-disk row order within
        each index. Frontend re-sorts by ``generated_at`` for display.

        This is the read path for ``/api/runs/index.json`` without
        ``?run_set=``. Write paths and ``?run_set=`` reads remain
        per-run-set and are not affected.
        """
        merged: list[dict] = []

        def _ingest(idx_path: Path, run_set: str) -> None:
            raw = self._read_index_bytes(idx_path)
            if raw is None:
                return
            try:
                doc = json.loads(raw)
            except json.JSONDecodeError:
                return
            for row in doc.get("runs", []):
                if not isinstance(row, dict):
                    continue
                merged.append({**row, "run_set": run_set})

        root_index = self.root / "index.json"
        if root_index.exists():
            _ingest(root_index, ".")

        if self.root.is_dir():
            for entry in sorted(self.root.iterdir()):
                if not entry.is_dir():
                    continue
                sub_index = entry / "index.json"
                if sub_index.exists():
                    _ingest(sub_index, entry.name)

        body = {"schema_version": "0.1.0", "runs": merged}
        return json.dumps(body).encode("utf-8")

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
