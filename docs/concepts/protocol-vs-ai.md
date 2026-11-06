# Protocol, visibility and AI

These examples demonstrate three progressively different things.

## 1. Protocol

The protocol-level tests prove that the widget exposes its intended HTTP surface, including `/ask` and `/mcp`.

No AI service is needed.

## 2. Visibility

The visibility demonstrations show how an independently running application can be reached through that protocol boundary.

They are useful for understanding what an external consumer can observe without introducing LLM variability.

## 3. AI consumer

AskAgent can be placed outside the application:

```text
application → nlweb-widget → HTTP → AskAgent → retrieval/ranking/generation
```

This adds an AI consumer to the demonstration. It does not change the widget's role.

Live LLM/network tests are therefore opt-in in this suite.
