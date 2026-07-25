from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from graphkit.workspace import approve_workspace, atomic_write, profile_sources


@pytest.fixture
def incident_workspace(tmp_path: Path) -> Path:
    source = Path(__file__).parents[1] / "examples" / "incidents"
    target = tmp_path / "incidents"
    shutil.copytree(source, target)
    profile = profile_sources(target / "sources")
    atomic_write(
        target / "source-profile.json",
        profile.model_dump_json(indent=2) + "\n",
    )
    approve_workspace(target)
    return target
