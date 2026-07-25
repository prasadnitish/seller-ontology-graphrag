from __future__ import annotations

from pathlib import Path

from graphkit.compiler import compile_workspace, validate_workspace
from graphkit.workspace import (
    approval_is_current,
    load_spec,
    save_spec,
    spec_hash,
)


def test_incident_workspace_compiles_without_dangling_relationships(
    incident_workspace: Path,
) -> None:
    report = validate_workspace(incident_workspace)
    graph = compile_workspace(incident_workspace)

    assert report.valid
    assert report.unmapped_fields == 0
    assert graph.counts == {"nodes": 17, "relationships": 17, "chunks": 36}
    node_ids = {node.id for node in graph.nodes}
    assert all(
        relationship.from_id in node_ids and relationship.to_id in node_ids
        for relationship in graph.relationships
    )
    assert all(item.provenance.source_path for item in graph.nodes)
    assert all(item.provenance.source_path for item in graph.relationships)
    assert all(item.provenance.source_path for item in graph.corpus)


def test_layout_only_change_preserves_approval(incident_workspace: Path) -> None:
    spec = load_spec(incident_workspace)
    original_hash = spec_hash(spec)
    spec.ui.nodes["Service"]["x"] += 10
    save_spec(incident_workspace, spec)

    assert spec_hash(load_spec(incident_workspace)) == original_hash
    assert approval_is_current(incident_workspace)


def test_semantic_change_invalidates_approval(incident_workspace: Path) -> None:
    spec = load_spec(incident_workspace)
    spec.metadata.description = "Changed meaning"
    save_spec(incident_workspace, spec)

    assert not approval_is_current(incident_workspace)
