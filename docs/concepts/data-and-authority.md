# Domain data and authority

The examples are built around a simple boundary:

> **The application remains the authority for its domain content.**

Each reference scenario keeps its AI-facing demonstration data beside the application in `examples/<scenario>/data.json`. The file uses Schema.org/JSON-LD-compatible objects and is deliberately small enough to inspect, modify and replace.

```text
scenario data.json
       │
       ▼
nlweb-widget projection
       │
       ▼
 /ask /mcp /discovery
       │
       ▼
external AI consumer
```

Starter profiles provide reusable scenario seeds in the examples repository. They are not production runtime resources. A scenario combines one or more profiles into concrete domain data rather than treating the profile files as the application's authoritative database.

Provider infrastructure is separate again: PostgreSQL/pgvector and Neo4j setup fixtures are kept under `provider_backends/infra/` and exist to demonstrate optional retrieval backends. They are not authoritative scenario data.

The examples do not claim that an AI consumer will automatically discover, index or answer every query about an application. They demonstrate the application-side protocol surface required to make that information reachable.


## Externally hosted source evidence

An external hosted source can be an additional evidence input without becoming the authoritative domain source. The external-source example stores extraction evidence separately, can produce additive Schema.org/JSON-LD records for review, and then projects approved content through the same Widget boundary. The extractor does not override existing source state.
