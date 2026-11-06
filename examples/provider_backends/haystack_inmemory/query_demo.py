import asyncio

import httpx


async def main() -> None:
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000", trust_env=False) as client:
        response = await client.post(
            "/ask",
            json={
                "query": {"text": "What does the AI search service provide?"},
                "prefer": {"mode": "list"},
            },
        )
        response.raise_for_status()
        print(response.json())


if __name__ == "__main__":
    asyncio.run(main())
