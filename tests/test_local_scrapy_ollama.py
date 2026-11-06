from __future__ import annotations

import json
from types import SimpleNamespace

from examples.external_hosted_sources.domain_site_extractor.local_scrapy_ollama import (
    _as_jsonld_graph,
    parse_jsonld_scripts,
)


class FakeSelector:
    def __init__(self, values):
        self.values = values

    def getall(self):
        return self.values


class FakeResponse:
    url = "https://example.test/"

    def xpath(self, query):
        return FakeSelector(
            [
                '{"@context":"https://schema.org","@type":"Organization","name":"Example","@id":"https://example.test/#org"}'
            ]
        )


def test_jsonld_script_is_preserved_directly():
    records = parse_jsonld_scripts(FakeResponse())
    assert len(records) == 1
    assert records[0]["raw"]["@id"] == "https://example.test/#org"
    assert records[0]["raw"]["@type"] == "Organization"


def test_artifact_writer_keeps_jsonld_and_marks_text_claims_unverified(tmp_path):
    items = tmp_path / "items.jsonl"
    items.write_text(
        json.dumps(
            {
                "page_url": "https://example.test/",
                "jsonld_records": [
                    {
                        "raw": {
                            "@type": "Organization",
                            "name": "Example",
                            "@id": "https://example.test/#org",
                        },
                        "source_url": "https://example.test/",
                    }
                ],
                "claims": [
                    {
                        "kind": "service",
                        "name": "Integration",
                        "description": "Service description",
                        "evidence_quote": "We provide integration services.",
                        "source_url": "https://example.test/",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "result.jsonld"
    summary = _as_jsonld_graph(items, output)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert summary["preserved_jsonld_records"] == 1
    assert payload["@graph"][0]["@id"] == "https://example.test/#org"
    assert payload["@graph"][1]["nlwebEvidenceStatus"] == "unverified-extraction"
    assert payload["@graph"][1]["nlwebEvidenceQuote"] == "We provide integration services."


def test_scraped_page_text_is_preserved_when_jsonld_and_llm_claims_are_absent(tmp_path):
    items = tmp_path / "items.jsonl"
    output = tmp_path / "site.jsonld"
    items.write_text(
        json.dumps(
            {
                "page_url": "https://example.test/",
                "title": "Example",
                "page_text": "The company provides consulting services.",
                "jsonld_records": [],
                "claims": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = _as_jsonld_graph(items, output)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert result["text_claim_records"] == 0
    assert payload["@graph"][0]["@type"] == "WebPage"
    assert payload["@graph"][0]["text"] == "The company provides consulting services."


def test_scrapy_callback_preserves_jsonld_when_ollama_fails(monkeypatch) -> None:
    from examples.external_hosted_sources.domain_site_extractor import local_scrapy_ollama as module

    class Selector:
        def __init__(self, values):
            self.values = values

        def getall(self):
            return self.values

    class Response:
        url = "https://example.test/"

        def xpath(self, query):
            if "script[" in query:
                return Selector(
                    [
                        '{"@context":"https://schema.org","@type":"Product","name":"Marketing Automation"}'
                    ]
                )
            if "//title" in query:
                return Selector(["Example services"])
            if "//body" in query:
                return Selector(["Marketing automation services"])
            return Selector([])

        def css(self, query):
            return Selector([])

    def fail_ollama(*args, **kwargs):
        raise ConnectionError("local Ollama is unavailable")

    monkeypatch.setattr(module, "_ollama_extract", fail_ollama)
    # Scrapy exposes logger as a read-only property; when Scrapy is not installed,
    # the module deliberately falls back to object. Patch the class property for this
    # isolated callback test instead of assigning to the spider instance.
    test_logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    monkeypatch.setattr(
        module.LocalOllamaDomainSpider,
        "logger",
        property(lambda self: test_logger),
        raising=False,
    )
    spider = object.__new__(module.LocalOllamaDomainSpider)
    spider.allowed_domains = ["example.test"]
    spider.model = "test-model"
    spider.ollama_url = "http://127.0.0.1:11434/api/chat"
    items = list(spider.parse(Response()))
    assert len(items) == 1
    assert items[0]["jsonld_records"][0]["raw"]["@type"] == "Product"
    assert items[0]["page_text"] == "Marketing automation services"
    assert items[0]["claims"] == []


def test_ollama_page_items_are_persisted_to_extraction_sqlite(tmp_path):
    from examples.external_hosted_sources.domain_site_extractor.local_scrapy_ollama import (
        _persist_items_to_sqlite,
    )
    from examples.external_hosted_sources.domain_site_extractor.storage import ExtractionStore

    items = tmp_path / "ollama-items.jsonl"
    items.write_text(
        json.dumps(
            {
                "page_url": "https://example.test/about",
                "title": "About Example",
                "page_text": "Example provides consulting.",
                "jsonld_records": [],
                "claims": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    database = tmp_path / "runtime" / "extracted-content.sqlite3"
    count = _persist_items_to_sqlite(
        items,
        database,
        scenario="ollama-audit-test",
        source_url="https://example.test/",
        model_name="qwen2.5:0.5b-test",
    )
    rows = list(ExtractionStore(database).iter_results())
    assert count == 1
    assert len(rows) == 1
    assert rows[0]["scenario"] == "ollama-audit-test"
    assert rows[0]["extractor"] == "scrapy_ollama"
    assert rows[0]["llm_provider"] == "ollama"
    assert rows[0]["model"] == "qwen2.5:0.5b-test"
    assert rows[0]["payload"]["page_url"] == "https://example.test/about"
    assert rows[0]["payload"]["page_text"] == "Example provides consulting."
