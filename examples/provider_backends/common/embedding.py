"""Sentence Transformers embedding provider used by provider examples."""

import asyncio
from collections.abc import Sequence
from typing import Any

from .config import get_config


class SentenceTransformerEmbeddingProvider:
    """Async adapter matching the Widget embedding-provider contract."""

    def __init__(
        self,
        model_name: str,
        *,
        device: str = "cpu",
        batch_size: int = 1,
        normalize_embeddings: bool = True,
    ) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except (ImportError, OSError) as exc:
            raise RuntimeError(
                "Provider examples could not load Sentence Transformers or its native "
                "dependencies; run `uv sync` to apply the declared dependency constraints."
            ) from exc
        self.model_name = model_name
        self.batch_size = batch_size
        self.normalize_embeddings = normalize_embeddings
        self._model = SentenceTransformer(model_name, device=device)

    @property
    def model(self) -> Any:
        """Return the underlying SentenceTransformer model for Haystack components."""
        return self._model

    @property
    def dimensions(self) -> int:
        """Return the embedding dimension produced by the configured model."""
        dimension = self._model.get_sentence_embedding_dimension()
        if dimension is None:
            raise RuntimeError("Embedding model did not expose its vector dimension")
        return int(dimension)

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch without blocking the event loop."""
        values = list(texts)
        if not values:
            return []
        return await asyncio.to_thread(self._encode, values)

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=self.normalize_embeddings,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vectors.tolist()


def build_embedding_provider() -> SentenceTransformerEmbeddingProvider:
    """Build the configured local Sentence Transformers provider."""
    config = get_config()
    return SentenceTransformerEmbeddingProvider(
        config.embedding_model,
        device=config.embedding_device,
        batch_size=config.embedding_batch_size,
        normalize_embeddings=config.embedding_normalize,
    )


def embedding_metadata(provider: Any) -> dict[str, Any]:
    """Return safe metadata for example output and diagnostics."""
    return {"model": provider.model_name, "dimensions": provider.dimensions}
