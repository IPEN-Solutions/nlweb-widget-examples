"""Exercise the provider example through its real /ask HTTP boundary."""

# Allow direct `python examples/.../query_demo.py` execution from the repository root.
if __package__ in {None, ""}:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


import json
import os

import httpx

from examples.provider_backends.common.openrouter import OpenRouterAnswerer

QUESTIONS = (
    "What AI engineering services does IPEN provide to manufacturers?",
    "I need a technology partner for AI-enabled modernization of a manufacturing operation. What capabilities are available?",
)


def main() -> None:
    base_url = os.getenv("PROVIDER_EXAMPLE_BASE_URL", "http://127.0.0.1:8000")
    hostname = (httpx.URL(base_url).host or "").casefold()
    trust_env = hostname not in {"localhost", "127.0.0.1", "::1"} and not hostname.startswith(
        "127."
    )
    with httpx.Client(base_url=base_url, timeout=30.0, trust_env=trust_env) as client:
        for question in QUESTIONS:
            response = client.post("/ask", json={"query": {"text": question}})
            response.raise_for_status()
            payload = response.json()
            print(
                json.dumps({"question": question, "results": payload.get("results", [])}, indent=2)
            )
            if os.getenv("OPENROUTER_API_KEY") and payload.get("results"):
                try:
                    print(OpenRouterAnswerer().answer(question, payload["results"]))
                except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                    print(
                        f"[warning] OpenRouter answer synthesis failed; retrieval succeeded: {exc}"
                    )


if __name__ == "__main__":
    main()
