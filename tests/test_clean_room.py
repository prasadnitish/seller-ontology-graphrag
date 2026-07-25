from __future__ import annotations

import os
import subprocess
from pathlib import Path


def test_documented_incident_commands_work_in_a_clean_copy(
    incident_workspace: Path,
) -> None:
    environment = os.environ.copy()
    environment.pop("OPENAI_API_KEY", None)
    commands = [
        ["graphkit", "validate", "--workspace", str(incident_workspace)],
        ["graphkit", "build", "--workspace", str(incident_workspace)],
        [
            "graphkit",
            "query",
            "Which team owns Authentication Service?",
            "--workspace",
            str(incident_workspace),
        ],
    ]
    outputs = [
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        ).stdout
        for command in commands
    ]

    assert '"valid": true' in outputs[0]
    assert '"nodes": 17' in outputs[1]
    assert '"recipe_id": "service_owner"' in outputs[2]
