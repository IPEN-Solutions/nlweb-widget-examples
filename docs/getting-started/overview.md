# Overview

## What this repository is

`nlweb-widget-examples` is a standalone reference suite. It is not part of the production `nlweb-widget` runtime package and is not intended to be installed as a production dependency.

The suite contains complete, runnable applications for FastAPI, Flask, Django, Starlette and the Python standard-library HTTP server. Each demonstrates the same architectural idea through a different application boundary.

## What the examples teach

The examples are designed to show that an application can keep its existing domain model, services and data stores while exposing an NLWeb-compatible interface.

```text
existing application
        │
        ▼
framework integration
        │
        ▼
nlweb-widget core
        │
        ├── POST /ask
        └── POST /mcp
        │
        ▼
external NLWeb consumer
```

The example code is intentionally small enough to read, but the documentation explains the runtime behavior and the decisions behind the layout.

## What is optional

AskAgent is an optional external consumer used to demonstrate AI-facing visibility. It is not required for protocol tests or for running the framework examples. The AskAgent UI is also optional. Docker and nginx are not prerequisites for the lightweight API workflow.
