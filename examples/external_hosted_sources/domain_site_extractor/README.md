# External hosted-domain source adapter example

This example demonstrates optional hosted-source acquisition while keeping the approved
`nlweb-widget` runtime unchanged. The authoritative inbox is ingested through the example's custom
provider loader, while each hosted extraction scenario produces one exact JSON-LD artifact under its
declared corpus ID.

## The source-of-truth contract

Three identities are intentionally separate:

- **Canonical domain identity** (`NLWEB_EXTERNAL_SOURCE_SITE`) is a URL used as the JSON-LD
  `isPartOf` context and to recognize the untouched placeholder fixture. It is not a retrieval
  filter and does not rewrite corpus IDs.
- **Retrieval corpus ID** (`site` in `nlweb-sources.json`) is a consumer-controlled token used by
  the Widget's existing retrieval filter. It may be a hostname-like ID, but it is not required to
  be a URL or proof of domain ownership. The Widget currently performs exact matching; a parent
  ID does not automatically include subdomain IDs. When custom and LLM extraction are both run,
  the custom output retains the scenario ID and each LLM output uses `<scenario-site>--<backend>`
  (for example `external-source.example--scrapy_transformers`) to keep site-filtered results distinct.
- **Authoritative content** lives in `content/inbox/` and may include JSON-LD plus unstructured
  PDF/PPTX/text files. Each source entry declares the corpus under which its file is ingested.

`nlweb-sources.json` is the portable, checked-in content-sync registry. The `authoritative_domain`
source intentionally points to the `content/inbox/` directory so supported JSON/JSON-LD, Markdown,
text, PDF and PPTX files can be discovered without hard-coded filenames. Each hosted extraction
scenario instead points to one exact file under `generated/`; those scenario entries never scan a
shared generated directory. The app writes `runtime/config/nlweb-sources.json` as a runtime-only copy
with absolute paths: because that copy is nested under `runtime/config`, keeping the relative paths
would make the Widget resolve them against the wrong directory. The checked-in registry remains
relative and is never rewritten. This preserves the deliberate distinction between inbox discovery
and exact per-scenario generated artifacts. The checked-in `content/inbox/` and the root website scenario use
the `external-source.example` corpus by default. The other hosted scenarios use distinct defaults:

| Scenario / registry name | Default corpus ID (`site`) | Exact JSON-LD artifact |
|---|---|---|
| `authoritative_domain` | `external-source.example` | `content/inbox/` (supported files discovered at startup) |
| `company_website` | `external-source.example` | `generated/external-source.example.jsonld` |
| `company_knowledge_base` | `help.external-source.example` | `generated/help.external-source.example.jsonld` |
| `product_service_catalog` | `products.external-source.example` | `generated/products.external-source.example.jsonld` |
| `company_portal` | `manuals.products.external-source.example` | `generated/manuals.products.external-source.example.jsonld` |
| `company_newsroom` | `news.external-source.example` | `generated/news.external-source.example.jsonld` |

The sample uses host-like corpus IDs to make separation legible, not because the Widget requires
hostnames. Choose stable, consumer-owned IDs. The `authoritative_domain.metadata.url` value is a
source-level URL fallback for documents that do not declare their own URL: explicit JSON-LD `url` or
`@id` values and URLs supplied by the document converter take precedence. Set this metadata value to
a consumer-owned canonical content URL when appropriate; the sample defaults to
`https://external-source.example/`. The same `metadata.url` convention is supported by the shared
provider-widget builder, so provider examples can declare their own fallback URL without changing
runtime code. When switching from the placeholder to a real domain,
edit the intended corpus IDs in both `sources.toml` and the matching generated-scenario `nlweb-sources.json`
entries; `NLWEB_EXTERNAL_SOURCE_SITE` deliberately does not rewrite them. If the checked-in
`domain.jsonld` still identifies the placeholder host, runtime configuration excludes only that file
for a real domain and leaves the inbox directory enabled, so consumer-provided unstructured files are
still ingested. Replace the fixture with your own JSON-LD to include it. If queries should span several
corpora, the caller must explicitly issue queries for those IDs or use an application-level
aggregation strategy.

## Artifact evidence manifest and storage locations

The active QA inbox manifest is `content/inbox/nlweb-evidence-manifest.json`. Its `artifacts` entries use relative paths from that inbox and may provide a fallback Schema.org `type` plus a `grounding` object. The grounding fixture demonstrates `source`, `description`, `citations` (`label`, `source_url`, optional `page`) and `schema_refs`. Source-provided suitable `@type` takes precedence over the manifest fallback. The ingestion code retains grounding metadata without normalizing custom fields. Conflicting source and manifest grounding is an explicit error for structured source records.

The default registry uses local paths, which also supports mounted volumes. For object-store prefixes, set `location` to a URI supported by `fsspec` (such as `s3://bucket/prefix/`, `gs://bucket/prefix/`, or `az://container/prefix/`), install `uv sync --extra remote-storage` (includes both `fsspec` and `s3fs`) plus the backend's filesystem package, and configure credentials outside the checked-in registry. See the [authoritative data contract guide](../../../docs/guides/authoritative-domain-data-contract.md) for limitations and the distinction between example conventions and Widget API requirements.

## Local proxy behavior

The CouchDB initializer and CouchDB ingestion client bypass environment-configured HTTP proxies for loopback URLs (`localhost`, `127.0.0.0/8`, and `::1`). This avoids proxy-generated errors such as HTTP 403 when the CouchDB service is running on the same machine. If `NLWEB_COUCHDB_URL` points to a non-loopback host, HTTPX continues to honor the normal proxy environment settings. The same loopback-only policy is used by local query demos; remote service requests retain proxy support.

## Optional CouchDB first-use seed

The optional `authoritative_domain_document_store` registry source is disabled by default. The registry `name` is the stable source identity; successful syncs refresh that source and delete stale IDs previously tracked for the same name without deleting other sources. To seed the example corpus into a local CouchDB 3.x instance, configure `NLWEB_COUCHDB_URL`, `NLWEB_COUCHDB_DATABASE`, and optional credentials in this example's `.env`, then run from the repository root:

```powershell
uv run python examples/external_hosted_sources/domain_site_extractor/content/scripts/initialize_couchdb.py
```

The initializer creates the configured database if needed and creates one document per supported file in `content/inbox/`, using `nlweb-evidence-manifest.json` for type and evidence attributes. It validates the manifest and inbox inventory. During ingestion, supported artifacts are processed independently: missing, unsupported, undeclared, or malformed artifacts are reported and skipped while healthy artifacts continue; stale-record deletion is withheld for a partial sync so a skipped artifact does not erase its previously indexed records. It is idempotent for unchanged seed documents and will not overwrite or delete consumer-edited records. Use Fauxton or your own scripts for subsequent manual maintenance. PDF extraction requires selectable text; this example does not perform OCR. See [the CouchDB guide](../../../docs/guides/document-store-couchdb.md) for the document contract and limits.

## Configuration and one-to-one mapping

- `sources.toml` maps each extraction scenario to its URL environment variable, explicit corpus ID,
  and exact generated artifact path.
- `prompts/extraction_scenarios.toml` has the same scenario keys and supplies each prompt/schema hint.
- `nlweb-sources.json` has a generated-source entry whose `name` exactly matches the scenario key;
  its `site` and `location` must match the values in `sources.toml`.
- `registry.py` validates this contract before extraction or runtime registry generation. Duplicate
  artifacts, missing prompt/source counterparts, mismatched names, unsafe paths, or mismatched corpus
  IDs fail loudly. Relative local `location` values are resolved against the directory of the
  registry that declares them, never against PowerShell's current working directory. If
  `NLWEB_CONTENT_SOURCES_FILE` explicitly points to this example's own `nlweb-sources.json`, the
  app still generates its runtime-normalized registry; a genuinely external registry remains
  consumer-owned.

The URL environment variables are empty by default, and extraction is disabled by default. The
runtime registry enables a generated scenario only when that scenario's exact artifact exists.
Artifacts for other scenarios and stray files in `generated/` are never scanned by that entry.
If a prior artifact exists, it remains available until replaced; review it when source URLs or
extraction prompts change. The example does not silently delete consumer data or claim that an old
artifact is fresh.

## Install optional extraction providers

The Widget app and checked-in corpus do not require ScrapeGraphAI or Playwright. To use the
browser-backed LLM extractor:

```powershell
uv sync --extra external-scrapegraphai
uv run playwright install chromium
```

Installing the Python dependency does not install the Chromium executable. Configure the selected
source URL, the exact hostname allowlist, provider credentials, and then explicitly set
`NLWEB_EXTERNAL_SOURCE_LLM_ENABLED=true`. For a consumer-owned or deterministic extractor, set
`NLWEB_EXTERNAL_SOURCE_EXTRACTOR_FACTORY=python.module:callable`, install any required optional
packages, and set `NLWEB_EXTERNAL_SOURCE_ENABLED=true`. Do not enable both extraction modes without
understanding the precedence and provider behavior. External source content may be sent to an LLM
provider and may incur charges.

## Configuration reference

Copy `.env.example` to `.env`. This example loads its own `.env` with `override=True`; values in that
file can override same-named shell variables.

### Widget enablement and source synchronization

The following settings are explicit in this example's `.env.example`, matching the provider-backend
examples. Leave them enabled for the normal startup ingestion path; set them false only when
intentionally disabling Widget projection or startup sync.

| Variable | Default | Effect |
|---|---|---|
| `NLWEB_ENABLED` | `true` | Enables the Widget. |
| `NLWEB_CONTENT_SYNC_ENABLED` | `true` | Enables configured source synchronization. |
| `NLWEB_CONTENT_SYNC_ON_STARTUP` | `true` | Lets `Widget.startup()` ingest the configured sources. |
| `NLWEB_CONTENT_SYNC_INTERVAL_SECONDS` | `0` | Disables periodic background sync; startup sync still runs. |
| `NLWEB_CONTENT_SYNC_STATE_FILE` | `runtime/state/.nlweb-sync-state.json` | Records source sync outcomes. |

### Source identity and mapping

| Variable | Default | Effect |
|---|---|---|
| `NLWEB_EXTERNAL_SOURCE_SCENARIO` | `company_website` | Selects one of the five matching source/prompt scenarios. |
| `NLWEB_EXTERNAL_SOURCE_SITE` | `https://external-source.example/` | Canonical website URL for JSON-LD context and placeholder-fixture handling. Does not overwrite registry corpus IDs. |
| `NLWEB_EXTERNAL_SOURCE_ALLOWED_HOSTS` | unset | Comma-separated exact hostnames permitted for extraction. Every requested source hostname must be listed. |
| `NLWEB_EXTERNAL_SOURCE_COMPANY_WEBSITE_URL` | unset | Root website URL. |
| `NLWEB_EXTERNAL_SOURCE_KNOWLEDGE_BASE_URL` | unset | Knowledge-base/help URL. |
| `NLWEB_EXTERNAL_SOURCE_PORTAL_URL` | unset | Portal/documentation URL. |
| `NLWEB_EXTERNAL_SOURCE_CATALOG_URL` | unset | Product/service catalog URL. |
| `NLWEB_EXTERNAL_SOURCE_NEWSROOM_URL` | unset | Newsroom/publication URL. |
| `NLWEB_CONTENT_SOURCES_FILE` | example-owned registry generated under `runtime/config/` | Optional Widget registry override. If it points to this example’s own `nlweb-sources.json`, runtime paths and fresh backend artifacts are still normalized. A genuinely external consumer-owned registry is left untouched and must declare correct paths and corpus IDs. |

Run the standalone CLI once per scenario, for example:

```powershell
uv run python -m examples.external_hosted_sources.domain_site_extractor.demo company_website
uv run python -m examples.external_hosted_sources.domain_site_extractor.demo product_service_catalog
```

Each invocation writes only that scenario's configured artifact and a matching `.manifest.json`
provenance file. There is deliberately no global
`NLWEB_EXTERNAL_SOURCE_JSONLD_OUTPUT` override because it would break the one-to-one mapping.

### Extraction and LLM

| Variable | Default | Effect |
|---|---|---|
| `NLWEB_EXTERNAL_SOURCE_ENABLED` | `false` | Explicit opt-in for a configured custom extractor, including non-LLM extractors. |
| `NLWEB_EXTERNAL_SOURCE_LLM_ENABLED` | `false` | Explicit opt-in for LLM-backed extraction (remote or local, depending on the selected backend). |
| `NLWEB_EXTERNAL_SOURCE_EXTRACTOR_BACKEND` | required when extraction runs | Explicit backend choice: `scrapegraphai`, `scrapy_ollama`, `scrapy_transformers`, or `custom`; code has no implicit backend default. |
| `NLWEB_EXTERNAL_SOURCE_EXTRACTOR_FACTORY` | unset | Optional `python.module:callable` factory returning an object with async `extract(request)`. |
| `NLWEB_EXTERNAL_SOURCE_LLM_PROVIDER` | `openrouter` | Provider label for the ScrapeGraphAI implementation. |
| `NLWEB_EXTERNAL_SOURCE_LLM_MODEL` | `openai/gpt-4o-mini` | Model identifier. |
| `NLWEB_EXTERNAL_SOURCE_LLM_BASE_URL` | `https://openrouter.ai/api/v1` | OpenAI-compatible endpoint. |
| `NLWEB_EXTERNAL_SOURCE_LLM_API_KEY` | unset | Explicit provider key; never commit a real secret. |
| `OPENROUTER_API_KEY` | unset | OpenRouter fallback credential. |
| `NLWEB_EXTERNAL_SOURCE_LLM_TEMPERATURE` | `0` | LLM sampling temperature. |
| `NLWEB_EXTERNAL_SOURCE_HEADLESS` | `true` | Browser display mode; Chromium is still required. |
| `NLWEB_EXTERNAL_SOURCE_EXTRACTION_DB` | `runtime/extracted-content.sqlite3` | Separate evidence database, not the Widget retrieval store. |

### Retrieval and embeddings

| Variable | Default | Effect |
|---|---|---|
| `NLWEB_RETRIEVAL_STORE` | `sqlite` | Widget retrieval backend. |
| `NLWEB_SQLITE_PATH` | `./runtime/retrieval/nlweb.db` | Retrieval database path. |
| `NLWEB_SQLITE_DIMENSIONS` | `384` | Must match the embedding model output dimension. |
| `NLWEB_EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Embedding model. |
| `NLWEB_EMBEDDING_DEVICE` | `cpu` | Embedding device. |
| `NLWEB_EMBEDDING_BATCH_SIZE` | `1` | Conservative embedding batch size for low-memory local runs. |
| `NLWEB_EMBEDDING_NORMALIZE` | `true` | Normalize vectors when supported by the provider. |

Do not mix embedding dimensions in an existing database. Old retrieval rows are not automatically
removed when a source is disabled or its corpus ID changes; use a fresh disposable database for
clean local QA.

## Run the app and query it

```powershell
uv run uvicorn examples.external_hosted_sources.domain_site_extractor.app:app --host 127.0.0.1 --port 8000 --env-file examples/external_hosted_sources/domain_site_extractor/.env
```

Then, in another terminal:

```powershell
uv run python examples/external_hosted_sources/domain_site_extractor/query_demo.py
```

The app runs extraction only when explicitly enabled, refreshes its runtime registry after extraction,
and then lets `Widget.startup()` perform the one configured source-sync pass. It does not disable
`content_sync_on_startup` or call `sync_sources(force=True)` a second time. `/external-source/status`
reports extraction, per-scenario artifact freshness/disable reasons, and outcomes read from the Widget
sync-state file. The app continues serving checked-in content if optional extraction fails,
but a failure is not evidence that hosted content was indexed. `/ask` and `/mcp` use the standard
Widget integration. The standalone `demo.py` writes the artifact and evidence but does not start a
Widget; start/restart the app to ingest it.

The optional BeautifulSoup alternative can be installed with `uv sync --extra external-beautifulsoup`.
It parses a configured page deterministically without a browser or LLM; it does not crawl linked pages
or infer unsupported relationships. It retains valid `application/ld+json` script objects as separate additive records before removing script markup from visible text; malformed or oversized JSON-LD blocks are ignored. The source-provided claims are retained, not independently authenticated by this extractor. `edgextract` remains a possible future optional adapter, not a
current dependency.

Official protocol reference: [NLWeb Specification](https://nlweb.ai/docs/specification).


## Local-first Scrapy + Ollama alternative

This optional path sits beside (and does not replace) ScrapeGraphAI. On a constrained local machine, start with Ollama `qwen2.5:0.5b`, a up to five same-host pages by default, and sequential crawling. Install `uv sync --extra local-scrapy-ollama`, install Ollama separately, and pull the model with `ollama pull qwen2.5:0.5b`. Then run:

```powershell
uv run python -m examples.external_hosted_sources.domain_site_extractor.local_scrapy_ollama https://your-domain.example/ --allowed-hosts your-domain.example --max-pages 5 --depth-limit 2
```

The extractor preserves parsed JSON-LD source objects directly, and asks Ollama only for evidence-backed claims from visible page text. It emits `generated/local-scrapy-ollama.jsonld`; pass that file through the existing inbox/registry workflow deliberately if you want Widget startup synchronization to ingest it. It does not automatically overwrite the active authoritative artifact. The small model is best-effort and may omit valid claims; every model-derived record is marked `unverified-extraction` and includes an evidence quotation. This is not a source-authenticity check. Each crawled page is also retained in `runtime/local-scrapy-ollama-items.jsonl` and persisted as an independent audit row in `runtime/extracted-content.sqlite3`, with `extractor=scrapy_ollama`, provider `ollama`, scenario, source URL, and model ID. The command summary reports `persisted_items` and `extraction_db`; use `--scenario` and `--db-path` to override the defaults (also configurable with `NLWEB_EXTERNAL_SOURCE_SCENARIO` and `NLWEB_EXTERNAL_SOURCE_EXTRACTION_DB`). This audit database is separate from the Widget retrieval database and does not combine the Ollama result with other backend artifacts.

## Local-first Scrapy + Hugging Face Transformers alternative

This is a separate local LLM path that loads `Qwen/Qwen2.5-0.5B-Instruct` directly through Transformers; no Ollama server is used. Install `uv sync --extra local-scrapy-transformers`. On first run, model weights are downloaded from Hugging Face and cached. The resource-constrained defaults target a dual-core CPU / 4 GB RAM: CPU, two PyTorch threads, 1,024 input tokens, 2,000 page characters, 96 generated tokens, three pages at depth one. A first run still needs several GB of disk space and the process may be slow; avoid concurrent embedding/indexing. See the [resource-constrained guide](../../../docs/guides/local-scrapy-transformers.md).

```powershell
uv run --extra local-scrapy-transformers python -m examples.external_hosted_sources.domain_site_extractor.local_scrapy_transformers https://your-domain.example/ --allowed-hosts your-domain.example --max-pages 1 --depth-limit 0
```

The standalone output is `generated/local-scrapy-transformers.jsonld`. Each crawled page is also written to `runtime/local-scrapy-transformers-items.jsonl` and audited in the separate `runtime/extracted-content.sqlite3` database with `extractor=scrapy_transformers`, provider `huggingface-transformers`, and the selected model ID. Omit `--max-pages` and `--depth-limit` to use the conservative three-page/depth-one defaults. To select it for the configured LLM extraction flow, set `NLWEB_EXTERNAL_SOURCE_EXTRACTOR_BACKEND=scrapy_transformers` and `NLWEB_EXTERNAL_SOURCE_LLM_ENABLED=true`. When custom and LLM extraction are both enabled, their artifacts and provenance remain separate. The custom path keeps the scenario's base corpus ID; the LLM artifact uses a backend-specific ID such as `external-source.example--scrapy_transformers`, so a site-filtered `/ask` query selects one extraction corpus rather than returning its overlapping records twice. Unfiltered queries can still return records from both independent sources. JSON-LD and page text survive model errors, while model-derived claims are evidence-quote checked and marked `unverified-extraction`. See the [full guide](../../../docs/guides/local-scrapy-transformers.md).

## Remote filesystem options

Each `nlweb-sources.json` source may include a `remote_storage_options` object passed to `fsspec.core.url_to_fs(url, **kwargs)`. Values may use `${ENV_VAR}` placeholders resolved at runtime. Empty placeholders are omitted so the provider's native credential chain can be used. Never commit real secrets or log resolved options. The checked-in `authoritative_domain_remote_storage` entry in `nlweb-sources.json` is the working S3-compatible configuration example; copy its options into your own source entry and keep secrets in the private `.env`.


### Runtime-only excluded filename behavior

`prepare_runtime_source_registry` may add `metadata.excluded_filenames` only when a real canonical site is configured and the local authoritative inbox still contains the untouched placeholder `domain.jsonld`. This generated runtime value prevents indexing that placeholder as if it described the consumer's real site. It is not required in the checked-in registry template, does not exclude other consumer artifacts, and is not applied to remote object-store locations. Remote sources use the `location` URI itself as the bucket/prefix scope.


### Independent extraction gates

`NLWEB_EXTERNAL_SOURCE_ENABLED=true` runs the configured custom non-LLM factory path, while `NLWEB_EXTERNAL_SOURCE_LLM_ENABLED=true` separately permits the selected LLM backend. Set `NLWEB_EXTERNAL_SOURCE_EXTRACTOR_BACKEND` explicitly; `scrapegraphai`, `scrapy_ollama`, and `scrapy_transformers` require the LLM flag, while `custom` requires the source flag and a factory path. If both enable flags are true, the custom and LLM paths execute separately and write distinct backend-specific JSON-LD artifacts with separate provenance manifests. Runtime source synchronization registers each artifact as its own source. The custom artifact retains the scenario's configured corpus ID; each non-custom LLM artifact uses `<scenario-site>--<backend>` as its retrieval corpus ID. This makes site-filtered queries backend-specific and avoids duplicate results from overlapping independent corpora; unfiltered queries can still retrieve both. No automatic merge or reconciliation occurs. No LLM path runs merely because a backend name appears in `.env.example`.
