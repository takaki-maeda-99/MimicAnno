"""Shared pytest fixtures for mimicanno tests.

Side-effect: import ``torch`` at module load so that ``sys.modules['torch']``
is the *real* package before any test that does
``sys.modules.setdefault('torch', <fake>)`` runs (notably
``tests/unit/test_local_gemma_skeleton.py``). Without this, alphabetical
collection order causes that test to install a MagicMock under
``torch`` and poison every later test that legitimately needs torch
(e.g. anything that imports ``sam3.model_builder``).
"""

from __future__ import annotations

try:
    import torch  # noqa: F401  (intentional eager import)
except ImportError:  # pragma: no cover - torch is a hard dep in dev/test env
    pass
