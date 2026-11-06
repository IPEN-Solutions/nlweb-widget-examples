# Framework guide

Choose the example that matches your application framework, then compare it with the stdlib example to see what is framework-specific and what belongs to the widget core.

| Example | Main lesson |
|---|---|
| FastAPI | Modern ASGI application integration |
| Flask | WSGI application integration |
| Django | Integration into a larger application framework |
| Starlette | Lightweight ASGI integration |
| stdlib HTTP | Framework-independent HTTP boundary |

The framework adapters are intentionally thin. Their job is to connect the framework's HTTP machinery to the same widget protocol operations.
