# Architecture

The Examples package is a runnable integration layer around the separately versioned `nlweb-widget` runtime. It demonstrates framework adapters, provider choices, source ingestion and visibility without moving example-only dependencies into the production Widget package.

```text
Domain-owned data / document store / object storage
                   │
      optional extraction and ingestion examples
                   │
                   ▼
       Widget-compatible content source
                   │
                   ▼
       NLWeb Widget retrieval + protocol
```

The source-of-truth remains the domain's responsibility. ScrapeGraphAI and local Scrapy + Ollama are optional extraction approaches, not required runtime dependencies. The file/object inbox can use an evidence manifest; the CouchDB example keeps evidence attributes on each document.
