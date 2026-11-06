# External hosted-domain sources

The examples package demonstrates hosted-domain acquisition as an optional custom source
adapter. It does not add a new Widget ingestion architecture or change the frozen Widget.

```text
hosted website / portal / knowledge base / catalog / newsroom
                 -> optional extractor
                 -> extraction evidence SQLite + JSON-LD artifact
                 -> generated/ configured custom source
                 -> normal Widget startup source synchronization
                 -> existing retrieval store and NLWeb projection
                 -> /ask and /mcp
```

## Responsibilities and configuration files

- `prompts/extraction_scenarios.toml` contains the prompt and schema hint for each scenario.
- `sources.toml` maps each matching scenario key to its URL environment variable, consumer-controlled
  retrieval corpus ID (`site`), and one exact generated JSON-LD artifact path.
- `nlweb-sources.json` is the Widget's content-sync registry. Every entry has an explicit corpus ID.
  The authoritative source deliberately points to `content/inbox/` and discovers all supported files
  there, including unstructured Markdown, text, PDF and PPTX. Each generated scenario points to one
  exact artifact file under `generated/`, so generated corpora are never scanned across scenarios.
- Each `[sources.<scenario>]` section, `[scenarios.<scenario>]` prompt section, and generated-source
  registry entry must have the same name. `sources.toml`'s `site` and `artifact` must exactly match
  the corresponding registry entry. The example validates these constraints before extraction.
- `.env.example` documents adapter, demo, retrieval, and optional registry-override settings.

Three concepts stay separate: `NLWEB_EXTERNAL_SOURCE_SITE` is a canonical website URL used for JSON-LD
context and placeholder fixture handling; registry `site` is a retrieval corpus token; and the source
URL allowlist is a separate extraction security boundary. The Widget's current site filtering is exact
matching, so a parent hostname-like corpus ID does not automatically include subdomain corpus IDs.
Consumers should select stable IDs and explicitly aggregate/query multiple IDs when needed. When
switching to a real domain, update the chosen corpus IDs in both `sources.toml` and matching registry
entries; the canonical URL setting intentionally does not rewrite retrieval corpus IDs.

Generated scenario entries are enabled only when their exact configured artifact and provenance
manifest match the artifact hash, configured source URLs, canonical URL, and prompt/schema fingerprint.
Missing or stale artifacts remain disabled with a reason; stray files in `generated/` are not indexed.
The checked-in registry is never rewritten; a runtime copy is created under `runtime/config/`. An explicit
`NLWEB_CONTENT_SOURCES_FILE` override remains consumer-managed and must preserve the same exact-file and
corpus-ID contract.

## Optional ScrapeGraphAI and manual Playwright setup

ScrapeGraphAI is an optional implementation of the provider-neutral `ExternalSourceExtractor`
contract. It is not required to start or use the ordinary Widget app. Install it only to run
the extraction command:

```powershell
uv sync --extra external-scrapegraphai
uv run playwright install chromium
```

Installing the Python dependency does not install the Chromium executable. The second command
is a manual prerequisite for the browser-backed extraction path, and should be repeated if a
Playwright upgrade changes its expected browser revision. A missing browser causes an explicit
extraction run to fail; it does not prevent the normal FastAPI app from starting. Headless mode
controls display, not whether Chromium must exist.

All extraction is disabled by default. For a custom/non-LLM factory, configure the selected scenario URL,
`NLWEB_EXTERNAL_SOURCE_ALLOWED_HOSTS`, and factory path, then explicitly set
`NLWEB_EXTERNAL_SOURCE_ENABLED=true`. For the default LLM-backed path, configure provider/model/base URL
and a credential, then explicitly set `NLWEB_EXTERNAL_SOURCE_LLM_ENABLED=true`. Source content may be sent to the configured LLM
provider and may incur charges. Never commit API keys. See the example README for the complete
configuration table and precedence details.

## Four configuration groups

1. **Source selection and identity:** scenario, scenario-specific URL, hostname allowlist, canonical
   `NLWEB_EXTERNAL_SOURCE_SITE`, and the independent registry corpus ID.
2. **Extraction and LLM:** explicit enablement, provider/model/base URL, API-key precedence,
   temperature and browser headless mode.
3. **Retrieval and embeddings:** the Widget SQLite backend, database path, embedding model,
   device, batch size, normalization and vector dimension. The configured dimension must match
   the model output.
4. **Evidence and JSON-LD artifacts:** the separate extraction SQLite path and per-scenario artifact
   paths declared in `sources.toml`. The artifact path is intentionally not globally overrideable because
   it must remain bound to exactly one registry entry and corpus ID.

The example-owned `.env` is loaded by the provider helper with `override=True`, so values in
that file can override same-named inherited process environment variables. The helper also
recognizes Widget source-sync controls (`NLWEB_ENABLED`, `NLWEB_CONTENT_SYNC_ENABLED`,
`NLWEB_CONTENT_SYNC_ON_STARTUP`, `NLWEB_CONTENT_SYNC_INTERVAL_SECONDS`,
`NLWEB_CONTENT_SOURCES_FILE`, and `NLWEB_CONTENT_SYNC_STATE_FILE`) when those variables are
present in the process environment. Those controls determine whether the registered generated
source is actually synchronized. Consult `examples/external_hosted_sources/domain_site_extractor/README.md`
for the variable-by-variable table and defaults.

## Normal application versus explicit extraction

`app.py` follows the provider examples: build the Widget, start it, mount the existing FastAPI
integration, and close it at shutdown. `NLWEB_EXTERNAL_SOURCE_ENABLED=true` enables the custom
non-LLM factory path; `NLWEB_EXTERNAL_SOURCE_LLM_ENABLED=true` separately opts into an LLM path.
When both are true, the custom path and selected LLM backend execute separately and write
backend-specific JSON-LD artifacts with separate provenance manifests. Runtime source sync registers
each artifact independently; it does not merge or reconcile their records. The backend
must be explicitly configured: there is no code default. `scrapegraphai` and `scrapy_ollama` require
the LLM opt-in; `custom` requires the source opt-in and a factory path. If both flags are disabled,
extraction is skipped. If extraction fails, the app continues with existing sources and reports status
at `/external-source/status`; every enabled app restart can incur another LLM request.

Run the standalone extraction demo separately when you want to inspect the adapter/artifact flow
without starting an app or Widget:

```powershell
uv run python -m examples.external_hosted_sources.domain_site_extractor.demo
```

The command writes raw extraction evidence to its own SQLite database and writes an additive
JSON-LD `@graph` artifact under `generated/`. It does not call `widget.store.upsert()` or start
a Widget. This is intentional: the command showcases extraction output independently, while
`nlweb-sources.json` and the Widget's ordinary startup synchronization demonstrate ingestion.
The standalone demo writes the artifact but does not start a Widget; start/restart the app after
that command so the newly created artifact is picked up by the normal source-sync path. The checked-in authoritative source is never overwritten.

`query_demo.py` sends questions through `/ask`; `/mcp` is mounted by the same integration.
`NLWEB_EXTERNAL_SOURCE_EXTRACTOR_FACTORY=python.module:callable` can replace ScrapeGraphAI with a
consumer-owned drop-in factory returning an object with async `extract(request)`. The provided
BeautifulSoup implementation is an optional, non-LLM alternative; install it with
`uv sync --extra external-beautifulsoup` and enable `NLWEB_EXTERNAL_SOURCE_ENABLED=true`. The optional
configured-extraction pytest remains skipped unless explicitly configured and is not a substitute
for manually exercising the full extractor workflow.

## Lighter and future options

For lower cost or footprint, consumers can substitute the included deterministic BeautifulSoup
HTTP/parser implementation, Playwright without an LLM, Trafilatura, a CMS/API connector, or a
proprietary exporter using the same generic contract. `edgextract` is noted in the examples package manifest
as a possible future optional ontology-constrained local-first extraction adapter; it is not
part of this iteration or a required dependency.


### Corpus identity and standalone demo configuration

The runtime registry preserves each consumer-declared `site` corpus ID; it does not replace those IDs
with the hostname in `NLWEB_EXTERNAL_SOURCE_SITE`. When a real canonical URL is configured, an untouched
placeholder `content/inbox/domain.jsonld` is excluded by filename while the directory source stays enabled,
so unstructured authoritative files remain eligible for ingestion. Consumer-replaced authoritative JSON-LD
remains included. The runtime registry enables a generated scenario only when its mapped exact artifact exists.
The standalone command loads the example's own `.env` before resolving scenario URLs and validates the
scenario/prompt/registry/artifact mapping. It writes a provenance manifest beside the JSON-LD artifact.
After extraction, start/restart the app so normal source sync
picks up the generated artifact. Old rows in an existing retrieval database are not automatically
removed; use a disposable fresh database for clean QA.


### Authoritative inbox discovery and page-declared structured data

The authoritative `content/inbox/` registry entry uses `kind = "custom"` to route the directory through the example's provider loader. The loader discovers all supported files in the directory, parses JSON-LD directly, and normalizes unstructured PDF/PPTX/Markdown/text through the declared Haystack converter dependency. Do not narrow this source to `domain.jsonld`: directory discovery is the contract that permits consumer-provided unstructured authoritative domain content. The app generates `runtime/config/nlweb-sources.json` with absolute paths because that file is nested under `runtime/config`; the checked-in `nlweb-sources.json` remains portable with paths relative to the example root.

The app relies on `NLWEB_CONTENT_SYNC_ENABLED=true` and `NLWEB_CONTENT_SYNC_ON_STARTUP=true` and lets `Widget.startup()` perform the normal sync pass. It does not disable startup sync and then call `sync_sources(force=True)` separately. `/external-source/status` reads the recorded sync state instead of triggering a second ingestion pass.
The `authoritative_domain` registry entry includes `metadata.url` as the source-level fallback URL. The shared provider-widget builder passes that value to the ingestion helper; a suitable JSON-LD `url` takes precedence over `@id`, and URLs returned by the unstructured-document converter are preserved. When the fallback is a base path rather than a file URL, the artifact filename is appended. This fallback is not a declaration of public evidence; use the optional grounding manifest for that. Consumers should replace sample fallback mappings when adapting the corpus. The same metadata convention is supported by all examples using the shared provider-widget builder.

The deterministic BeautifulSoup adapter captures valid `application/ld+json` script payloads before stripping script markup from readable page text. It adds those records to the scenario's generated JSON-LD alongside the visible page summary. The LLM prompts explicitly require additive preservation of relevant source-provided JSON-LD. Extraction does not independently authenticate publisher claims.


### Choose an extraction backend explicitly

Set `NLWEB_EXTERNAL_SOURCE_EXTRACTOR_BACKEND` explicitly to `scrapegraphai` (remote LLM-backed extraction), `scrapy_ollama` (local Scrapy crawler plus local Ollama), `scrapy_transformers` (local Scrapy crawler with `Qwen/Qwen2.5-0.5B-Instruct` loaded directly by Hugging Face Transformers), or `custom` (consumer-supplied `NLWEB_EXTERNAL_SOURCE_EXTRACTOR_FACTORY`). If the variable is absent, extraction fails with a configuration error rather than assuming an LLM backend. The Scrapy/Ollama path requires `uv sync --extra local-scrapy-ollama` and a running Ollama service. The Transformers path requires `uv sync --extra local-scrapy-transformers`; it downloads/caches model weights from Hugging Face on first use and does not use Ollama. `scrapegraphai` may send fetched page content to the configured LLM provider; review data handling before enabling it. All backends remain opt-in through the existing extraction-enable flags: use `NLWEB_EXTERNAL_SOURCE_LLM_ENABLED=true` for `scrapegraphai`, `scrapy_ollama`, and `scrapy_transformers`, and `NLWEB_EXTERNAL_SOURCE_ENABLED=true` for `custom`. When both enable flags are true, both paths run independently and write separate artifacts with independent provenance; runtime registration keeps the results separate and performs no automatic merge.
