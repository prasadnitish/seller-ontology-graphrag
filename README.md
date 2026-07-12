# Seller Ontology GraphRAG

A schema-first, tenant-scoped knowledge layer for relationship-dependent seller policy questions. One synthetic source file projects into both a Neo4j graph seed and a prose corpus, preventing fact drift in GraphRAG-versus-vector comparisons.

## Evidence path

Run `npm test`, `npm run project`, `npm run evaluate`, and `npm run load`. The comparison report includes the question, generated Cypher, governed answer, baseline answer, and score delta. With `VECTOR_RAG_URL` unset, the baseline is a deterministic simulation and the report says so. A live `rag-pipeline-guardrails` and Eval Control Tower judge run remains the external validation gate.

## Neo4j

Set `NEO4J_PASSWORD`, run `docker compose up`, apply `schema.cypher`, then pass the generated graph in `generated/seller-graph-seed.json` to `ingestGraph`. Every node and query is tenant-scoped; generated queries reject writes, unbounded traversal, missing tenant predicates, and missing result limits.

## Operating controls

Immutable events carry idempotency keys. Conflict retries are bounded and exhausted writes enter a dead-letter queue. Subgraph cache keys include tenant, ontology version, and data version; affected entities invalidate cached results.
