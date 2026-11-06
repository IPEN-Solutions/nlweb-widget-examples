"""Optional OpenRouter answer synthesis for provider demonstrations."""

from typing import Any

from .config import get_config


class OpenRouterAnswerer:
    """Generate an answer from Widget /ask results through OpenRouter."""

    def __init__(self) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("OpenRouter examples require the openai package") from exc
        import os

        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY is required for answer synthesis")
        config = get_config()
        self._client = OpenAI(api_key=api_key, base_url=config.openrouter_base_url)
        self._model = config.llm_model
        self._temperature = config.llm_temperature

    def answer(self, query: str, results: list[dict[str, Any]]) -> str:
        context = "\n\n".join(
            f"[{item.get('name')}] {item.get('description', '')}" for item in results
        )
        response = self._client.chat.completions.create(
            model=self._model,
            temperature=self._temperature,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Answer only from the supplied domain context. "
                        "If the context does not support the answer, say so. "
                        "This is a company-specific retrieval demonstration."
                    ),
                },
                {"role": "user", "content": f"Question: {query}\n\nContext:\n{context}"},
            ],
        )
        return response.choices[0].message.content or "No answer returned."
