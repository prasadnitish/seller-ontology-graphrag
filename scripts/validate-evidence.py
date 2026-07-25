from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
manifest = json.loads((ROOT / "evidence" / "manifest.json").read_text())

for scenario, expected in manifest["scenarios"].items():
    workspace = ROOT / "examples" / scenario
    evaluation = json.loads((workspace / "generated" / "evaluation.json").read_text())
    graph = json.loads((workspace / "generated" / "graph-ir.json").read_text())

    assert graph["counts"]["nodes"] == expected["nodes"]
    assert graph["counts"]["relationships"] == expected["relationships"]
    assert graph["counts"]["chunks"] == expected["chunks"]
    assert evaluation["cases"] == expected["routing_cases"]
    assert evaluation["passed"] == expected["routing_passed"]
    assert evaluation["pass_rate_pct"] == expected["routing_pass_rate_pct"]
    assert evaluation["publishable_graph_vs_vector_claim"] is False
    assert evaluation["validation"]["mapped_fields"] == expected["mapped_fields"]
    assert evaluation["validation"]["ignored_fields"] == expected["ignored_fields"]
    assert evaluation["validation"]["unmapped_fields"] == expected["unmapped_fields"]

documents = [
    (ROOT / "README.md").read_text(),
    (ROOT / "docs" / "case-study.md").read_text(),
]
for expected_text in ("40/40", "37/40"):
    assert all(expected_text in document for document in documents), expected_text

print("Evidence manifest matches generated artifacts and documentation.")
