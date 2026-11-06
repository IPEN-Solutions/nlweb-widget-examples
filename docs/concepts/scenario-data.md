# Scenario data

Every framework example uses a local `data.json` file so the domain projection is visible without reading application internals.

The files contain multiple realistic offerings rather than a single placeholder record. Each record carries a Schema.org-compatible `schema_object` and the text that the widget returns through the AI-facing protocol.

The examples use these profile combinations:

- **FastAPI retail:** AI digital transformation + ecommerce concepts.
- **Flask marketing:** AI-reach marketing + publisher/content concepts.
- **Django services:** professional services + generic business concepts.
- **Starlette catalog:** SaaS + documentation concepts.
- **stdlib directory:** local business + organization concepts.

The profile files are reusable starter material; `data.json` is the concrete scenario projection used by the runnable application.
