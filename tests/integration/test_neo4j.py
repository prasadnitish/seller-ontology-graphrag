from __future__ import annotations

import os
from pathlib import Path

import pytest
from neo4j import AsyncGraphDatabase

from graphkit.compiler import compile_workspace
from graphkit.neo4j_store import ingest_graph

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("NEO4J_TEST_URI"),
        reason="NEO4J_TEST_URI is not configured",
    ),
]


@pytest.mark.asyncio
async def test_real_neo4j_load_is_idempotent_and_tenant_isolated(
    incident_workspace: Path,
) -> None:
    graph = compile_workspace(incident_workspace)
    uri = os.environ["NEO4J_TEST_URI"]
    username = os.getenv("NEO4J_TEST_USERNAME", "neo4j")
    password = os.environ["NEO4J_TEST_PASSWORD"]
    driver = AsyncGraphDatabase.driver(uri, auth=(username, password))
    try:
        await driver.verify_connectivity()
        await ingest_graph(driver, graph)
        await ingest_graph(driver, graph)

        async with driver.session() as session:
            node_result = await session.run(
                "MATCH (n) WHERE n.tenant_id = $tenant_id AND NOT n:Chunk "
                "RETURN count(n) AS count",
                tenant_id=graph.nodes[0].tenant_id,
            )
            chunk_result = await session.run(
                "MATCH (n:Chunk {tenant_id: $tenant_id}) RETURN count(n) AS count",
                tenant_id=graph.nodes[0].tenant_id,
            )
            other_result = await session.run(
                "MATCH (n {tenant_id: $tenant_id}) RETURN count(n) AS count",
                tenant_id="another-tenant",
            )
            assert (await node_result.single())["count"] == graph.counts["nodes"]
            assert (await chunk_result.single())["count"] == graph.counts["chunks"]
            assert (await other_result.single())["count"] == 0
    finally:
        async with driver.session() as session:
            await session.run(
                "MATCH (n {tenant_id: $tenant_id}) DETACH DELETE n",
                tenant_id=graph.nodes[0].tenant_id,
            )
        await driver.close()
