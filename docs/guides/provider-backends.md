# Configured provider examples

The provider suite demonstrates retrieval backends exposed by the current Widget package. Examples are independently configured and do not change the Widget's normative protocol or production dependency set.

## Provider matrix

| Backend | Example | Requires external service | Configuration |
|---|---|---:|---|
| Haystack InMemory | `haystack_inmemory` | No | provider `.env` |
| Qdrant Edge | `qdrant_edge` | No | provider `.env` |
| Qdrant Server/Cloud | `qdrant_server` | Yes unless existing service is used | provider `.env` |
| PostgreSQL + pgvector | `postgres_pgvector` | Yes | provider `.env` |
| Neo4j | `neo4j` | Yes | provider `.env` |
| SQLite + sqlite-vec | `sqlite` | No | provider `.env` |

## Provider-owned configuration

Every configured provider owns its `.env.example`. Copy it to `.env` in that provider directory. Tests skip an unconfigured provider and fail once that provider has been explicitly configured. Vector dimensions and paths are configuration-driven.

## Content ingestion

Structured JSON-LD is normalized directly. PDF, PPTX, Markdown, and text files use Haystack's `MultiFileConverter` and `DocumentSplitter`; DOCX uses `python-docx` for extraction and the shared splitter. When an evidence manifest is present, each declared artifact is processed independently: mismatches and unsupported formats are reported and skipped while healthy files continue. A partial sync withholds stale-record deletion until a clean sync. The external-hosted-source examples additionally demonstrate local/object-storage inbox ingestion, evidence manifests, and a CouchDB document-store alternative whose grounding/citations/schema references are stored as document attributes.
