from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from graphkit.models import (
    CorpusChunk,
    GraphIR,
    GraphNode,
    GraphRelationship,
    GraphSpec,
    Provenance,
    SourceFormat,
    TextExtraction,
    ValidationIssue,
    ValidationReport,
)
from graphkit.workspace import (
    approval_is_current,
    load_profile,
    load_spec,
    profile_hash,
    spec_hash,
)


def validate_workspace(workspace: Path) -> ValidationReport:
    spec = load_spec(workspace)
    profile = load_profile(workspace)
    issues: list[ValidationIssue] = []
    source_specs = {source.id: source for source in spec.sources}
    mapped: dict[str, set[str]] = {source.id: set() for source in spec.sources}

    profile_by_path = {source.relative_path: source for source in profile.sources}
    for source in spec.sources:
        if source.path not in profile_by_path:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="SOURCE_NOT_PROFILED",
                    message=f"Source {source.path} is not present in source-profile.json",
                    location=f"sources.{source.id}",
                )
            )

    for mapping in spec.node_mappings:
        mapped[mapping.source].add(mapping.key_field)
        mapped[mapping.source].update(mapping.properties.values())
    for mapping in spec.relationship_mappings:
        mapped[mapping.source].update({mapping.from_field, mapping.to_field})
        mapped[mapping.source].update(mapping.properties.values())

    ignored_count = 0
    unmapped_count = 0
    for source_id, source in source_specs.items():
        profile_source = profile_by_path.get(source.path)
        if not profile_source or source.format not in {SourceFormat.CSV, SourceFormat.JSON}:
            continue
        fields = {field.name for field in profile_source.fields}
        ignored = set(source.ignored_fields)
        unknown_ignored = ignored - fields
        unknown_mapped = mapped[source_id] - fields
        for field in sorted(unknown_ignored):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="UNKNOWN_IGNORED_FIELD",
                    message=f"Ignored field {field} does not exist in {source.path}",
                    location=f"sources.{source_id}.ignored_fields",
                )
            )
        for field in sorted(unknown_mapped):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="UNKNOWN_MAPPED_FIELD",
                    message=f"Mapped field {field} does not exist in {source.path}",
                    location=f"mappings.{source_id}",
                )
            )
        unmapped = fields - mapped[source_id] - ignored
        ignored_count += len(ignored & fields)
        unmapped_count += len(unmapped)
        for field in sorted(unmapped):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="UNMAPPED_FIELD",
                    message=f"Field {field} must be mapped or explicitly ignored",
                    location=f"sources.{source_id}.{field}",
                )
            )

    try:
        compile_workspace(workspace, require_approval=False)
    except (ValueError, KeyError, TypeError) as error:
        issues.append(
            ValidationIssue(
                severity="error",
                code="COMPILE_FAILED",
                message=str(error),
                location="compiler",
            )
        )

    return ValidationReport(
        valid=not any(issue.severity == "error" for issue in issues),
        issues=issues,
        mapped_fields=sum(len(fields) for fields in mapped.values()),
        ignored_fields=ignored_count,
        unmapped_fields=unmapped_count,
    )


def compile_workspace(workspace: Path, *, require_approval: bool = True) -> GraphIR:
    workspace = workspace.resolve()
    spec = load_spec(workspace)
    profile = load_profile(workspace)
    if require_approval and not approval_is_current(workspace):
        raise ValueError("GraphSpec or source data is not approved, or approval is stale")
    records = {
        source.id: read_source_records(workspace, source.path, source.format, source.record_path)
        for source in spec.sources
        if source.format in {SourceFormat.CSV, SourceFormat.JSON}
    }
    node_types = {node.name: node for node in spec.node_types}
    relationship_types = {item.name: item for item in spec.relationship_types}
    nodes: list[GraphNode] = []
    node_index: dict[tuple[str, str], str] = {}

    for mapping in spec.node_mappings:
        node_type = node_types[mapping.node_type]
        for index, row in enumerate(records[mapping.source], start=1):
            raw_key = get_value(row, mapping.key_field)
            if raw_key in (None, ""):
                raise ValueError(f"{mapping.id} has an empty key at row {index}")
            canonical_id = f"{node_type.name}:{raw_key}"
            lookup_key = (node_type.name, str(raw_key))
            if lookup_key in node_index:
                raise ValueError(f"Duplicate node key {node_type.name}:{raw_key}")
            properties = {
                target: coerce(get_value(row, source), node_type.properties[target].type)
                for target, source in mapping.properties.items()
            }
            properties[node_type.key] = str(raw_key)
            node_index[lookup_key] = canonical_id
            nodes.append(
                GraphNode(
                    id=canonical_id,
                    type=node_type.name,
                    tenant_id=spec.metadata.tenant_id,
                    properties=properties,
                    provenance=Provenance(
                        source_id=mapping.source,
                        source_path=source_path(spec, mapping.source),
                        locator=f"row:{index}",
                    ),
                )
            )

    relationships: list[GraphRelationship] = []
    for mapping in spec.relationship_mappings:
        rel_type = relationship_types[mapping.relationship_type]
        for index, row in enumerate(records[mapping.source], start=1):
            from_value = get_value(row, mapping.from_field)
            to_value = get_value(row, mapping.to_field)
            from_id = node_index.get((rel_type.from_type, str(from_value)))
            to_id = node_index.get((rel_type.to_type, str(to_value)))
            if not from_id or not to_id:
                raise ValueError(
                    f"{mapping.id} row {index} references missing nodes: "
                    f"{rel_type.from_type}:{from_value} -> {rel_type.to_type}:{to_value}"
                )
            properties = {
                target: get_value(row, source) for target, source in mapping.properties.items()
            }
            relationships.append(
                GraphRelationship(
                    id=f"{rel_type.name}:{from_id}:{to_id}:{index}",
                    type=rel_type.name,
                    tenant_id=spec.metadata.tenant_id,
                    from_id=from_id,
                    to_id=to_id,
                    properties=properties,
                    provenance=Provenance(
                        source_id=mapping.source,
                        source_path=source_path(spec, mapping.source),
                        locator=f"row:{index}",
                    ),
                )
            )

    relationships.extend(
        compile_text_extractions(
            workspace,
            spec,
            node_index,
            relationship_types,
        )
    )
    corpus = build_corpus(workspace, spec, nodes, relationships)
    return GraphIR(
        graph_name=spec.metadata.name,
        graph_version=spec.metadata.version,
        ontology_hash=spec_hash(spec),
        data_hash=profile_hash(profile),
        nodes=nodes,
        relationships=relationships,
        corpus=corpus,
        counts={
            "nodes": len(nodes),
            "relationships": len(relationships),
            "chunks": len(corpus),
        },
    )


def source_path(spec: GraphSpec, source_id: str) -> str:
    return next(source.path for source in spec.sources if source.id == source_id)


def safe_source_path(workspace: Path, relative: str) -> Path:
    root = (workspace / "sources").resolve()
    candidate = (root / relative).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("Source path escapes the workspace")
    if not candidate.is_file():
        raise ValueError(f"Source file does not exist: {relative}")
    return candidate


def read_source_records(
    workspace: Path,
    relative: str,
    source_format: SourceFormat,
    record_path: str | None,
) -> list[dict[str, Any]]:
    path = safe_source_path(workspace, relative)
    if source_format == SourceFormat.CSV:
        return list(csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines()))
    if source_format == SourceFormat.JSON:
        data: Any = json.loads(path.read_text())
        if record_path:
            data = get_value(data, record_path)
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
            raise ValueError(f"JSON source {relative} must resolve to a list of objects")
        return data
    raise ValueError(f"{relative} is not a structured source")


def compile_text_extractions(
    workspace: Path,
    spec: GraphSpec,
    node_index: dict[tuple[str, str], str],
    relationship_types: dict[str, Any],
) -> list[GraphRelationship]:
    path = workspace / "extractions.jsonl"
    if not path.exists():
        return []
    source_specs = {source.id: source for source in spec.sources}
    output: list[GraphRelationship] = []
    seen_ids: set[str] = set()
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        extraction = TextExtraction.model_validate_json(line)
        if extraction.id in seen_ids:
            raise ValueError(f"Duplicate text extraction id {extraction.id}")
        seen_ids.add(extraction.id)
        source = source_specs.get(extraction.source)
        if not source or source.format not in {SourceFormat.MARKDOWN, SourceFormat.TEXT}:
            raise ValueError(
                f"Text extraction {extraction.id} references a non-text source"
            )
        source_text = safe_source_path(workspace, source.path).read_text()
        if extraction.exact_quote not in source_text:
            raise ValueError(
                f"Text extraction {extraction.id} quote is not present in {source.path}"
            )
        relationship = relationship_types.get(extraction.relationship_type)
        if (
            not relationship
            or relationship.from_type != extraction.subject_type
            or relationship.to_type != extraction.object_type
        ):
            raise ValueError(
                f"Text extraction {extraction.id} does not conform to the ontology"
            )
        from_id = node_index.get(
            (extraction.subject_type, extraction.subject_key)
        )
        to_id = node_index.get((extraction.object_type, extraction.object_key))
        if not from_id or not to_id:
            raise ValueError(
                f"Text extraction {extraction.id} references a missing node"
            )
        output.append(
            GraphRelationship(
                id=f"text:{extraction.id}",
                type=extraction.relationship_type,
                tenant_id=spec.metadata.tenant_id,
                from_id=from_id,
                to_id=to_id,
                provenance=Provenance(
                    source_id=source.id,
                    source_path=source.path,
                    locator=extraction.locator,
                    quote=extraction.exact_quote,
                    confidence=extraction.confidence,
                ),
            )
        )
    return output


def build_corpus(
    workspace: Path,
    spec: GraphSpec,
    nodes: list[GraphNode],
    relationships: list[GraphRelationship],
) -> list[CorpusChunk]:
    chunks: list[CorpusChunk] = []
    for node in nodes:
        details = ", ".join(f"{key}={value}" for key, value in node.properties.items())
        chunks.append(
            CorpusChunk(
                id=f"chunk:{node.id}",
                text=f"{node.type} {details}.",
                tenant_id=node.tenant_id,
                provenance=node.provenance,
            )
        )
    for rel in relationships:
        chunks.append(
            CorpusChunk(
                id=f"chunk:{rel.id}",
                text=f"{rel.from_id} {rel.type} {rel.to_id}.",
                tenant_id=rel.tenant_id,
                provenance=rel.provenance,
            )
        )
    for source in spec.sources:
        if source.format not in {SourceFormat.MARKDOWN, SourceFormat.TEXT}:
            continue
        text = safe_source_path(workspace, source.path).read_text()
        for index, (paragraph, start, end) in enumerate(
            chunk_text_spans(
                text,
                spec.vector.chunk_size,
                spec.vector.chunk_overlap,
            ),
            start=1,
        ):
            chunks.append(
                CorpusChunk(
                    id=f"chunk:{source.id}:{index}",
                    text=paragraph,
                    tenant_id=spec.metadata.tenant_id,
                    provenance=Provenance(
                        source_id=source.id,
                        source_path=source.path,
                        locator=f"chars:{start}-{end}",
                        quote=paragraph,
                    ),
                )
            )
    return chunks


def chunk_text(text: str, target_size: int, overlap: int = 0) -> list[str]:
    return [
        chunk
        for chunk, _, _ in chunk_text_spans(text, target_size, overlap)
    ]


def chunk_text_spans(
    text: str,
    target_size: int,
    overlap: int,
) -> list[tuple[str, int, int]]:
    if not text.strip():
        return []
    output: list[tuple[str, int, int]] = []
    start = 0
    length = len(text)
    while start < length:
        while start < length and text[start].isspace():
            start += 1
        if start >= length:
            break
        end = min(length, start + target_size)
        reached_end = end >= length
        if end < length:
            search_start = min(end, start + max(1, target_size // 2))
            paragraph_break = text.rfind("\n\n", search_start, end)
            word_break = text.rfind(" ", search_start, end)
            chosen_break = max(paragraph_break, word_break)
            if chosen_break > start:
                end = chosen_break
        while end > start and text[end - 1].isspace():
            end -= 1
        output.append((text[start:end], start, end))
        if reached_end:
            break
        start = max(start + 1, end - overlap)
    return output


def get_value(value: Any, dotted_path: str) -> Any:
    current = value
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(f"Missing field {dotted_path}")
        current = current[part]
    return current


def coerce(value: Any, kind: str) -> Any:
    if value in (None, ""):
        return None
    if kind == "integer":
        return int(value)
    if kind == "number":
        return float(value)
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized not in {"true", "false"}:
            raise ValueError(f"Cannot coerce {value!r} to boolean")
        return normalized == "true"
    return str(value)
