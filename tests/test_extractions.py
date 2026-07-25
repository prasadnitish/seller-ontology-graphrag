from __future__ import annotations

import json
from pathlib import Path

import pytest

from graphkit.compiler import compile_workspace
from graphkit.workspace import approve_workspace


def test_source_backed_text_extraction_is_compiled(incident_workspace: Path) -> None:
    quote = "The Authentication Service runbook uses a staged rollback."
    runbook = incident_workspace / "sources" / "runbook.md"
    runbook.write_text(runbook.read_text() + f"\n\n{quote}\n")
    from graphkit.workspace import atomic_write, profile_sources

    profile = profile_sources(incident_workspace / "sources")
    atomic_write(
        incident_workspace / "source-profile.json",
        profile.model_dump_json(indent=2) + "\n",
    )
    extraction = {
        "id": "documented_owner",
        "source": "runbook",
        "subject_type": "Service",
        "subject_key": "svc-auth",
        "relationship_type": "OWNED_BY",
        "object_type": "Team",
        "object_key": "team-identity",
        "exact_quote": quote,
        "locator": "paragraph:99",
        "confidence": 0.96,
    }
    (incident_workspace / "extractions.jsonl").write_text(
        json.dumps(extraction) + "\n"
    )
    approve_workspace(incident_workspace)

    graph = compile_workspace(incident_workspace)

    relationship = next(item for item in graph.relationships if item.id == "text:documented_owner")
    assert relationship.provenance.quote == quote
    assert relationship.provenance.confidence == 0.96


def test_unverifiable_text_quote_is_rejected(incident_workspace: Path) -> None:
    extraction = {
        "id": "invented_fact",
        "source": "runbook",
        "subject_type": "Service",
        "subject_key": "svc-auth",
        "relationship_type": "OWNED_BY",
        "object_type": "Team",
        "object_key": "team-identity",
        "exact_quote": "This sentence does not exist.",
        "locator": "paragraph:1",
        "confidence": 0.99,
    }
    (incident_workspace / "extractions.jsonl").write_text(
        json.dumps(extraction) + "\n"
    )

    with pytest.raises(ValueError, match="quote is not present"):
        compile_workspace(incident_workspace)
