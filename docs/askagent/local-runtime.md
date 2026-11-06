# Local AskAgent topology

The lightweight local topology is:

```text
127.0.0.1:8000  Example domain application
       │
       │ NLWeb HTTP
       ▼
127.0.0.1:8001  AskAgent API          optional
       │
       ▼
    LLM / retrieval

127.0.0.1:8002  AskAgent UI          optional
```

The UI is not required for API testing. Docker and nginx are not prerequisites for the lightweight backend workflow documented by this suite.

The exact upstream AskAgent provider configuration should be pinned and verified before enabling live AI testing. The examples repository intentionally does not silently claim provider compatibility that has not been verified against a specific upstream revision.
