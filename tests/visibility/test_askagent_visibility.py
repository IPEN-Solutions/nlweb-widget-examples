import os

import httpx
import pytest


@pytest.mark.asyncio
async def test_independent_askagent_can_reach_domain() -> None:
    askagent_url = os.getenv("ASKAGENT_URL")
    _domain_url = os.getenv("NLWEB_DOMAIN_URL", "http://127.0.0.1:8000")
    corpus_site = os.getenv("NLWEB_CORPUS_SITE", "retail.example")
    if not askagent_url:
        pytest.skip("ASKAGENT_URL is not configured; optional external-agent test")

    async with httpx.AsyncClient(timeout=20) as client:
        health = await client.get(f"{askagent_url.rstrip('/')}/ask")
        assert health.status_code in {200, 400, 405}
        response = await client.post(
            f"{askagent_url.rstrip('/')}/ask",
            json={
                "query": {
                    "text": "What services does the company offer retailers?",
                    "site": corpus_site,
                },
                "prefer": {"streaming": False},
            },
        )
        assert response.status_code < 500, response.text
        assert "results" in response.json()
