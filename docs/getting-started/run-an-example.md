# Run an example

## Prepare the environment

```powershell
uv sync --dev
uv run pytest
```

Optional integrations require their corresponding extras and external services. For example, install `uv sync --extra local-scrapy-ollama` for the Ollama-backed crawler, `uv sync --extra local-scrapy-transformers` for the direct Hugging Face Transformers crawler, or `uv sync --extra remote-storage` for fsspec-backed object storage.

## Run FastAPI

```powershell
uv run uvicorn examples.fastapi_retail.app:app --host 127.0.0.1 --port 8000
```

## Run a provider-backed example

Copy the provider-owned `.env.example` to `.env`, then start that provider's app. For example:

```powershell
Copy-Item examples/provider_backends/neo4j/.env.example examples/provider_backends/neo4j/.env
uv run uvicorn examples.provider_backends.neo4j.app:app --host 127.0.0.1 --port 8000 --env-file examples/provider_backends/neo4j/.env
```

## Explore domain-site extraction

Choose the existing ScrapeGraphAI path or the optional local Scrapy + Ollama path. For already-curated documents, use the local/object-storage inbox or the optional CouchDB document-store registry entry. See the guides for credential setup and evidence preservation.
