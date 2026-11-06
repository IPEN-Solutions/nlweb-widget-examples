"""Query the hosted-source example through the same /ask endpoint as provider examples."""

from __future__ import annotations

import asyncio
import os

import httpx


async def ask(client: httpx.AsyncClient, question: str) -> None:
    response = await client.post(
        "/ask",
        json={"query": {"text": question}, "prefer": {"mode": "list"}},
    )
    response.raise_for_status()
    print(f"\nQUESTION: {question}\n{response.json()}")


async def main() -> None:
    base_url = os.getenv("NLWEB_EXTERNAL_SOURCE_BASE_URL", "http://127.0.0.1:8000")
    hostname = (httpx.URL(base_url).host or "").casefold()
    trust_env = hostname not in {"localhost", "127.0.0.1", "::1"} and not hostname.startswith(
        "127."
    )
    external_question = os.getenv(
        "NLWEB_EXTERNAL_SOURCE_QUERY",
        "What information from the hosted company source is available?",
    )
    existing_question = os.getenv(
        "NLWEB_EXTERNAL_SOURCE_EXISTING_QUERY",
        "What does the AI search service provide?",
    )
    async with httpx.AsyncClient(base_url=base_url, timeout=30, trust_env=trust_env) as client:
        status_response = await client.get("/external-source/status")
        status_response.raise_for_status()
        print(f"EXTERNAL SOURCE STATUS: {status_response.json()}")
        await ask(client, existing_question)
        await ask(client, external_question)


if __name__ == "__main__":
    asyncio.run(main())
