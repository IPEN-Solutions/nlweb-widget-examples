# AskAgent visibility testing

AskAgent is an **optional external consumer**, not a required part of the default examples suite. The default workspace configuration keeps live AskAgent entries commented so a clean checkout does not accidentally activate external services or provider credentials.

To opt in, initialize the required values in your environment and run:

```powershell
uv run pytest tests/visibility/test_askagent_visibility.py
```

The test crosses the real HTTP boundary to the configured `ASKAGENT_URL`. Without the required live configuration, it is intentionally skipped.

## What this establishes

The visibility test establishes the external HTTP boundary and expected response shape. It does **not** establish LLM answer quality, retrieval completeness, ranking quality, or production deployment readiness.

This separation is intentional: protocol/integration correctness is validated independently from an external AI consumer's model, ranking, embedding, and deployment choices.

The query `site` value is a retrieval corpus ID, not the URL used to reach the Widget. Set `NLWEB_CORPUS_SITE` to the `site` value declared in the target example's `nlweb-sources.json` (the retail example defaults to `retail.example`). `NLWEB_DOMAIN_URL` remains the HTTP endpoint address.
