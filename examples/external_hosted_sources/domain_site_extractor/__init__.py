"""Generic external-source adapter contract with an optional ScrapeGraphAI implementation."""

from .adapter import (
    ExternalSourceExtractor,
    ExtractionRequest,
    ExtractionResult,
    ScrapeGraphAIExtractor,
)
from .jsonld import extraction_to_jsonld
from .storage import ExtractionStore

__all__ = [
    "ExtractionRequest",
    "ExtractionResult",
    "ExternalSourceExtractor",
    "ScrapeGraphAIExtractor",
    "ExtractionStore",
    "extraction_to_jsonld",
]
