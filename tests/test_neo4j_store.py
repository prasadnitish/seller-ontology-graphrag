from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from graphkit.compiler import compile_workspace
from graphkit.neo4j_store import ingest_graph


class FakeSession:
    def __init__(self, calls: list[tuple[str, dict[str, Any]]]) -> None:
        self.calls = calls

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def run(self, cypher: str, **parameters: Any) -> None:
        self.calls.append((cypher, parameters))


class FakeDriver:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def session(self, **_: Any) -> FakeSession:
        return FakeSession(self.calls)


@pytest.mark.asyncio
async def test_ingestion_is_idempotent_tenant_scoped_and_includes_corpus(
    incident_workspace: Path,
) -> None:
    graph = compile_workspace(incident_workspace)
    driver = FakeDriver()

    await ingest_graph(driver, graph)  # type: ignore[arg-type]

    cypher = "\n".join(call[0] for call in driver.calls)
    assert "IS UNIQUE" in cypher
    assert "MERGE (n:" in cypher
    assert "tenant_id: row.tenant_id" in cypher
    assert "MERGE (a)-[r:" in cypher
    assert "{id: row.id}" in cypher
    assert "MERGE (chunk:Chunk" in cypher
