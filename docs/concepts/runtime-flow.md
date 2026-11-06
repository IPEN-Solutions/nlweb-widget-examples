# Runtime flow

A typical request travels through these layers:

1. An external client sends an NLWeb request.
2. The framework receives the HTTP request.
3. The framework adapter validates/maps the request into the widget protocol model.
4. The widget invokes the configured retrieval/domain projection mechanism.
5. The widget returns a structured NLWeb response.
6. The framework serializes that response over HTTP.

For the lightweight examples, the flow can be tested without a remote LLM.

## Why real HTTP tests matter

The integration tests deliberately exercise the HTTP boundary rather than inspecting framework internals. This verifies what an actual consumer can observe: paths, methods, request shapes and response behavior.
