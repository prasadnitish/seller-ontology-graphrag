from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from neo4j import AsyncDriver

from graphkit.models import GraphIR, QueryRecipe


async def ensure_constraints(driver: AsyncDriver, graph: GraphIR) -> None:
    labels = sorted({node.type for node in graph.nodes} | {"Chunk"})
    async with driver.session() as session:
        for label in labels:
            await session.run(
                f"CREATE CONSTRAINT graphkit_{label.lower()}_tenant_id IF NOT EXISTS "
                f"FOR (n:{label}) REQUIRE (n.tenant_id, n.id) IS UNIQUE"
            )


async def ingest_graph(driver: AsyncDriver, graph: GraphIR, *, batch_size: int = 500) -> None:
    grouped_nodes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    grouped_relationships: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in graph.nodes:
        grouped_nodes[node.type].append(
            {
                "id": node.id,
                "tenant_id": node.tenant_id,
                **node.properties,
                "provenance": node.provenance.model_dump_json(),
            }
        )
    for relationship in graph.relationships:
        grouped_relationships[relationship.type].append(
            {
                "from_id": relationship.from_id,
                "to_id": relationship.to_id,
                "id": relationship.id,
                "tenant_id": relationship.tenant_id,
                **relationship.properties,
                "provenance": relationship.provenance.model_dump_json(),
            }
        )
    chunks = [
        {
            "id": chunk.id,
            "tenant_id": chunk.tenant_id,
            "text": chunk.text,
            "provenance": chunk.provenance.model_dump_json(),
        }
        for chunk in graph.corpus
    ]
    await ensure_constraints(driver, graph)
    async with driver.session() as session:
        for label, rows in grouped_nodes.items():
            for batch in batched(rows, batch_size):
                await session.run(
                    f"UNWIND $rows AS row "
                    f"MERGE (n:{label} {{tenant_id: row.tenant_id, id: row.id}}) "
                    "SET n += row",
                    rows=batch,
                )
        for relationship_type, rows in grouped_relationships.items():
            for batch in batched(rows, batch_size):
                await session.run(
                    "UNWIND $rows AS row "
                    "MATCH (a {tenant_id: row.tenant_id, id: row.from_id}), "
                    "(b {tenant_id: row.tenant_id, id: row.to_id}) "
                    f"MERGE (a)-[r:{relationship_type} {{id: row.id}}]->(b) "
                    "SET r += row",
                    rows=batch,
                )
        for batch in batched(chunks, batch_size):
            await session.run(
                "UNWIND $rows AS row "
                "MERGE (chunk:Chunk {tenant_id: row.tenant_id, id: row.id}) "
                "SET chunk += row",
                rows=batch,
            )


async def execute_recipe(
    driver: AsyncDriver,
    recipe: QueryRecipe,
    parameters: dict[str, Any],
    tenant_id: str,
) -> list[dict[str, Any]]:
    if not recipe.cypher:
        return []
    async with driver.session(default_access_mode="READ") as session:
        result = await session.run(recipe.cypher, tenant_id=tenant_id, **parameters)
        rows = [record.data() async for record in result]
    return json.loads(json.dumps(rows, default=str))


def batched(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]
