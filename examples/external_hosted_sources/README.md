# External hosted-domain sources

These examples show how consumers can extend the Widget's authoritative-domain-data
projection toolbox with hosted sources without modifying the Widget itself.

The adapter is deliberately generic. ScrapeGraphAI is one optional implementation of the
`ExternalSourceExtractor` contract; other acquisition/extraction tools can implement the same
boundary.

The ScrapeGraphAI example separates explicit acquisition from normal app serving:

1. `python -m examples.external_hosted_sources.domain_site_extractor.demo` writes extraction evidence
   to a separate SQLite database and additive JSON-LD artifacts under `generated/`.
2. The checked-in `nlweb-sources.json` registers the scenario sources; at runtime, fresh
   backend-specific artifacts are registered as separate source entries with distinct identities.
3. Starting/restarting `app.py` uses normal Widget source synchronization to ingest each
   enabled source independently and exposes them through `/ask` and `/mcp`.

The FastAPI app never launches a browser or calls an LLM during startup. ScrapeGraphAI is an
optional examples extra. To run the browser-backed extraction path, install the extra and
manually install Chromium:

```powershell
uv sync --extra external-scrapegraphai
uv run playwright install chromium
```

See `examples/external_hosted_sources/domain_site_extractor/README.md` for the complete environment
variable reference, `sources.toml`/prompt/source-registry relationships, and run instructions.


For localhost CouchDB and local Widget query endpoints, example HTTPX clients bypass configured environment proxies. Non-loopback endpoints continue to use configured proxies. The `remote-storage` extra includes `s3fs` as well as `fsspec` for S3-compatible URLs.
