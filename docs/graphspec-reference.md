# GraphSpec reference

`graphspec.yaml` is the canonical, versioned contract between profiling, coding agents, the
visual editor, the compiler, Neo4j loading, retrieval, and evaluation.

Generate its authoritative JSON Schema:

```bash
uv run graphkit schema --output docs/graphspec.schema.json
```

## Top-level fields

| Field | Purpose |
|---|---|
| `metadata` | Workspace name, semantic version, tenant ID, description |
| `sources` | Source IDs, paths, formats, JSON record paths, ignored-field reasons |
| `node_types` | Labels, stable keys, typed properties, constraints |
| `relationship_types` | Permitted relationship names and source/target types |
| `node_mappings` | Structured records to node keys and properties |
| `relationship_mappings` | Structured records to typed edges |
| `query_recipes` | Safe routes, examples, typed parameters, read-only Cypher, result meaning |
| `vector` | Chunk size, overlap, retrieval count |
| `ui` | Non-semantic canvas positions |

## Identifiers

Source IDs, type names, properties, mapping IDs, extraction IDs, and recipe IDs must match
`^[A-Za-z][A-Za-z0-9_]*$`. This makes dynamic Neo4j labels and relationship types safe to
interpolate after schema validation.

## Structured coverage

Every CSV or JSON field must appear in at least one mapping or in the source's
`ignored_fields`. An ignored field requires a non-empty reason.

Mapping direction is `target_property: source_field`.

## Text extractions

Optional `extractions.jsonl` contains one JSON object per relationship:

```json
{
  "id": "runbook_owner_fact",
  "source": "runbook",
  "subject_type": "Service",
  "subject_key": "svc-auth",
  "relationship_type": "OWNED_BY",
  "object_type": "Team",
  "object_key": "team-identity",
  "exact_quote": "The Authentication Service is owned by Identity Foundations.",
  "locator": "heading:Ownership",
  "confidence": 0.96
}
```

The compiler verifies that:

- the source is a declared Markdown or text file
- the exact quote occurs in that file
- the subject and object already exist
- the relationship and direction are permitted by the ontology
- IDs are unique
- confidence is between 0 and 1

Agents never write extracted facts directly to Neo4j.

## Query safety

Graph and hybrid recipes must:

- include Cypher
- use `$tenant_id`
- declare every other parameter
- contain `RETURN`
- contain a numeric `LIMIT`
- bound every variable-length traversal, such as `*0..3`

Recipes reject semicolons, `CREATE`, `MERGE`, `DELETE`, `DETACH`, `SET`, `DROP`, `REMOVE`,
`LOAD CSV`, `CALL`, `FOREACH`, and unbounded traversal.

Vector recipes may not contain Cypher.

## Approval semantics

The approval digest covers normalized GraphSpec semantics but excludes `ui`. The source digest
covers the ordered list of relative source paths and SHA-256 file hashes.

Changing mappings, recipes, types, metadata, vector configuration, or source content invalidates
approval. Repositioning a canvas node does not.
