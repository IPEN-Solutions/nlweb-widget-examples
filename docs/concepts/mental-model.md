# Mental model

Think of `nlweb-widget` as an **adapter at the edge of an existing domain application**.

It is not an AI database, an LLM, or a replacement for the application's domain layer.

```text
                    authoritative
                    application data
                           │
                           ▼
                    your domain logic
                           │
                           ▼
                    nlweb-widget
                    protocol boundary
                           │
                 ┌─────────┴─────────┐
                 ▼                   ▼
               /ask                 /mcp
                 │                   │
                 └─────────┬─────────┘
                           ▼
                  agents / AI search
```

The widget can expose information derived from the application's authoritative domain content without requiring that content to be moved into a separate AI knowledge base.

## Why the examples are framework-specific

The core protocol behavior is framework-neutral, but applications expose HTTP through different lifecycle and routing models. The examples show the thin adapter appropriate to each framework while keeping protocol logic in the widget core.
