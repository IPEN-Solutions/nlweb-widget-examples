# Apache CouchDB as an authoritative document source

The domain-site extractor example can ingest a CouchDB database as a custom Widget content source. This is an alternative to a filesystem/object-storage inbox, not a requirement for the Widget runtime. The example uses CouchDB's HTTP API through the existing `httpx` dependency and keeps provider integration isolated in the Examples package.

## Enable it

1. Install and start Apache CouchDB.
2. Copy the selected example folder’s `.env.example` to `.env` beside that example and set `NLWEB_COUCHDB_URL` and `NLWEB_COUCHDB_DATABASE`; every `.env.example` includes blank `NLWEB_DOCUMENT_STORE_USERNAME` and `NLWEB_DOCUMENT_STORE_PASSWORD` assignments; leave both blank for an unauthenticated local instance, or set both in your private local `.env` if authentication is enabled. Every example registry has a disabled CouchDB source. Examples with an owned `content/inbox/` also have a matching initializer under `content/scripts/initialize_couchdb.py`.
3. For a first-use demonstration, run the opt-in initializer from the repository root:

   ```powershell
   uv run python examples/external_hosted_sources/domain_site_extractor/content/scripts/initialize_couchdb.py
   ```

   It creates the database named by `NLWEB_COUCHDB_DATABASE` if needed and seeds one CouchDB document per supported artifact in `content/inbox/`, mapping `type`, `grounding`, `citations`, and `schema_refs` from `nlweb-evidence-manifest.json`. It extracts text from TXT/Markdown, JSON-LD, DOCX, PDFs with selectable text, and PowerPoint text. It does not perform OCR. The script validates that the manifest and supported inbox artifacts match before writing.
4. After initialization, use CouchDB Fauxton or your own scripts to add, update, or remove documents for your domain. The initializer is only a startup convenience, not a synchronization daemon or ongoing source of truth. It never deletes documents or overwrites a seeded document whose content/evidence attributes have changed; such conflicts stop the run with an actionable error.
5. For consumer-authored documents, prefer `title`, `url` or `source_url`, and optionally `type`, `grounding`, `citations`, `schema_refs`, `artifact`, `document_type`, and a `metadata` object.
6. In `nlweb-sources.json`, enable `authoritative_domain_document_store`, set its `site` to the consumer-controlled corpus ID used by your Widget queries, and update `metadata.url` to the public domain URL used as the fallback evidence URL. Disable `authoritative_domain` if you do not also want the file/object inbox ingested. Do not enable both unless you intentionally want both sources projected into the same corpus.

The registry uses `couchdb+${NLWEB_COUCHDB_URL}/${NLWEB_COUCHDB_DATABASE}` as its `location` to distinguish a document database from an ordinary HTTP URL or an fsspec-backed bucket. The URL and database are both environment-backed; there is no static host or database in the registry template. There is no duplicate `metadata.document_store_location`; `location` is authoritative. The registry source has `remote_storage_options` only when it represents remote object storage, not for CouchDB or local files. The source's `document_store_options` accepts `${ENV_VAR}` references for `database`, `username`, and `password`; the `database` option takes precedence over the database suffix in the location URI. secret values are resolved at runtime and must not be committed. The initializer and CouchDB ingestion client bypass environment proxies for loopback endpoints only; remote endpoints still honor proxy variables. This avoids local proxy interference (for example, proxy-generated 403 responses) without disabling proxies globally.

## Document contract

Example document:

```json
{
  "_id": "capability:industrial-platforms",
  "title": "Industrial platforms",
  "type": "Service",
  "url": "https://example.org/services/industrial-platforms",
  "content": "Evidence-backed description of the service.",
  "grounding": {"source": "https://example.org/services/industrial-platforms", "description": "Extracted from the published service page"},
  "citations": [{"label": "Service page", "source_url": "https://example.org/services/industrial-platforms"}],
  "schema_refs": ["https://schema.org/Service"],
  "artifact": "services/industrial-platforms",
  "document_type": "service-page"
}
```

The document attributes supply the equivalent of the evidence-manifest fields directly, so this path does not require `nlweb-evidence-manifest.json`. `grounding`, `citations`, and `schema_refs` are retained as retrieval metadata and source schema attributes. The source URL should identify the public evidence page; the CouchDB database URL is only a transport address.

## Limits and operational notes

- The example reads `_all_docs?include_docs=true` with pagination; use a dedicated database or database-level access policy to constrain the document set.
- This adapter reads the document database into the retrieval projection; it does not turn the retrieval index into the source of truth. The Examples loader namespaces IDs by registry source name and, after a successful enumeration, removes stale retrieval IDs previously tracked for that same source. This does not delete documents from CouchDB. Review synchronization and authorization boundaries before production use.
- Use HTTPS and a secret manager outside local development. Do not expose CouchDB to the public internet.
- The adapter skips design/local documents and documents without non-empty content.
- Test against a disposable database before enabling startup synchronization.


### All three source modes in each example registry

Each example registry exposes local disk, S3-compatible remote storage, and CouchDB document-store source entries. Local/scenario sources are enabled for the runnable baseline; remote and CouchDB entries are disabled by default and can be enabled after configuration. They are complementary sources, not a precedence chain. Each `name` is a distinct identity and receives its own retrieval-ID namespace. Successful sync replaces that source's current projection and removes stale IDs from that source only.
