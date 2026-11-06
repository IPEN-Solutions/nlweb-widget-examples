# Providers and stores

The examples keep authoritative domain data separate from the AI-facing retrieval projection. The Widget controls the protocol/store contract; this repository supplies runnable provider infrastructure and low-cost example embeddings.

```text
authoritative domain source
       ↓
content synchronization
       ↓
ContentDocument projection
       ↓
embedding provider
       ↓
retrieval store
   ┌────┼────────┐
 memory pgvector Neo4j
```

## Configuration ownership

Each provider example owns its own `.env`. The provider-owned file is authoritative for that provider and is also the source used by its VS Code launch/run entries and configured-provider tests. The workspace-root `.env` is not a substitute for a provider's backend configuration.

Production vector dimensions are configuration, not example constants. For Neo4j, `NLWEB_NEO4J_VECTOR_DIMENSIONS` supplies the production dimension and the bootstrap fixture receives that value. Neo4j recommends specifying vector dimensions so mismatches fail clearly.

## Neo4j test isolation

The configured Neo4j provider test deliberately does **not** initialize or assert the production/example store. It creates only the test-side schema:

- label/property: `NLWebTestDocument.embedding`
- vector index: `test_nlweb_document_embedding_r1`
- production schema remains: `NLWebDocument.embedding`
- production index remains: `nlweb_document_embedding`

The test uses the same configured database because a second database is unnecessary for this contract. The separate label is the schema boundary, preventing test nodes from entering the production vector index. Neo4j's current vector-index model explicitly describes vector indexes in terms of indexed labels/properties and configured dimensions.

## PostgreSQL + pgvector

The PostgreSQL example uses the Widget document fields and the configured pgvector dimension. The example's provider-owned environment controls the database connection and vector settings.

## Dynamic document ingestion

Provider examples discover supported files in their `content/inbox` at runtime. Structured JSON-LD, TXT, PDF, PPTX, and other supported inputs are processed through the example ingestion path rather than being hard-coded into the application. Structured domain projection remains distinct from unstructured retrieval content.
