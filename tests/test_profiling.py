from __future__ import annotations

from pathlib import Path

import pytest

from graphkit.workspace import initialize_workspace, profile_file


def test_nested_json_record_array_is_profiled(tmp_path: Path) -> None:
    source = tmp_path / "nested.json"
    source.write_text('{"payload":{"records":[{"id":"1","name":"Ada"}]}}')

    profile = profile_file(source, tmp_path)

    assert profile.record_count == 1
    assert {field.name for field in profile.fields} == {"id", "name"}
    assert "payload.records" in profile.warnings[0]


def test_workspace_cannot_be_nested_inside_source_directory(tmp_path: Path) -> None:
    (tmp_path / "data.csv").write_text("id\n1\n")

    with pytest.raises(ValueError, match="outside"):
        initialize_workspace(tmp_path, tmp_path / "workspace")
