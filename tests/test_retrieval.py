from __future__ import annotations

from pathlib import Path

import pytest

from graphkit.compiler import compile_workspace
from graphkit.retrieval import RulePlanner
from graphkit.workspace import load_spec


@pytest.mark.asyncio
async def test_rule_planner_selects_approved_recipe_and_existing_entity(
    incident_workspace: Path,
) -> None:
    spec = load_spec(incident_workspace)
    graph = compile_workspace(incident_workspace)

    selection = await RulePlanner().select(
        "Which team owns Authentication Service?",
        spec,
        graph,
    )

    assert selection.supported
    assert selection.recipe_id == "service_owner"
    assert selection.parameters == {"service_name": "Authentication Service"}


@pytest.mark.asyncio
async def test_rule_planner_does_not_invent_missing_parameter(
    incident_workspace: Path,
) -> None:
    spec = load_spec(incident_workspace)
    graph = compile_workspace(incident_workspace)

    selection = await RulePlanner().select(
        "Which team owns the made-up moon service?",
        spec,
        graph,
    )

    assert not selection.supported
    assert selection.parameters == {}
