from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
WRITE_PATTERN = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|DROP|REMOVE|LOAD\s+CSV|CALL|FOREACH)\b",
    re.IGNORECASE,
)
PARAM_PATTERN = re.compile(r"\$([A-Za-z][A-Za-z0-9_]*)")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceFormat(StrEnum):
    CSV = "csv"
    JSON = "json"
    MARKDOWN = "markdown"
    TEXT = "text"


class Route(StrEnum):
    GRAPH = "graph"
    VECTOR = "vector"
    HYBRID = "hybrid"


class SourceSpec(StrictModel):
    id: str
    path: str
    format: SourceFormat
    record_path: str | None = None
    ignored_fields: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_source(self) -> SourceSpec:
        if not NAME_PATTERN.fullmatch(self.id):
            raise ValueError(f"Invalid source id: {self.id}")
        if self.path.startswith("/") or ".." in self.path.split("/"):
            raise ValueError("Source paths must be workspace-relative and may not traverse upward")
        if self.format not in {SourceFormat.JSON} and self.record_path:
            raise ValueError("record_path is only supported for JSON sources")
        if any(not reason.strip() for reason in self.ignored_fields.values()):
            raise ValueError("Every ignored field requires a non-empty reason")
        return self


class PropertySpec(StrictModel):
    type: Literal["string", "integer", "number", "boolean", "date", "datetime"] = "string"
    required: bool = False
    description: str = ""


class NodeType(StrictModel):
    name: str
    key: str = "id"
    description: str = ""
    properties: dict[str, PropertySpec] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_names(self) -> NodeType:
        if not NAME_PATTERN.fullmatch(self.name):
            raise ValueError(f"Invalid node type: {self.name}")
        if not NAME_PATTERN.fullmatch(self.key):
            raise ValueError(f"Invalid key property: {self.key}")
        for name in self.properties:
            if not NAME_PATTERN.fullmatch(name):
                raise ValueError(f"Invalid property name: {name}")
        return self


class RelationshipType(StrictModel):
    name: str
    from_type: str
    to_type: str
    description: str = ""
    properties: dict[str, PropertySpec] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_name(self) -> RelationshipType:
        if not NAME_PATTERN.fullmatch(self.name):
            raise ValueError(f"Invalid relationship type: {self.name}")
        return self


class NodeMapping(StrictModel):
    id: str
    source: str
    node_type: str
    key_field: str
    properties: dict[str, str]


class RelationshipMapping(StrictModel):
    id: str
    source: str
    relationship_type: str
    from_field: str
    to_field: str
    properties: dict[str, str] = Field(default_factory=dict)


class CandidateLookup(StrictModel):
    node_type: str
    property: str


class ParameterSpec(StrictModel):
    type: Literal["string", "integer", "number", "boolean"] = "string"
    description: str = ""
    required: bool = True
    candidates: CandidateLookup | None = None


class QueryRecipe(StrictModel):
    id: str
    description: str
    route: Route
    examples: list[str] = Field(min_length=1)
    parameters: dict[str, ParameterSpec] = Field(default_factory=dict)
    cypher: str | None = None
    result_description: str = ""

    @model_validator(mode="after")
    def validate_recipe(self) -> QueryRecipe:
        if not NAME_PATTERN.fullmatch(self.id):
            raise ValueError(f"Invalid recipe id: {self.id}")
        if self.route in {Route.GRAPH, Route.HYBRID}:
            if not self.cypher:
                raise ValueError(f"{self.route} recipe {self.id} requires Cypher")
            validate_read_query(self.cypher, set(self.parameters) | {"tenant_id"})
        elif self.cypher:
            raise ValueError("Vector-only recipes may not include Cypher")
        return self


class VectorConfig(StrictModel):
    enabled: bool = True
    chunk_size: int = Field(default=900, ge=200, le=4000)
    chunk_overlap: int = Field(default=100, ge=0, le=1000)
    top_k: int = Field(default=5, ge=1, le=20)


class UILayout(StrictModel):
    nodes: dict[str, dict[str, float]] = Field(default_factory=dict)


class GraphMetadata(StrictModel):
    name: str
    version: str
    tenant_id: str = "demo"
    description: str = ""


class GraphSpec(StrictModel):
    metadata: GraphMetadata
    sources: list[SourceSpec]
    node_types: list[NodeType]
    relationship_types: list[RelationshipType]
    node_mappings: list[NodeMapping]
    relationship_mappings: list[RelationshipMapping]
    query_recipes: list[QueryRecipe]
    vector: VectorConfig = Field(default_factory=VectorConfig)
    ui: UILayout = Field(default_factory=UILayout)

    @model_validator(mode="after")
    def validate_references(self) -> GraphSpec:
        source_ids = unique_names(self.sources, "source")
        node_names = unique_names(self.node_types, "node type", attr="name")
        relationship_names = unique_names(
            self.relationship_types, "relationship type", attr="name"
        )
        unique_names(self.node_mappings, "node mapping")
        unique_names(self.relationship_mappings, "relationship mapping")
        unique_names(self.query_recipes, "query recipe")

        for rel in self.relationship_types:
            if rel.from_type not in node_names or rel.to_type not in node_names:
                raise ValueError(f"Relationship {rel.name} references an unknown node type")
        for mapping in self.node_mappings:
            if mapping.source not in source_ids or mapping.node_type not in node_names:
                raise ValueError(f"Node mapping {mapping.id} has an unknown source or node type")
            node = next(item for item in self.node_types if item.name == mapping.node_type)
            unknown = set(mapping.properties) - set(node.properties)
            if unknown:
                raise ValueError(f"Node mapping {mapping.id} maps unknown properties: {unknown}")
            required = {
                name for name, prop in node.properties.items() if prop.required
            } - {node.key}
            missing_required = required - set(mapping.properties)
            if missing_required:
                raise ValueError(
                    f"Node mapping {mapping.id} omits required properties: "
                    f"{sorted(missing_required)}"
                )
        for mapping in self.relationship_mappings:
            if (
                mapping.source not in source_ids
                or mapping.relationship_type not in relationship_names
            ):
                raise ValueError(
                    f"Relationship mapping {mapping.id} has an unknown source or type"
                )
            relationship = next(
                item
                for item in self.relationship_types
                if item.name == mapping.relationship_type
            )
            unknown = set(mapping.properties) - set(relationship.properties)
            if unknown:
                raise ValueError(
                    f"Relationship mapping {mapping.id} maps unknown properties: {unknown}"
                )
            required = {
                name
                for name, prop in relationship.properties.items()
                if prop.required
            }
            missing_required = required - set(mapping.properties)
            if missing_required:
                raise ValueError(
                    f"Relationship mapping {mapping.id} omits required properties: "
                    f"{sorted(missing_required)}"
                )
        for recipe in self.query_recipes:
            for parameter in recipe.parameters.values():
                if parameter.candidates and parameter.candidates.node_type not in node_names:
                    raise ValueError(f"Recipe {recipe.id} references an unknown candidate node")
        return self


class ProfileField(StrictModel):
    name: str
    inferred_type: str
    null_count: int = 0
    samples: list[Any] = Field(default_factory=list)
    sensitive: bool = False


class SourceProfile(StrictModel):
    id: str
    relative_path: str
    format: SourceFormat
    sha256: str
    size_bytes: int
    record_count: int | None = None
    fields: list[ProfileField] = Field(default_factory=list)
    headings: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class WorkspaceProfile(StrictModel):
    generated_at: str
    sources: list[SourceProfile]


class Provenance(StrictModel):
    source_id: str
    source_path: str
    locator: str
    quote: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class GraphNode(StrictModel):
    id: str
    type: str
    tenant_id: str
    properties: dict[str, Any]
    provenance: Provenance


class GraphRelationship(StrictModel):
    id: str
    type: str
    tenant_id: str
    from_id: str
    to_id: str
    properties: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance


class CorpusChunk(StrictModel):
    id: str
    text: str
    tenant_id: str
    provenance: Provenance


class TextExtraction(StrictModel):
    id: str
    source: str
    subject_type: str
    subject_key: str
    relationship_type: str
    object_type: str
    object_key: str
    exact_quote: str = Field(min_length=1)
    locator: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_names(self) -> TextExtraction:
        for value in (
            self.id,
            self.source,
            self.subject_type,
            self.relationship_type,
            self.object_type,
        ):
            if not NAME_PATTERN.fullmatch(value):
                raise ValueError(f"Invalid extraction identifier: {value}")
        return self


class GraphIR(StrictModel):
    graph_name: str
    graph_version: str
    ontology_hash: str
    data_hash: str
    nodes: list[GraphNode]
    relationships: list[GraphRelationship]
    corpus: list[CorpusChunk]
    counts: dict[str, int]


class ValidationIssue(StrictModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    location: str = ""


class ValidationReport(StrictModel):
    valid: bool
    issues: list[ValidationIssue]
    mapped_fields: int
    ignored_fields: int
    unmapped_fields: int


class ApprovalRecord(StrictModel):
    spec_hash: str
    source_manifest_hash: str
    approved_at: str


class QuerySelection(StrictModel):
    supported: bool
    recipe_id: str | None = None
    route: Route | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0, ge=0, le=1)
    reason: str = ""


def unique_names(items: list[Any], label: str, attr: str = "id") -> set[str]:
    values = [getattr(item, attr) for item in items]
    duplicates = {value for value in values if values.count(value) > 1}
    if duplicates:
        raise ValueError(f"Duplicate {label}s: {sorted(duplicates)}")
    return set(values)


def validate_read_query(cypher: str, allowed_parameters: set[str]) -> None:
    normalized = cypher.strip()
    if ";" in normalized:
        raise ValueError("Cypher recipes may contain only one statement")
    if WRITE_PATTERN.search(normalized):
        raise ValueError("Cypher recipe contains a prohibited clause")
    for relationship_pattern in re.findall(r"\[([^\]]*)\]", normalized):
        if "*" in relationship_pattern and not re.search(
            r"\*\s*\d+\s*\.\.\s*\d+",
            relationship_pattern,
        ):
            raise ValueError("Cypher recipe contains an unbounded traversal")
    if "RETURN" not in normalized.upper():
        raise ValueError("Cypher recipe must return results")
    if "$tenant_id" not in normalized:
        raise ValueError("Cypher recipe must use the tenant parameter")
    if not re.search(r"\bLIMIT\s+\d+\b", normalized, re.IGNORECASE):
        raise ValueError("Cypher recipe must include a numeric result limit")
    unknown = set(PARAM_PATTERN.findall(normalized)) - allowed_parameters
    if unknown:
        raise ValueError(f"Cypher recipe uses undeclared parameters: {sorted(unknown)}")
