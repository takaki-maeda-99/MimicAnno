"""Pre-flight model / checkpoint resolution.

- ``resolve_vlm_model`` (spec §2.5) — parse ``--vlm-model``, route to one of
  three resolution cases, return a frozen (model_id, resolved_checkpoint)
  tuple. The ONLY caller of ``huggingface_hub`` in the codebase.
- ``resolve_sam3_checkpoint`` (spec §8 ``sam3_checkpoint_not_found``) —
  validate a local SAM3 weights file and return its ``sha256:<hex>``. Caches
  the digest by ``(mtime_ns, size)`` so multi-GB SAM3 weights are not rehashed
  on every CLI invocation (2026-05-04 SAM3 backend swap, plan Task 2).

The rest of the system accepts the resolved strings verbatim.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from mimicanno.errors import SAM3CheckpointNotFound, VLMModelNotFound
from mimicanno.hashing import sha256_file

_LOG = logging.getLogger(__name__)

SHA40_REGEX = re.compile(r"^[0-9a-f]{40}$")
SHA256_REGEX = re.compile(r"^[0-9a-f]{64}$")
FIXTURE_URI_PREFIX = "fixture://"

# Override-able for tests via the MIMICANNO_SAM3_SHA_CACHE_DIR env var.
_DEFAULT_SAM3_SHA_CACHE_DIR = Path.home() / ".cache" / "mimicanno" / "sam3-sha"


@dataclass(slots=True, frozen=True)
class PreflightResult:
    model_id: str
    resolved_checkpoint: str
    fixture_path: Path | None = None  # populated only for fixture:// URIs


def _hf_model_info(model_id: str, revision: str | None) -> str:
    """Resolve a HuggingFace model_id+revision to a commit sha.
    Isolated for monkeypatching in tests; production import guarded so that
    test environments without `huggingface_hub` installed still pass."""
    from huggingface_hub import HfApi  # local import — only loaded on real path
    info = HfApi().model_info(model_id, revision=revision)
    sha = getattr(info, "sha", None) or getattr(info, "commit_hash", None)
    if not sha or not SHA40_REGEX.match(sha):
        raise OSError(f"HF returned non-sha revision: {sha!r}")
    return str(sha)


def _split_model_at_revision(arg: str) -> tuple[str, str | None]:
    if "@" in arg:
        model_id, _, revision = arg.partition("@")
        return model_id, revision
    return arg, None


def _resolve_fixture(path_str: str) -> PreflightResult:
    p = Path(path_str).resolve()
    if not p.is_file():
        raise VLMModelNotFound(
            model_id="fixture",
            reason=f"fixture file does not exist: {p}",
        )
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    return PreflightResult(
        model_id="fixture", resolved_checkpoint=sha, fixture_path=p,
    )


def resolve_vlm_model(arg: str, *, offline: bool) -> PreflightResult:
    """Resolve a CLI --vlm-model argument to a stable (model_id, sha) tuple.

    Cases (spec §2.5):
      A. <id>@<40-hex-sha>  → accept directly, no HF lookup. Offline-safe.
      B. <id> or <id>@<branch_or_tag> → HF lookup. Forbidden when offline=True.
      C. fixture://<path>   → sha = sha256(file content).

    Raises VLMModelNotFound on any resolution failure (Tier 1 abort, spec §4.2).
    """
    if arg.startswith(FIXTURE_URI_PREFIX):
        return _resolve_fixture(arg[len(FIXTURE_URI_PREFIX):])

    model_id, revision = _split_model_at_revision(arg)

    # Case A: explicit 40-hex sha.
    if revision is not None and SHA40_REGEX.match(revision):
        return PreflightResult(model_id=model_id, resolved_checkpoint=revision)

    # Case B: needs HF API lookup.
    if offline:
        raise VLMModelNotFound(
            model_id=arg,
            reason=(
                "explicit 40-hex commit sha required after '@' for --offline runs "
                "(use '<id>@<40-hex-sha>')"
            ),
        )

    try:
        sha = _hf_model_info(model_id, revision)
    except Exception as e:  # network, 404, auth — all collapse into Tier 1.
        raise VLMModelNotFound(model_id=arg, reason=str(e)) from e
    return PreflightResult(model_id=model_id, resolved_checkpoint=sha)


# SAM3 checkpoint resolution (spec §8 + 2026-05-04 sha cache)


def _sam3_sha_cache_dir() -> Path:
    override = os.environ.get("MIMICANNO_SAM3_SHA_CACHE_DIR")
    return Path(override) if override else _DEFAULT_SAM3_SHA_CACHE_DIR


def _read_cached_sha(cache_path: Path) -> str | None:
    """Return cached hex sha or None if cache miss / corrupt / unreadable.

    A "corrupt" cache (junk content, wrong length, leftover tmp file) is
    treated as a miss — we recompute and overwrite, never fail.
    """
    try:
        content = cache_path.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        return None
    except OSError as exc:
        _LOG.warning("sam3 sha cache read failed at %s: %r", cache_path, exc)
        return None
    if SHA256_REGEX.match(content):
        return content
    _LOG.warning("sam3 sha cache content invalid at %s, recomputing", cache_path)
    return None


def _write_cached_sha(cache_path: Path, sha_hex: str) -> None:
    """Atomically write `sha_hex` to `cache_path`. Errors are logged + swallowed.

    Atomicity: write to a sibling NamedTemporaryFile then `os.replace` — POSIX
    rename is atomic on the same filesystem, so concurrent writers either both
    win (last one observed) or one observes a complete file.
    """
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _LOG.warning("could not create sam3 sha cache dir %s: %r", cache_path.parent, exc)
        return
    try:
        # delete=False so we can rename rather than auto-cleanup.
        with tempfile.NamedTemporaryFile(
            mode="w", dir=str(cache_path.parent), prefix=".tmp-",
            suffix=".sha", delete=False, encoding="ascii",
        ) as tf:
            tf.write(sha_hex)
            tmp_name = tf.name
        os.replace(tmp_name, cache_path)
    except OSError as exc:
        _LOG.warning("sam3 sha cache write failed at %s: %r", cache_path, exc)
        # Best-effort cleanup of any orphaned tmp file.
        try:
            Path(tmp_name).unlink(missing_ok=True)  # type: ignore[name-defined]
        except (NameError, OSError):
            pass


def resolve_sam3_checkpoint(path: Path) -> str:
    """Validate a local SAM3 checkpoint file and return its sha256.

    Caches the digest under ``~/.cache/mimicanno/sam3-sha/<mtime_ns>_<size>.txt``
    (override with ``MIMICANNO_SAM3_SHA_CACHE_DIR`` env var). The cache key is
    purposely path-agnostic — moving the same weights file does not invalidate
    the cache. mtime or size change (i.e. weights overwrite) does.

    Cache failures are silent: missing-cache, corrupt-cache, dir-creation-fail,
    and write-fail all degrade gracefully to "compute the sha and skip caching".

    Parameters
    ----------
    path:
        Filesystem path to the checkpoint file.

    Returns
    -------
    str
        ``"sha256:<64 hex chars>"`` for a regular, readable file.

    Raises
    ------
    SAM3CheckpointNotFound (Tier 1 abort, spec §8) on:
      - missing file (incl. broken symlink chains)
      - non-regular file (e.g., directory, FIFO)
      - permission denied
      - sha256 read failure
    """
    path_str = str(path)

    # `is_file()` follows symlinks AND returns False for broken links/non-files.
    # Distinguishing "not exists" vs "not regular" needs an exists() probe first.
    if not path.exists():
        raise SAM3CheckpointNotFound(
            path=path_str, reason="file not found"
        )
    if not path.is_file():
        raise SAM3CheckpointNotFound(
            path=path_str, reason="not a regular file"
        )

    try:
        st = path.stat()
    except OSError as exc:
        raise SAM3CheckpointNotFound(
            path=path_str, reason=f"stat failed: {exc!r}"
        ) from exc

    cache_path = _sam3_sha_cache_dir() / f"{st.st_mtime_ns}_{st.st_size}.txt"
    cached = _read_cached_sha(cache_path)
    if cached is not None:
        return f"sha256:{cached}"

    try:
        sha_hex = sha256_file(path)
    except PermissionError as e:
        raise SAM3CheckpointNotFound(
            path=path_str, reason="permission denied"
        ) from e
    except OSError as e:
        raise SAM3CheckpointNotFound(
            path=path_str, reason=f"sha256 read failed: {e!r}"
        ) from e

    _write_cached_sha(cache_path, sha_hex)
    return f"sha256:{sha_hex}"
