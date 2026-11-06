"""Generic external-source extraction boundary and optional ScrapeGraphAI adapter.

The Widget never depends on this module.  A consumer can replace the extractor
implementation with any other library while keeping the same extraction-to-widget
projection boundary demonstrated here.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urljoin, urlparse


@dataclass(frozen=True)
class ExtractionRequest:
    """Machine-readable extraction request supplied to an external extractor."""

    scenario: str
    sources: tuple[str, ...]
    prompt: str
    schema_hint: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractionResult:
    """Normalized extractor output retained independently of the Widget."""

    scenario: str
    sources: tuple[str, ...]
    payload: Mapping[str, Any]
    extractor: str
    llm_provider: str | None = None
    model: str | None = None


class ExternalSourceExtractor(Protocol):
    """Small provider-neutral contract implemented by any acquisition library."""

    async def extract(self, request: ExtractionRequest) -> ExtractionResult:
        """Extract domain information from the requested external source(s)."""


@dataclass(frozen=True)
class ScrapeGraphAIConfig:
    """Configuration for the optional LLM-backed ScrapeGraphAI implementation."""

    model: str
    api_key: str | None
    base_url: str | None
    provider: str
    temperature: float = 0.0
    headless: bool = True
    allowed_hosts: frozenset[str] = frozenset()

    @classmethod
    def from_environment(cls) -> ScrapeGraphAIConfig:
        provider = os.getenv("NLWEB_EXTERNAL_SOURCE_LLM_PROVIDER", "openrouter")
        model = os.getenv("NLWEB_EXTERNAL_SOURCE_LLM_MODEL", "openai/gpt-4o-mini")
        api_key = os.getenv("NLWEB_EXTERNAL_SOURCE_LLM_API_KEY")
        if not api_key and provider.lower() == "openrouter":
            api_key = os.getenv("OPENROUTER_API_KEY")
        base_url = os.getenv(
            "NLWEB_EXTERNAL_SOURCE_LLM_BASE_URL",
            "https://openrouter.ai/api/v1" if provider.lower() == "openrouter" else "",
        )
        allowed_hosts = frozenset(
            item.strip().lower()
            for item in os.getenv("NLWEB_EXTERNAL_SOURCE_ALLOWED_HOSTS", "").split(",")
            if item.strip()
        )
        return cls(
            model=model,
            api_key=api_key or None,
            base_url=base_url or None,
            provider=provider,
            temperature=float(os.getenv("NLWEB_EXTERNAL_SOURCE_LLM_TEMPERATURE", "0")),
            headless=os.getenv("NLWEB_EXTERNAL_SOURCE_HEADLESS", "true").lower()
            in {"1", "true", "yes", "on"},
            allowed_hosts=allowed_hosts,
        )


class ScrapeGraphAIExtractor:
    """Optional ScrapeGraphAI implementation of the generic extractor contract.

    Importing this class does not import ScrapeGraphAI or invoke an LLM.  The
    dependency and network/token boundary is crossed only when ``extract`` is
    explicitly called.
    """

    def __init__(self, config: ScrapeGraphAIConfig | None = None) -> None:
        self.config = config or ScrapeGraphAIConfig.from_environment()

    async def extract(self, request: ExtractionRequest) -> ExtractionResult:
        if not request.sources:
            raise ValueError("At least one external source is required")
        self._validate_sources(request.sources)
        graph = self._build_graph(request)
        payload = await asyncio.to_thread(graph.run)
        if not isinstance(payload, Mapping):
            raise TypeError(f"ScrapeGraphAI returned {type(payload)!r}; expected a mapping")
        return ExtractionResult(
            scenario=request.scenario,
            sources=request.sources,
            payload=dict(payload),
            extractor="scrapegraphai",
            llm_provider=self.config.provider,
            model=self.config.model,
        )

    def _validate_sources(self, sources: Sequence[str]) -> None:
        if not self.config.allowed_hosts:
            raise RuntimeError(
                "No external-source host allowlist is configured. Set "
                "NLWEB_EXTERNAL_SOURCE_ALLOWED_HOSTS before explicit extraction."
            )
        for source in sources:
            parsed = urlparse(source)
            hostname = (parsed.hostname or "").lower()
            if parsed.scheme not in {"http", "https"} or hostname not in self.config.allowed_hosts:
                raise ValueError(
                    f"External source {source!r} is outside the configured host allowlist"
                )

    def _build_graph(self, request: ExtractionRequest) -> Any:
        try:
            from scrapegraphai.graphs import SmartScraperGraph, SmartScraperMultiGraph
        except ImportError as exc:
            raise RuntimeError(
                "ScrapeGraphAI is optional. Install the examples extra before explicit extraction: "
                "uv sync --extra external-scrapegraphai"
            ) from exc

        llm: dict[str, Any] = {
            "model": self.config.model,
            "temperature": self.config.temperature,
            "format": "json",
        }
        if self.config.api_key:
            llm["api_key"] = self.config.api_key
        if self.config.base_url:
            llm["base_url"] = self.config.base_url

        graph_config = {
            "llm": llm,
            "headless": self.config.headless,
            "verbose": False,
        }
        prompt = request.prompt
        if request.schema_hint:
            prompt = (
                f"{prompt}\n\nReturn data matching this JSON shape:\n{dict(request.schema_hint)!r}"
            )

        if len(request.sources) == 1:
            return SmartScraperGraph(prompt=prompt, source=request.sources[0], config=graph_config)
        return SmartScraperMultiGraph(
            prompt=prompt,
            source=list(request.sources),
            config=graph_config,
        )


class BeautifulSoupExtractor:
    """Lightweight deterministic HTML extractor; no LLM or browser is used.

    It fetches each explicitly configured URL and preserves page title, description,
    headings, and readable text as a WebPage record. Unlike ScrapeGraphAI, it does not
    infer services/entities or follow links automatically.
    """

    def __init__(self, allowed_hosts: frozenset[str] | None = None) -> None:
        self.allowed_hosts = (
            allowed_hosts
            if allowed_hosts is not None
            else ScrapeGraphAIConfig.from_environment().allowed_hosts
        )

    async def extract(self, request: ExtractionRequest) -> ExtractionResult:
        if not request.sources:
            raise ValueError("At least one external source is required")
        if not self.allowed_hosts:
            raise RuntimeError(
                "No external-source host allowlist is configured. Set "
                "NLWEB_EXTERNAL_SOURCE_ALLOWED_HOSTS before explicit extraction."
            )
        try:
            import httpx
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError(
                "The BeautifulSoup extractor is optional. Install it with "
                "`uv sync --extra external-beautifulsoup`."
            ) from exc

        records: list[dict[str, Any]] = []
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=20.0,
            headers={"User-Agent": "nlweb-widget-examples-external-source/1.0"},
        ) as client:
            for source in request.sources:
                current_url = source
                for redirect_count in range(6):
                    parsed = urlparse(current_url)
                    hostname = (parsed.hostname or "").lower()
                    if parsed.scheme not in {"http", "https"} or hostname not in self.allowed_hosts:
                        raise ValueError(
                            f"External source or redirect {current_url!r} is outside the "
                            "configured host allowlist"
                        )
                    response = await client.get(current_url)
                    if response.is_redirect:
                        if redirect_count == 5:
                            raise RuntimeError(f"Too many redirects while fetching {source!r}")
                        location = response.headers.get("location")
                        if not location:
                            raise RuntimeError(
                                f"Redirect from {current_url!r} has no Location header"
                            )
                        current_url = urljoin(current_url, location)
                        continue
                    response.raise_for_status()
                    break
                soup = BeautifulSoup(response.text, "html.parser")
                # JSON-LD is structured domain evidence, not executable page markup. Capture
                # valid application/ld+json payloads before removing scripts from visible text.
                structured_records: list[dict[str, Any]] = []
                jsonld_type = re.compile(r"^\s*application/ld\+json\s*$", re.I)
                for script in soup.find_all("script", attrs={"type": jsonld_type}):
                    raw_jsonld = script.string or script.get_text()
                    if not raw_jsonld or len(raw_jsonld) > 1_000_000:
                        continue
                    try:
                        structured_payload = json.loads(raw_jsonld)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    structured_records.extend(_jsonld_objects(structured_payload))
                    if len(structured_records) >= 100:
                        structured_records = structured_records[:100]
                        break
                for node in soup(["script", "style", "noscript", "svg", "nav", "footer"]):
                    node.decompose()
                title = (soup.title.get_text(" ", strip=True) if soup.title else "") or source
                description_node = soup.find("meta", attrs={"name": "description"})
                description = (
                    str(description_node.get("content", "")).strip() if description_node else ""
                )
                headings = [
                    node.get_text(" ", strip=True)
                    for node in soup.find_all(["h1", "h2", "h3"])
                    if node.get_text(" ", strip=True)
                ]
                main = soup.find("main") or soup.find("article") or soup.body or soup
                text = " ".join(main.stripped_strings)
                readable_content = "\n".join(
                    part
                    for part in [description, "Headings: " + " | ".join(headings), text]
                    if part
                )
                records.append(
                    {
                        "@type": "WebPage",
                        "name": title[:300],
                        # The current structured-source adapter indexes `description` as the
                        # document content, so include the readable page text there too.
                        "description": readable_content[:12000],
                        "url": str(response.url),
                        "text": text[:12000],
                        "headings": headings[:80],
                    }
                )
                # Keep the page summary first for stable consumers, then retain structured
                # records supplied by the page. Their schema fields are persisted as JSON-LD.
                records.extend(structured_records)
        return ExtractionResult(
            scenario=request.scenario,
            sources=request.sources,
            payload={"records": records},
            extractor="beautifulsoup",
            llm_provider=None,
            model=None,
        )


def _jsonld_objects(payload: Any) -> list[dict[str, Any]]:
    """Flatten valid JSON-LD objects/graphs without requiring @id or url fields."""
    if isinstance(payload, list):
        values = payload
    elif isinstance(payload, Mapping):
        graph = payload.get("@graph")
        values = graph if isinstance(graph, list) else [payload]
    else:
        return []
    return [dict(item) for item in values if isinstance(item, Mapping)][:100]


def build_beautifulsoup_extractor() -> BeautifulSoupExtractor:
    """Factory target for NLWEB_EXTERNAL_SOURCE_EXTRACTOR_FACTORY."""
    return BeautifulSoupExtractor()


def configured_extractor_from_environment() -> ExternalSourceExtractor:
    """Build the opted-in extractor, allowing a consumer-owned drop-in implementation.

    ``NLWEB_EXTERNAL_SOURCE_EXTRACTOR_FACTORY`` may name ``module:callable`` when the
    explicitly selected backend is ``custom``. The callable must return an object implementing
    the async ``extract(request)`` contract. Without a factory, only the explicitly selected
    ``scrapegraphai`` backend is handled here, and it still requires the LLM opt-in.
    """
    llm_enabled = os.getenv("NLWEB_EXTERNAL_SOURCE_LLM_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    source_enabled = os.getenv("NLWEB_EXTERNAL_SOURCE_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    factory_path = os.getenv("NLWEB_EXTERNAL_SOURCE_EXTRACTOR_FACTORY", "").strip()
    backend = os.getenv("NLWEB_EXTERNAL_SOURCE_EXTRACTOR_BACKEND", "").strip().casefold()
    if not (source_enabled or llm_enabled):
        raise RuntimeError(
            "External LLM extraction is disabled. Set NLWEB_EXTERNAL_SOURCE_LLM_ENABLED=true "
            "for an explicitly selected LLM backend, or NLWEB_EXTERNAL_SOURCE_ENABLED=true "
            "for a custom extractor."
        )
    if not backend:
        raise RuntimeError(
            "NLWEB_EXTERNAL_SOURCE_EXTRACTOR_BACKEND must be explicitly configured when extraction is enabled."
        )
    if not factory_path:
        if backend != "scrapegraphai":
            raise RuntimeError(
                f"Backend {backend!r} requires its dedicated adapter or a configured custom extractor factory."
            )
        if not llm_enabled:
            raise RuntimeError(
                "External LLM extraction is disabled. Set NLWEB_EXTERNAL_SOURCE_LLM_ENABLED=true "
                "to opt into the explicitly selected scrapegraphai backend."
            )
        return ScrapeGraphAIExtractor()
    if backend != "custom":
        raise RuntimeError(
            "NLWEB_EXTERNAL_SOURCE_EXTRACTOR_FACTORY is only used with "
            "NLWEB_EXTERNAL_SOURCE_EXTRACTOR_BACKEND=custom."
        )
    if not source_enabled:
        raise RuntimeError(
            "A custom external-source extractor requires NLWEB_EXTERNAL_SOURCE_ENABLED=true."
        )
    if ":" not in factory_path:
        raise ValueError(
            "NLWEB_EXTERNAL_SOURCE_EXTRACTOR_FACTORY must use 'python.module:callable' syntax"
        )
    module_name, attribute_name = factory_path.split(":", 1)
    if not module_name or not attribute_name:
        raise ValueError(
            "NLWEB_EXTERNAL_SOURCE_EXTRACTOR_FACTORY must use 'python.module:callable' syntax"
        )
    factory = getattr(importlib.import_module(module_name), attribute_name)
    extractor = factory()
    if not callable(getattr(extractor, "extract", None)):
        raise TypeError("Configured external-source extractor must provide extract(request)")
    return extractor
