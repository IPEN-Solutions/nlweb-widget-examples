# FastAPI

The FastAPI example is the primary full-featured reference application.

Path: `examples/fastapi_retail/`

It demonstrates:

- an existing FastAPI application;
- a small domain dataset;
- `NLWebWidget` as the protocol-facing component;
- real HTTP access to `/ask` and `/mcp`;
- an offline visibility/agent demonstration.

## Consumer takeaway

If your application is already FastAPI-based, you do not need to replace its routing or domain architecture. The widget is mounted as an integration boundary around the application.

Study this example first if you want the most direct path from a conventional Python API to an NLWeb-compatible surface.

The scenario data is in `examples/fastapi_retail/data.json` and demonstrates AI transformation, customer experience, commerce modernization and agent/knowledge services.
