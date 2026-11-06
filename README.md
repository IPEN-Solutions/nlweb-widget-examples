# NLWeb Widget Examples 0.1.8

This approved release adds a local-first cross-lingual retrieval benchmark while preserving the existing examples and the separately versioned Widget runtime. See [the cumulative changelog](CHANGELOG.md) for the release-to-release changes.

The [local-first cross-lingual retrieval benchmark](examples/embedding_benchmark/README.md) owns its scenario catalogue (`examples/embedding_benchmark/benchmark_scenarios.toml`), corpus/query registry, benchmark-scoped settings, and SQLite + sqlite-vec indexes. Run it by scenario name; predefined templates compare every non-empty combination of three Sentence Transformers models, the configured local Ollama Nomic model, or Sentence Transformers vs Ollama for a compatible Nomic model family. Each scenario produces a comparative matrix and a provisional metric-based recommendation. MTEB public-task evaluation remains disabled by default; no hosted inference APIs are called by the local benchmark.

## Family boundary

- `nlweb-widget` 0.9.12 is the separately approved, immutable runtime baseline.
- This repository demonstrates consumer integrations and optional source-ingestion patterns; it does not redefine the Widget protocol.
- ScrapeGraphAI remains available as an optional hosted-LLM extraction path. Scrapy + Ollama and Scrapy + Hugging Face Transformers are separate local-first alternatives.
- File/object inbox ingestion supports `nlweb-evidence-manifest.json`; the optional CouchDB source instead reads provenance attributes from each stored document.

## Install and test

This repository is a runnable examples and test workspace, **not a publishable Python package**. Its `pyproject.toml` intentionally has no `[build-system]` section; `tool.uv.package = false` tells uv not to build or install the examples workspace itself. The separately maintained `nlweb-widget` runtime remains a normal dependency.

```powershell
uv sync --dev
uv run pytest
```

Optional extras/groups are installed only when the selected example needs them, for example `uv sync --extra local-scrapy-ollama`, `uv sync --extra local-scrapy-transformers`, `uv sync --extra remote-storage`, or `uv sync --group benchmark-nomic-v2-moe` for the Nomic Embed v2 MoE benchmark model. The Nomic group only adds `einops`; `uv sync --group benchmark-huggingface-downloads` opts into Hugging Face Xet download acceleration, and the MegaBlocks GPU optimization is documented but disabled by default in `pyproject.toml`; enable its commented dependency group only on compatible NVIDIA GPU/CUDA + PyTorch systems with native build tools, never on CPU-only/low-resource systems. The predefined Nomic Sentence Transformers scenario explicitly enables custom model code, so review the model repository and pin a trusted revision in `benchmark_scenarios.toml` before running it. Scenario runtime parameters are owned by the TOML catalogue; `.env.example` is limited to operational paths and the remote-Ollama security gate, while separate `.env.mteb.example` settings apply only to the optional MTEB runner. MTEB is disabled by default and requires a deliberate local opt-in as documented in the benchmark guide.

For development against a sibling Widget checkout, use `uv add --editable ../nlweb_widget`. The examples workspace itself is intentionally non-package (`tool.uv.package = false`) and has no build backend; uv should resolve/build the Widget dependency, not this examples repository.

## Domain-site extraction options

See the [local Scrapy + Ollama guide](docs/guides/local-scrapy-ollama.md), [local Scrapy + Hugging Face Transformers guide](docs/guides/local-scrapy-transformers.md), [remote-storage guide](docs/guides/remote-storage.md), and [CouchDB document-store guide](docs/guides/document-store-couchdb.md). These examples keep resource use, credentials and source-of-truth boundaries explicit. The direct Transformers/Qwen example includes a conservative dual-core CPU / 4 GB RAM profile; see its guide before running it alongside embedding or indexing workloads. Both Scrapy LLM examples retain per-page audit rows in the separate `runtime/extracted-content.sqlite3` database, with backend/provider/model identity; see their guides for the Ollama and Transformers details. Each example registry exposes local disk, S3-compatible remote storage, and CouchDB as independent source modes. The optional per-example CouchDB initializer seeds the sample inbox once, validates the evidence manifest, and refuses to overwrite consumer-edited documents. The source registry `name` controls retrieval-ID namespacing and stale-record cleanup for that source only.

## Workspace and local mutation evidence

This repository is a runnable examples/test workspace, not a separately publishable Python distribution (`tool.uv.package = false`). The examples workspace does not pin a Python patch version: use the compatible Python version installed and managed at the system or environment level, as constrained by `requires-python` in `pyproject.toml`.

Private iteration manifests, candidate reports, QA evidence, integrity records, and build inventories belong in the root `package-mutation-evidence/` folder. The folder is Git-ignored and excluded from release archives. It is not part of consumer documentation or runtime functionality. Functional evidence manifests inside individual examples remain alongside those examples because they are runtime data contracts.

### Source identity and freshness

The source registry `name` is the stable identity of a source. The Examples loader namespaces retrieval document IDs by that name, so complementary local, remote, and CouchDB sources can coexist even when artifact names match. On a successful sync, current records from that source are upserted and previously indexed IDs tracked for that same source but absent from the current result are deleted. Other sources are not deleted or overridden. Do not reuse a registry name for a different logical source; treat renames as migrations. A failed ingestion does not run stale-record cleanup.


### All three source modes in each example registry

Each example registry exposes local disk, S3-compatible remote storage, and CouchDB document-store source entries. Local/scenario sources are enabled for the runnable baseline; remote and CouchDB entries are disabled by default and can be enabled after configuration. They are complementary sources, not a precedence chain. Each `name` is a distinct identity and receives its own retrieval-ID namespace. Successful sync replaces that source's current projection and removes stale IDs from that source only.

### Remote object-storage source contract

The S3-compatible source uses `location` as its sole bucket/prefix address, with `s3://${NLWEB_REMOTE_STORAGE_BUCKET}/` selecting the bucket root in the example. There is no `metadata.remote_location` duplicate and no `NLWEB_REMOTE_STORAGE_OPTIONS_JSON` fallback setting. The per-source `remote_storage_options` configure the filesystem client (`key`, `secret`, `prefix`, and `client_kwargs` containing `region_name` and `endpoint_url`). `prefix` defaults to an empty string (bucket root) and can be changed per registry entry to isolate separate object folders. Bare endpoint hostnames are normalized to HTTPS. Ingestion enumerates and reads objects; it does not upload them. The immutable Widget 0.9.12 runtime is unchanged; the examples adapter privately recovers the raw URI from the checked-in registry if the runtime normalizes it.

The external-hosted example may add `metadata.excluded_filenames` to its generated runtime registry when a real domain is configured and the local inbox still contains the untouched placeholder `domain.jsonld`. This is runtime-generated behavior, not a consumer template setting: it excludes only that placeholder file from local-folder ingestion. It is not added for remote object storage, and it does not exclude consumer artifacts.

### CouchDB registry and local HTTP behavior

The CouchDB registry `location` is `couchdb+${NLWEB_COUCHDB_URL}/${NLWEB_COUCHDB_DATABASE}` and `metadata.document_store_options.database` also uses `${NLWEB_COUCHDB_DATABASE}`; the redundant `metadata.document_store_location` is absent. Both endpoint and database are consumer-configurable, with no hard-coded CouchDB host in registry templates. `remote_storage_options` appears only on the S3-compatible source; unused empty option objects and the unconsumed `enabled_when_artifact_exists` metadata flag have been removed.

The `remote-storage` extra installs both `fsspec` and `s3fs`, so S3-compatible locations work after `uv sync --extra remote-storage`. Every `.env.example` includes blank `NLWEB_REMOTE_STORAGE_ACCESS_KEY`, `NLWEB_REMOTE_STORAGE_SECRET_KEY`, and `NLWEB_REMOTE_STORAGE_REGION` assignments because the S3 registry template references these names. Keep them blank while remote storage is disabled; populate them in your private `.env` when enabling that source. Every template also includes blank `NLWEB_DOCUMENT_STORE_USERNAME` and `NLWEB_DOCUMENT_STORE_PASSWORD` assignments; leave both blank for unauthenticated local CouchDB, or set both in the private `.env` when CouchDB authentication is enabled. Never commit real credentials.

CouchDB initializers and example HTTP clients bypass environment proxies for loopback endpoints (`localhost`, `127.0.0.0/8`, `::1`). Requests to non-loopback endpoints continue to honor configured proxy environment variables. This avoids a local proxy returning 403 for a local CouchDB service without disabling proxy use for remote services.


### Extraction opt-in and PDF parsing notes

`NLWEB_EXTERNAL_SOURCE_EXTRACTOR_BACKEND` must be explicitly configured when extraction runs; code does not silently default to an LLM backend. `scrapegraphai` and `scrapy_ollama` require `NLWEB_EXTERNAL_SOURCE_LLM_ENABLED=true`. `custom` requires `NLWEB_EXTERNAL_SOURCE_ENABLED=true` and a configured `NLWEB_EXTERNAL_SOURCE_EXTRACTOR_FACTORY`. When both enable flags are true, the custom non-LLM extractor and selected LLM backend execute as separate paths. Each writes its own JSON-LD artifact and provenance manifest, and the runtime source registry registers them independently; their records are never automatically merged. Scrapy/Ollama preserves source JSON-LD and scraped page text even when local Ollama is unavailable; only model-derived claims are omitted. Source ingestion now supports DOCX directly and reports/skips artifact-manifest mismatches per artifact while continuing healthy artifacts. `fonttools` is included to improve PDF parsing of embedded CFF Type1 font encodings.

## Private mutation evidence

Keep iteration candidates, supporting reports, QA evidence, and build manifests under `package-mutation-evidence/` at the workspace root. This local-only directory is Git-ignored and must be excluded from release archives. Public README/docs and functional runtime evidence manifests stay in their normal locations.

Embedding benchmark note: scenario definitions control whether Sentence Transformers may execute custom model repository code. Review the repository and pin a trusted revision before running a scenario with `trust_remote_code = true`; see `examples/embedding_benchmark/README.md`.
