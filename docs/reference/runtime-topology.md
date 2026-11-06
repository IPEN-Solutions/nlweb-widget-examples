# Runtime topology

The reference suite has three conceptually separate runtime layers:

```text
Layer 1: domain application
┌────────────────────────────────────┐
│ framework example                  │
│ authoritative/scenario domain data │
│ nlweb-widget                       │
│ /ask /mcp                          │
└────────────────┬───────────────────┘
                 │
                 │ optional provider store
                 ▼
        memory / pgvector / Neo4j

Layer 2: external AI consumer
┌────────────────────────────────────┐
│ AskAgent (optional)                │
│ retrieval / ranking / response     │
└────────────────┬───────────────────┘
                 │
                 ▼
          real HTTP boundary
```

The default test suite validates Layer 1 deterministically. AskAgent visibility is an explicit external test and is intentionally skipped unless live configuration is supplied.

Provider tests have their own isolation boundary: PostgreSQL uses a test table, while Neo4j uses `NLWebTestDocument.embedding` and `test_nlweb_document_embedding_r1` in the configured database without touching production/example entities.
