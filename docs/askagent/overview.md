# AskAgent

AskAgent is an optional external consumer used by this reference suite to demonstrate an AI-facing workflow.

It is important to separate the two systems:

```text
nlweb-widget-examples application
            │
            ▼
       nlweb-widget
            │ HTTP
            ▼
        AskAgent
```

The application-side tests do not require AskAgent. AskAgent becomes useful when you want to observe a more complete AI retrieval/generation path.

The suite deliberately keeps the provider configuration policy separate from the widget package. Current upstream provider wiring should be verified against a pinned AskAgent revision before treating any particular embedding or LLM provider combination as a supported integration contract.
