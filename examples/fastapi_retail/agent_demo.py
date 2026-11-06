"""Deterministic AI-search/MCP visibility companion for the FastAPI example."""

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi.testclient import TestClient

from examples.fastapi_retail.app import app

QUESTION = "What services does the company offer retailers?"


def main() -> None:
    with TestClient(app) as client:
        tools = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        tools.raise_for_status()
        ask = client.post("/ask", json={"query": {"text": QUESTION}})
        ask.raise_for_status()

    response = ask.json()
    urls = [item["url"] for item in response.get("results", [])]
    report = {
        "domain": "https://retail.example",
        "question": QUESTION,
        "askagent_like_tool_discovery": bool(tools.json().get("result", {}).get("tools")),
        "indexed_urls": urls,
        "mock_visibility_rank": 1 if urls else None,
        "note": "Deterministic proof-of-concept; real agents/crawlers own discovery and ranking.",
    }
    print("[agent] external-agent visibility companion started")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
