from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from graphkit.compiler import compile_workspace, validate_workspace
from graphkit.retrieval import Planner, RulePlanner
from graphkit.workspace import load_spec


async def evaluate_workspace(
    workspace: Path,
    *,
    planner: Planner | None = None,
    provider: str = "rule-planner",
    model: str = "deterministic-token-overlap",
) -> dict[str, Any]:
    cases_path = workspace / "evaluation.json"
    if not cases_path.exists():
        raise FileNotFoundError(f"Missing {cases_path}")
    cases = json.loads(cases_path.read_text())
    spec = load_spec(workspace)
    graph = compile_workspace(workspace)
    planner = planner or RulePlanner()
    rows: list[dict[str, Any]] = []
    for case in cases:
        selection = await planner.select(case["question"], spec, graph)
        expected_supported = case.get("expected_supported", True)
        supported_correct = selection.supported is expected_supported
        recipe_correct = selection.recipe_id == case.get("expected_recipe")
        route_correct = (
            str(selection.route) == case.get("expected_route")
            if expected_supported
            else selection.route is None
        )
        parameters_correct = (
            selection.parameters == case.get("expected_parameters", {})
            if expected_supported
            else selection.parameters == {}
        )
        rows.append(
            {
                "id": case["id"],
                "category": case.get("category", "routing"),
                "question": case["question"],
                "selection": selection.model_dump(mode="json"),
                "supported_correct": supported_correct,
                "recipe_correct": recipe_correct,
                "route_correct": route_correct,
                "parameters_correct": parameters_correct,
                "passed": (
                    supported_correct
                    and recipe_correct
                    and route_correct
                    and parameters_correct
                ),
            }
        )
    passed = sum(row["passed"] for row in rows)
    validation = validate_workspace(workspace)
    report = {
        "dataset": spec.metadata.name,
        "ontology_version": spec.metadata.version,
        "provider": provider,
        "model": model,
        "ontology_hash": graph.ontology_hash,
        "data_hash": graph.data_hash,
        "commit": os.getenv("GIT_COMMIT", "uncommitted"),
        "generated_at": datetime.now(UTC).isoformat(),
        "cases": len(rows),
        "passed": passed,
        "pass_rate_pct": round(passed / len(rows) * 100, 1) if rows else 0,
        "recipe_selection_certified": bool(
            rows and passed / len(rows) >= 0.9 and validation.valid
        ),
        "publishable_graph_vs_vector_claim": False,
        "limitations": [
            "This report validates approved-recipe routing and parameter extraction only.",
            (
                "Graph-versus-vector answer quality requires a configured Neo4j "
                "and embedding provider."
            ),
        ],
        "validation": validation.model_dump(mode="json"),
        "rows": rows,
    }
    reports = workspace / "generated"
    reports.mkdir(exist_ok=True)
    (reports / "evaluation.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
