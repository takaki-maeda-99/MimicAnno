# mimicanno/__main__.py
"""Entrypoint for ``python -m mimicanno``.

Forwards to the Typer ``app`` defined in :mod:`mimicanno.cli`. The console
script in ``[project.scripts]`` (``mimicanno = "mimicanno.cli:app"``) covers
the installed-binary path; this module covers the ``python -m mimicanno`` path
used by tests.
"""

from __future__ import annotations

from mimicanno.cli import app

if __name__ == "__main__":
    app()
