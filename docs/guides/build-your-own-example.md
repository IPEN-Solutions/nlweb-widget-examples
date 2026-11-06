# Build your own example

Use an existing framework example as a template, but preserve the boundaries.

1. Start with the application's normal domain model.
2. Choose the widget store/projection mechanism appropriate to the example.
3. Attach the framework adapter.
4. Expose the NLWeb protocol surface through the application's HTTP server.
5. Test the boundary through HTTP.
6. Add an offline visibility demonstration before adding live AI dependencies.

Keep AI/consumer infrastructure outside the core application unless it is genuinely part of the application's architecture.

A good new example should explain both **how to run it** and **what architectural lesson it demonstrates**.


## Adding an externally hosted source

When domain information lives outside the application, add a custom adapter rather than modifying the Widget. The adapter should acquire and normalize the external source, preserve provenance, and hand the result to the same Widget content boundary used by the existing examples. See [External hosted-domain sources](external-hosted-sources.md) for the generic contract and optional ScrapeGraphAI implementation.
