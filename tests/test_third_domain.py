from __future__ import annotations

import shutil
from pathlib import Path

from graphkit.compiler import compile_workspace, validate_workspace
from graphkit.workspace import (
    approve_workspace,
    atomic_write,
    profile_sources,
)


def test_third_domain_compiles_without_application_code_changes(
    tmp_path: Path,
) -> None:
    fixture = Path(__file__).parent / "fixtures" / "minimal"
    workspace = tmp_path / "minimal"
    shutil.copytree(fixture, workspace)
    profile = profile_sources(workspace / "sources")
    atomic_write(
        workspace / "source-profile.json",
        profile.model_dump_json(indent=2) + "\n",
    )
    approve_workspace(workspace)

    report = validate_workspace(workspace)
    graph = compile_workspace(workspace)

    assert report.valid
    assert graph.counts == {"nodes": 2, "relationships": 0, "chunks": 3}
    assert {node.properties["name"] for node in graph.nodes} == {"Ada", "Grace"}
