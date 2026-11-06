from __future__ import annotations

import json
from types import SimpleNamespace

from examples.external_hosted_sources.domain_site_extractor.local_scrapy_transformers import (
    _as_jsonld_graph,
    _decode_json_object,
    _validate_claims,
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
                '{"@context":"https://schema.org","@type":"Organization",'
                '"name":"Example","@id":"https://example.test/#org"}'
            ]
        )


def test_jsonld_is_preserved_without_model_reconstruction():
    records = parse_jsonld_scripts(FakeResponse())
    assert len(records) == 1
    assert records[0]["raw"]["@id"] == "https://example.test/#org"
    assert records[0]["raw"]["@type"] == "Organization"


def test_transformers_claims_require_exact_quote_and_source_url():
    text = "We provide industrial AI consulting and product design."
    valid = {
        "kind": "service",
        "name": "Industrial AI consulting",
        "description": "Consulting service",
        "evidence_quote": "We provide industrial AI consulting",
        "source_url": "https://example.test/",
    }
    decoded = {
        "claims": [
            valid,
            {**valid, "name": "Invented", "evidence_quote": "We do everything"},
            {**valid, "source_url": "https://other.test/"},
        ]
    }
    result = _validate_claims(decoded, text, "https://example.test/")
    assert len(result) == 1
    assert result[0]["name"] == "Industrial AI consulting"


def test_json_decoder_accepts_fenced_json():
    assert _decode_json_object('```json\n{"claims": []}\n```') == {"claims": []}


def test_artifact_is_backend_specific_and_keeps_jsonld_and_page_text(tmp_path):
    items_path = tmp_path / "items.jsonl"
    output_path = tmp_path / "result.jsonld"
    items_path.write_text(
        json.dumps(
            {
                "page_url": "https://example.test/",
                "title": "Example",
                "page_text": "We provide industrial AI consulting.",
                "jsonld_records": [
                    {
                        "raw": {"@type": "Organization", "name": "Example"},
                        "source_url": "https://example.test/",
                    }
                ],
                "claims": [
                    {
                        "kind": "service",
                        "name": "Industrial AI consulting",
                        "description": None,
                        "evidence_quote": "We provide industrial AI consulting.",
                        "source_url": "https://example.test/",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    summary = _as_jsonld_graph(items_path, output_path)
    graph = json.loads(output_path.read_text(encoding="utf-8"))["@graph"]
    assert summary["preserved_jsonld_records"] == 1
    assert graph[0]["@type"] == "Organization"
    assert graph[1]["@type"] == "WebPage"
    assert graph[2]["nlwebExtractionMethod"] == "huggingface-transformers-text-extraction"
    assert graph[2]["nlwebEvidenceStatus"] == "unverified-extraction"


def test_callback_preserves_static_evidence_when_transformers_fails(monkeypatch):
    from examples.external_hosted_sources.domain_site_extractor import (
        local_scrapy_transformers as module,
    )

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
                    ['{"@context":"https://schema.org","@type":"Product","name":"Example product"}']
                )
            if "//title" in query:
                return Selector(["Example services"])
            if "//body" in query:
                return Selector(["Industrial AI consulting services"])
            return Selector([])

        def css(self, query):
            return Selector([])

    def fail_model(*args, **kwargs):
        raise RuntimeError("local model load failed")

    monkeypatch.setattr(module, "_transformers_extract", fail_model)
    test_logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    monkeypatch.setattr(
        module.LocalTransformersDomainSpider,
        "logger",
        property(lambda self: test_logger),
        raising=False,
    )
    spider = object.__new__(module.LocalTransformersDomainSpider)
    spider.allowed_domains = ["example.test"]
    spider.model = "test-model"

    items = list(spider.parse(Response()))
    assert len(items) == 1
    assert items[0]["jsonld_records"][0]["raw"]["@type"] == "Product"
    assert items[0]["page_text"] == "Industrial AI consulting services"
    assert items[0]["claims"] == []


def test_resource_constrained_defaults_are_explicit():
    from examples.external_hosted_sources.domain_site_extractor import (
        local_scrapy_transformers as module,
    )

    assert module.DEFAULT_MODEL == "Qwen/Qwen2.5-0.5B-Instruct"
    assert module.DEFAULT_MAX_NEW_TOKENS == 96
    assert module.DEFAULT_MAX_INPUT_TOKENS == 1024
    assert module.DEFAULT_MAX_PAGE_CHARS == 2000
    assert module.DEFAULT_MAX_PAGES == 3
    assert module.DEFAULT_DEPTH_LIMIT == 1
    assert module.DEFAULT_TORCH_THREADS == 2


def test_transformers_model_load_requests_low_cpu_memory(monkeypatch):
    from examples.external_hosted_sources.domain_site_extractor import (
        local_scrapy_transformers as module,
    )

    calls = {}

    class FakeTokenizer:
        @classmethod
        def from_pretrained(cls, model_name):
            calls["tokenizer"] = model_name
            return object()

    class FakeModelInstance:
        def to(self, device):
            calls["device"] = device
            return self

        def eval(self):
            calls["eval"] = True

    class FakeModel:
        @classmethod
        def from_pretrained(cls, model_name, **kwargs):
            calls["model"] = model_name
            calls["kwargs"] = kwargs
            return FakeModelInstance()

    import sys
    from types import SimpleNamespace

    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(AutoTokenizer=FakeTokenizer, AutoModelForCausalLM=FakeModel),
    )
    module._MODEL_CACHE.clear()
    module._load_transformers_model("test-model", "cpu")
    assert calls["kwargs"] == {"low_cpu_mem_usage": True}
    assert calls["device"] == "cpu"
    assert calls["eval"] is True
    module._MODEL_CACHE.clear()


def test_transformers_items_are_audited_in_extraction_sqlite(tmp_path):
    from examples.external_hosted_sources.domain_site_extractor.local_scrapy_transformers import (
        _persist_items_to_sqlite,
    )
    from examples.external_hosted_sources.domain_site_extractor.storage import ExtractionStore

    items_path = tmp_path / "items.jsonl"
    database_path = tmp_path / "extracted-content.sqlite3"
    item = {
        "page_url": "https://example.test/",
        "title": "Example",
        "page_text": "Evidence text",
        "jsonld_records": [{"raw": {"@type": "Organization", "name": "Example"}}],
        "claims": [],
    }
    items_path.write_text(json.dumps(item) + "\n", encoding="utf-8")

    count = _persist_items_to_sqlite(
        items_path,
        database_path,
        scenario="company_website",
        source_url="https://example.test/",
        model_name="Qwen/Qwen2.5-0.5B-Instruct",
    )

    assert count == 1
    stored = list(ExtractionStore(database_path).iter_results())
    assert len(stored) == 1
    assert stored[0]["extractor"] == "scrapy_transformers"
    assert stored[0]["llm_provider"] == "huggingface-transformers"
    assert stored[0]["model"] == "Qwen/Qwen2.5-0.5B-Instruct"
    assert stored[0]["payload"]["page_text"] == "Evidence text"
