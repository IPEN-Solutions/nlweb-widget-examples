# Local-first Scrapy + Ollama domain extraction

This optional alternative sits alongside the existing ScrapeGraphAI adapter and the separate [Hugging Face Transformers variant](local-scrapy-transformers.md). It is designed for constrained local development: Scrapy fetches one configured page at a time, and Ollama runs a small local model such as `qwen2.5:0.5b`.

## Install

```powershell
uv sync --extra local-scrapy-ollama
ollama pull qwen2.5:0.5b
```

Ollama must be running locally. The example defaults to `http://127.0.0.1:11434/api/chat`, model `qwen2.5:0.5b`, a 2,048-token context, a short text input and a 90-second request timeout. Adjust `NLWEB_LOCAL_OLLAMA_MODEL`, `NLWEB_LOCAL_OLLAMA_URL`, and `NLWEB_LOCAL_OLLAMA_TIMEOUT_SECONDS` in the example `.env`.

## Run

```powershell
uv run --extra local-scrapy-ollama python -m examples.external_hosted_sources.domain_site_extractor.local_scrapy_ollama https://your-domain.example/ --allowed-hosts your-domain.example --max-pages 5 --depth-limit 2
```

The command writes `generated/local-scrapy-ollama.jsonld`, preserves the raw page items in `runtime/local-scrapy-ollama-items.jsonl`, and persists each page item to `runtime/extracted-content.sqlite3`. Each SQLite row records the scenario, configured start URL, raw page payload, `extractor=scrapy_ollama`, provider `ollama`, and model ID. The audit database is separate from the Widget retrieval database and keeps this backend’s outcome distinct from Transformers or custom extraction. The command summary includes `persisted_items` and `extraction_db`. Use `--scenario` and `--db-path` to override their defaults, or set `NLWEB_EXTERNAL_SOURCE_SCENARIO` and `NLWEB_EXTERNAL_SOURCE_EXTRACTION_DB`. JSON-LD script records are parsed directly; the model is only used to extract claims from visible page text. Model-generated claims require a verbatim evidence quote present in the page text and the exact current page URL. Output claims carry `nlwebEvidenceStatus: unverified-extraction`. This is an evidence-preserving MVP, not a completeness, truth, or authenticity guarantee. JavaScript-rendered content is not rendered by Scrapy.

## Remote filesystem credentials/options

`remote_storage_options` is a per-source object passed to `fsspec.core.url_to_fs(url, **kwargs)`. Use `${ENV_VAR}` placeholders for individual values; configuration is defined by the source registry entry, without a second JSON fallback object. Provider option names differ by backend; keep secrets in environment variables/secret stores and never commit them.


Local HTTPX requests to loopback endpoints bypass environment proxies to avoid local proxy interference. HTTPX calls to non-loopback endpoints continue to honor proxy settings. The optional Ollama HTTP request uses its configured URL and is not routed through the HTTPX client.


If Ollama is unavailable or its response fails, the crawler still emits the page's valid JSON-LD and scraped page text; only model-derived claims are omitted. The callback remains synchronous for compatibility across supported Scrapy versions, and the demo intentionally crawls one page at a time.
