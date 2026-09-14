"""Keep pytest's temporary files in a fresh, project-local directory.

Some Windows environments deny access to a shared per-user pytest directory in
AppData/Local/Temp. A unique directory also avoids stale ACLs from prior runs.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4

import pytest


PROJECT_ROOT = Path(__file__).resolve().parent


def pytest_configure(config: pytest.Config) -> None:
    """Choose an isolated base for tmp_path unless the caller supplied one."""
    if config.option.basetemp:
        return
    path = PROJECT_ROOT / f".pytest-run-{uuid4()}"
    config.option.basetemp = str(path)
    config._proctoring_lab_basetemp = path


def pytest_unconfigure(config: pytest.Config) -> None:
    """Remove only the temporary directory this pytest invocation created."""
    path = getattr(config, "_proctoring_lab_basetemp", None)
    if path is None or not path.exists():
        return
    resolved = path.resolve()
    if resolved.parent != PROJECT_ROOT or not resolved.name.startswith(".pytest-run-"):
        raise RuntimeError(f"Refusing to remove unexpected pytest directory: {resolved}")
    shutil.rmtree(resolved)

