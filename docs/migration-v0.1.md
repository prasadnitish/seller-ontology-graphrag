# Migrating from `v0.1-prototype`

The prototype remains available at the `v0.1-prototype` Git tag. V0.2 is a deliberate breaking
change.

## What changed

| V0.1 | V0.2 |
|---|---|
| Node.js seller-specific application | Python domain-independent package |
| One synthetic JSON source | CSV, JSON, Markdown, and text workspaces |
| Fixed browser questions | Approved free-text query recipes |
| Browser-computed output | Provider-neutral graph IR and optional Neo4j execution |
| Simulated vector score | Case-level routing evidence with no answer-quality claim |
| Hand-authored schema | Pydantic GraphSpec and generated JSON Schema |
| No approval workflow | Semantic and source-manifest approval hashes |

## Migration path

1. Export or copy the source data you want to preserve into a new `sources/` directory.
2. Run `graphkit init` against that directory.
3. Port ontology concepts into `graphspec.yaml`; use
   [`examples/seller/graphspec.yaml`](../examples/seller/graphspec.yaml) as the closest reference.
4. Express supported intents as bounded query recipes.
5. Convert any prose-only fact into structured source data or a quote-backed
   `extractions.jsonl` record.
6. Create held-out cases before changing the router.
7. Validate, review, approve, and build.

The old generated comparison report must not be migrated as evidence. Recreate any quality claim
from executed retrieval results and reference answers.
