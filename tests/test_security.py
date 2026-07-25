from __future__ import annotations

import pytest
from pydantic import ValidationError

from graphkit.models import QueryRecipe, validate_read_query


@pytest.mark.parametrize(
    ("cypher", "message"),
    [
        ("MATCH (n) DELETE n RETURN n LIMIT 1", "prohibited"),
        (
            "MATCH (n {tenant_id: $tenant_id})-[*]->(m) RETURN m LIMIT 10",
            "unbounded",
        ),
        (
            "MATCH (n {tenant_id: $tenant_id})-[:DEPENDS_ON*1..]->(m) "
            "RETURN m LIMIT 10",
            "unbounded",
        ),
        ("MATCH (n) RETURN n LIMIT 10", "tenant"),
        ("MATCH (n {tenant_id: $tenant_id}) RETURN n", "limit"),
        (
            "MATCH (n {tenant_id: $tenant_id, id: $unknown}) RETURN n LIMIT 1",
            "undeclared",
        ),
    ],
)
def test_unsafe_cypher_is_rejected(cypher: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate_read_query(cypher, {"tenant_id"})


def test_bounded_read_recipe_is_accepted() -> None:
    recipe = QueryRecipe.model_validate(
        {
            "id": "safe_lookup",
            "description": "Safe bounded lookup",
            "route": "graph",
            "examples": ["Find a thing"],
            "parameters": {"thing_id": {"type": "string"}},
            "cypher": (
                "MATCH (n {tenant_id: $tenant_id, id: $thing_id})"
                "-[:DEPENDS_ON*0..3]->(m {tenant_id: $tenant_id}) "
                "RETURN n, m LIMIT 20"
            ),
        }
    )
    assert recipe.id == "safe_lookup"


def test_source_path_traversal_is_rejected() -> None:
    with pytest.raises(ValidationError, match="traverse"):
        from graphkit.models import SourceSpec

        SourceSpec(id="bad", path="../secret.csv", format="csv")


def test_ignored_field_requires_a_reason() -> None:
    with pytest.raises(ValidationError, match="non-empty reason"):
        from graphkit.models import SourceSpec

        SourceSpec(
            id="source",
            path="data.csv",
            format="csv",
            ignored_fields={"unused": "  "},
        )
