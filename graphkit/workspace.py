from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from graphkit.models import (
    ApprovalRecord,
    GraphSpec,
    ProfileField,
    SourceFormat,
    SourceProfile,
    WorkspaceProfile,
)

SUPPORTED_SUFFIXES = {
    ".csv": SourceFormat.CSV,
    ".json": SourceFormat.JSON,
    ".md": SourceFormat.MARKDOWN,
    ".markdown": SourceFormat.MARKDOWN,
    ".txt": SourceFormat.TEXT,
}
SENSITIVE_FIELD = re.compile(
    r"(email|phone|ssn|social.?security|password|secret|token|api.?key|credit.?card)",
    re.IGNORECASE,
)
MAX_SOURCE_BYTES = 10 * 1024 * 1024


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_spec_bytes(spec: GraphSpec) -> bytes:
    # Canvas positions are presentation state, not ontology semantics. Keeping
    # them out of the approval digest lets users rearrange the graph without
    # invalidating an otherwise unchanged review.
    payload = spec.model_dump(mode="json", exclude_none=True, exclude={"ui"})
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def spec_hash(spec: GraphSpec) -> str:
    return sha256_bytes(canonical_spec_bytes(spec))


def profile_hash(profile: WorkspaceProfile) -> str:
    manifest = [(source.relative_path, source.sha256) for source in profile.sources]
    return sha256_bytes(json.dumps(manifest, separators=(",", ":")).encode())


def load_spec(workspace: Path) -> GraphSpec:
    path = workspace / "graphspec.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}")
    return GraphSpec.model_validate(yaml.safe_load(path.read_text()))


def save_spec(workspace: Path, spec: GraphSpec) -> None:
    path = workspace / "graphspec.yaml"
    previous_hash = spec_hash(load_spec(workspace)) if path.exists() else None
    history = workspace / ".graphkit" / "history"
    history.mkdir(parents=True, exist_ok=True)
    if path.exists():
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        shutil.copy2(path, history / f"graphspec-{stamp}.yaml")
    payload = yaml.safe_dump(
        spec.model_dump(mode="json", exclude_none=True),
        sort_keys=False,
        allow_unicode=True,
        width=100,
    )
    atomic_write(path, payload)
    if previous_hash != spec_hash(spec):
        approval = workspace / ".graphkit" / "approval.json"
        approval.unlink(missing_ok=True)


def load_profile(workspace: Path) -> WorkspaceProfile:
    path = workspace / "source-profile.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}; run graphkit init first")
    return WorkspaceProfile.model_validate_json(path.read_text())


def load_approval(workspace: Path) -> ApprovalRecord | None:
    path = workspace / ".graphkit" / "approval.json"
    if not path.exists():
        return None
    return ApprovalRecord.model_validate_json(path.read_text())


def approve_workspace(workspace: Path) -> ApprovalRecord:
    spec = load_spec(workspace)
    profile = load_profile(workspace)
    approval = ApprovalRecord(
        spec_hash=spec_hash(spec),
        source_manifest_hash=profile_hash(profile),
        approved_at=utc_now(),
    )
    path = workspace / ".graphkit" / "approval.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, approval.model_dump_json(indent=2) + "\n")
    return approval


def approval_is_current(workspace: Path) -> bool:
    approval = load_approval(workspace)
    if not approval:
        return False
    return approval.spec_hash == spec_hash(load_spec(workspace)) and (
        approval.source_manifest_hash == profile_hash(load_profile(workspace))
    )


def initialize_workspace(data_dir: Path, workspace: Path) -> WorkspaceProfile:
    data_dir = data_dir.resolve()
    workspace = workspace.resolve()
    if not data_dir.is_dir():
        raise ValueError(f"Data directory does not exist: {data_dir}")
    if workspace == data_dir or data_dir in workspace.parents:
        raise ValueError("Workspace must be outside the source data directory")
    workspace.mkdir(parents=True, exist_ok=True)
    target = workspace / "sources"
    target.mkdir(exist_ok=True)

    files = [
        path
        for path in sorted(data_dir.rglob("*"))
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    ]
    if not files:
        raise ValueError("No supported CSV, JSON, Markdown, or text files found")
    for source in files:
        relative = source.relative_to(data_dir)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    profile = profile_sources(target)
    atomic_write(
        workspace / "source-profile.json",
        profile.model_dump_json(indent=2) + "\n",
    )
    atomic_write(workspace / "AGENT_BRIEF.md", build_agent_brief(profile))
    (workspace / ".graphkit").mkdir(exist_ok=True)
    return profile


def profile_sources(source_root: Path) -> WorkspaceProfile:
    profiles: list[SourceProfile] = []
    for path in sorted(source_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        profiles.append(profile_file(path, source_root))
    return WorkspaceProfile(generated_at=utc_now(), sources=profiles)


def profile_file(path: Path, source_root: Path) -> SourceProfile:
    raw = path.read_bytes()
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError(f"{path.name} exceeds the v1 10 MB per-file limit")
    source_format = SUPPORTED_SUFFIXES[path.suffix.lower()]
    relative = path.relative_to(source_root).as_posix()
    warnings: list[str] = []
    fields: list[ProfileField] = []
    headings: list[str] = []
    record_count: int | None = None

    if source_format == SourceFormat.CSV:
        rows = list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
        record_count = len(rows)
        fields = profile_records(rows)
    elif source_format == SourceFormat.JSON:
        data = json.loads(raw)
        if isinstance(data, list):
            records = data
        else:
            candidates = find_record_arrays(data)
            if len(candidates) == 1:
                record_path, records = candidates[0]
                warnings.append(
                    f"Detected nested record array at {record_path}; "
                    "declare this GraphSpec record_path"
                )
            else:
                records = [data]
                if len(candidates) > 1:
                    warnings.append(
                        "Multiple nested record arrays found; select record_path explicitly"
                    )
        record_count = len(records)
        fields = profile_records([item for item in records if isinstance(item, dict)])
        if not isinstance(data, list) and not candidates:
            warnings.append("Top-level JSON object may require record_path in GraphSpec")
    else:
        text = raw.decode("utf-8")
        headings = [
            match.group(1).strip()
            for match in re.finditer(r"^#{1,6}\s+(.+)$", text, re.MULTILINE)
        ][:20]
        record_count = len([part for part in re.split(r"\n\s*\n", text) if part.strip()])

    if any(field.sensitive for field in fields):
        warnings.append("Potential sensitive fields were detected; sample values are redacted")
    return SourceProfile(
        id=slugify(path.stem),
        relative_path=relative,
        format=source_format,
        sha256=sha256_bytes(raw),
        size_bytes=len(raw),
        record_count=record_count,
        fields=fields,
        headings=headings,
        warnings=warnings,
    )


def profile_records(records: list[dict[str, Any]]) -> list[ProfileField]:
    names = sorted({name for record in records for name in record})
    output: list[ProfileField] = []
    for name in names:
        values = [record.get(name) for record in records]
        non_null = [value for value in values if value not in (None, "")]
        sensitive = bool(SENSITIVE_FIELD.search(name))
        samples = [] if sensitive else unique_samples(non_null)
        output.append(
            ProfileField(
                name=name,
                inferred_type=infer_type(non_null),
                null_count=len(values) - len(non_null),
                samples=samples,
                sensitive=sensitive,
            )
        )
    return output


def find_record_arrays(
    value: Any,
    prefix: str = "",
) -> list[tuple[str, list[Any]]]:
    output: list[tuple[str, list[Any]]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}".strip(".")
            if isinstance(child, list) and all(
                isinstance(item, dict) for item in child
            ):
                output.append((path, child))
            elif isinstance(child, dict):
                output.extend(find_record_arrays(child, path))
    return output


def unique_samples(values: list[Any], limit: int = 3) -> list[Any]:
    samples: list[Any] = []
    for value in values:
        normalized = value if isinstance(value, (str, int, float, bool)) else str(value)
        if normalized not in samples:
            samples.append(normalized)
        if len(samples) >= limit:
            break
    return samples


def infer_type(values: list[Any]) -> str:
    if not values:
        return "unknown"
    strings = [str(value).strip() for value in values]
    if all(value.lower() in {"true", "false"} for value in strings):
        return "boolean"
    if all(re.fullmatch(r"-?\d+", value) for value in strings):
        return "integer"
    if all(re.fullmatch(r"-?(?:\d+\.\d+|\d+)", value) for value in strings):
        return "number"
    return "string"


def slugify(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    if not result:
        return "source"
    if result[0].isdigit():
        result = f"source_{result}"
    return result


def build_agent_brief(profile: WorkspaceProfile) -> str:
    source_lines = "\n".join(
        f"- `{source.relative_path}`: {source.format}, "
        f"{source.record_count or 0} records, fields "
        f"{', '.join(field.name for field in source.fields) or 'n/a'}"
        for source in profile.sources
    )
    return f"""# GraphRAG ontology proposal brief

Create `graphspec.yaml` using the schema generated by `graphkit schema`.

## Outcome

Propose the smallest ontology that can answer relationship-dependent questions from these
sources. Prefer explicit entities and relationships over copying every column into the graph.

## Sources

{source_lines}

## Rules

- Do not invent entities, values, relationships, or source fields.
- Every structured field must be mapped or listed in `ignored_fields` with a reason.
- Use stable source identifiers as node keys.
- Add only bounded, parameterized, read-only query recipes.
- Every graph or hybrid recipe must use `$tenant_id` and include a numeric `LIMIT`.
- Keep narrative documents in the vector corpus; extract graph facts only with exact quotes.
- Stop and record an ambiguity instead of guessing.

## Completion

Run `graphkit validate --workspace .`, resolve all errors, then ask the user to open
`graphkit review --workspace .` and approve the proposal.
"""


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
