# Provider-backed domain examples

These examples demonstrate every optional retrieval backend currently exposed by
`nlweb-widget` while keeping the widget's public provider boundary unchanged.

## Backend matrix

| Example | Backend | External service | Best use |
|---|---|---|---|
| `haystack_inmemory/` | Haystack `InMemoryDocumentStore` + `InMemoryEmbeddingRetriever` (`NLWEB_RETRIEVAL_STORE=haystack-memory`) | No | local development, small corpora, pipeline experiments |
| `qdrant_edge/` | Qdrant Edge | No | embedded/local vector retrieval |
| `qdrant_server/` | Qdrant Server/Cloud client | Qdrant Server for local demo | durable/shared vector service |
| `postgres_pgvector/` | PostgreSQL + pgvector | PostgreSQL | relational source + vector retrieval |
| `neo4j/` | Neo4j vector index / knowledge graph | Neo4j | graph-aware domain data |
| `sqlite/` | SQLite FTS5 + sqlite-vec hybrid retrieval | No | lightweight local hybrid retrieval |

All six use the same IPEN-like domain corpus. Structured JSON-LD remains an
authoritative structured source. PDF, PPTX, TXT and Markdown sources enter the
Widget through `ContentSourceKind.CUSTOM`, are normalized by Haystack's
`MultiFileConverter`, then conservatively chunked before indexing. Markdown cleanup is deliberately not applied globally: blank lines, indentation, table rows and fenced code can be semantically significant. If adding preprocessing, validate its effect on Markdown/code-heavy corpora and compare retrieval quality, not only token count.

## Haystack InMemory

Copy `haystack_inmemory/.env.example` to `haystack_inmemory/.env`, then run:

```powershell
uv run uvicorn examples.provider_backends.haystack_inmemory.app:app --port 8000
uv run python examples/provider_backends/haystack_inmemory/query_demo.py
```

No database or vector service is required. The store is process-local and is
intended for development, demonstrations and small-scale experiments, not as
a durable production database.

## Qdrant Edge

Copy `qdrant_edge/.env.example` to `qdrant_edge/.env` and run:

```powershell
uv run uvicorn examples.provider_backends.qdrant_edge.app:app --port 8000
uv run python examples/provider_backends/qdrant_edge/query_demo.py
```

The provider owns its local storage path and vector dimensions through its
`.env`; it does not share state with the Qdrant Server example.

## Qdrant Server / Cloud

Start the local Qdrant service:

```powershell
docker compose -f examples/provider_backends/qdrant_server/infra/docker-compose.yml up -d
```

Copy `qdrant_server/.env.example` to `qdrant_server/.env`, then run:

```powershell
uv run uvicorn examples.provider_backends.qdrant_server.app:app --port 8000
uv run python examples/provider_backends/qdrant_server/query_demo.py
```

The same Widget provider supports a hosted Qdrant endpoint by replacing
`NLWEB_QDRANT_URL` and, when required, setting `NLWEB_QDRANT_API_KEY`.

## PostgreSQL + pgvector

Use `postgres_pgvector/.env.example`, initialize the provider-owned PostgreSQL
instance, and run its FastAPI/query demonstration. The provider test is
conditional: without an explicit database URL it skips; once configured, a
connection or retrieval failure fails the test.

## Neo4j

Use `neo4j/.env.example` and its query demonstration. Vector dimensions are
configuration-driven. Test-only Neo4j labels and indexes remain isolated from
production/example entities.

## SQLite + sqlite-vec

Copy `sqlite/.env.example` to `sqlite/.env`, then run:

```powershell
uv run uvicorn examples.provider_backends.sqlite.app:app --port 8000
uv run python examples/provider_backends/sqlite/query_demo.py
```

The provider keeps document metadata and FTS5 keyword search in SQLite and
combines it with sqlite-vec KNN retrieval through the same Widget provider
contract. The `sqlite-vec` extension is intentionally pinned because it remains
pre-v1; the current package pin is `0.1.8`.

## Common data flow

```text
authoritative domain files
        |
        v
CUSTOM ContentSource
        |
        v
Haystack MultiFileConverter
        |
        v
normalized ContentDocument
        |
        +--> Haystack splitter
        |
        +--> Sentence Transformers embeddings
        |
        v
selected retrieval backend
        |
        v
NLWeb /ask
```

The examples deliberately show the same ingestion boundary with different
retrieval stores so a consumer can compare backend behavior without learning
provider-specific internals.


### Local custom-file conversion

Provider examples use Haystack's `MultiFileConverter` for declared unstructured
source types. It provides one common `Document` boundary for PDF, PPTX, Markdown
and text without invoking Docling's local layout/RT-DETR pipeline. The examples
package therefore keeps its custom-file ingestion path suitable for constrained
Windows local-QA hosts.

### VS Code provider matrix

Each backend has three consistently named tasks: `Provider: <backend> — test`, `Provider: <backend> — run`, and `Provider: <backend> — query demo`. Matching debug configurations are `Python: Provider <backend>` and `Python: Provider <backend> query demo`.
