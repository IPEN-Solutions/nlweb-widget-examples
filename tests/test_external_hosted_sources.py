import asyncio
import hashlib
import json
import os
from pathlib import Path

import pytest

from examples.external_hosted_sources.domain_site_extractor.adapter import (
    ExtractionRequest,
    ExtractionResult,
    ScrapeGraphAIConfig,
    ScrapeGraphAIExtractor,
    configured_extractor_from_environment,
)
from examples.external_hosted_sources.domain_site_extractor.jsonld import extraction_to_jsonld
from examples.external_hosted_sources.domain_site_extractor.storage import ExtractionStore


def test_all_example_registries_use_explicit_corpus_ids() -> None:
    root = Path("examples")
    registries = sorted(root.rglob("nlweb-sources.json"))
    assert registries
    for registry_path in registries:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
        names = [source["name"] for source in payload["sources"]]
        assert len(names) == len(set(names)), registry_path
        for source in payload["sources"]:
            assert isinstance(source.get("site"), str) and source["site"].strip(), registry_path
            assert source["site"] != "default", registry_path
            if source.get("name") == "authoritative_domain_document_store":
                assert (
                    source["location"] == "couchdb+${NLWEB_COUCHDB_URL}/${NLWEB_COUCHDB_DATABASE}"
                ), registry_path
                assert "document_store_location" not in source.get("metadata", {}), registry_path
            if source.get("name") == "authoritative_domain_remote_storage":
                assert source["remote_storage_options"].get("prefix") == "", registry_path


def test_every_environment_template_contains_provider_placeholders_in_topic_groups() -> None:
    required = {
        "NLWEB_REMOTE_STORAGE_ACCESS_KEY",
        "NLWEB_REMOTE_STORAGE_SECRET_KEY",
        "NLWEB_REMOTE_STORAGE_REGION",
        "NLWEB_REMOTE_STORAGE_BUCKET",
        "NLWEB_REMOTE_STORAGE_ENDPOINT_URL",
        "NLWEB_DOCUMENT_STORE_USERNAME",
        "NLWEB_DOCUMENT_STORE_PASSWORD",
        "NLWEB_COUCHDB_URL",
        "NLWEB_COUCHDB_DATABASE",
    }
    templates = sorted(Path(".").rglob(".env.example"))
    assert templates
    for template in templates:
        # The benchmark template intentionally contains only NLWEB_BENCHMARK_*
        # settings and must remain independent of provider example configuration.
        if "embedding_benchmark" in template.parts:
            continue
        content = template.read_text(encoding="utf-8")
        keys = {
            line.strip().split("=", 1)[0]
            for line in content.splitlines()
            if "=" in line and not line.lstrip().startswith("#")
        }
        assert required.issubset(keys), template
        lines = content.splitlines()
        remote_positions = [
            next(i for i, line in enumerate(lines) if line.startswith(key))
            for key in (
                "NLWEB_REMOTE_STORAGE_BUCKET=",
                "NLWEB_REMOTE_STORAGE_ENDPOINT_URL=",
                "NLWEB_REMOTE_STORAGE_ACCESS_KEY=",
                "NLWEB_REMOTE_STORAGE_SECRET_KEY=",
                "NLWEB_REMOTE_STORAGE_REGION=",
            )
        ]
        assert remote_positions == sorted(remote_positions), template
        couch_positions = [
            next(i for i, line in enumerate(lines) if line.startswith(key))
            for key in (
                "NLWEB_COUCHDB_URL=",
                "NLWEB_COUCHDB_DATABASE=",
                "NLWEB_DOCUMENT_STORE_TIMEOUT_SECONDS=",
                "NLWEB_DOCUMENT_STORE_USERNAME=",
                "NLWEB_DOCUMENT_STORE_PASSWORD=",
            )
        ]
        assert couch_positions == sorted(couch_positions), template


def test_generic_extractor_contract_is_provider_neutral() -> None:
    request = ExtractionRequest(
        scenario="company_website",
        sources=("https://company.example/",),
        prompt="Extract first-party services.",
        schema_hint={"records": [{"@type": "Service"}]},
    )
    result = ExtractionResult(
        scenario=request.scenario,
        sources=request.sources,
        payload={"records": [{"@type": "Service", "name": "AI consulting"}]},
        extractor="test-double",
    )
    assert result.sources == request.sources
    assert result.extractor == "test-double"


def test_llm_extraction_is_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NLWEB_EXTERNAL_SOURCE_LLM_ENABLED", raising=False)
    with pytest.raises(RuntimeError, match="External LLM extraction is disabled"):
        configured_extractor_from_environment()


def test_extraction_requires_explicit_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    import examples.external_hosted_sources.domain_site_extractor.demo as demo

    # The demo normally loads its local .env with override=True. Keep this unit
    # test deterministic and make the monkeypatched environment authoritative.
    monkeypatch.setattr(demo, "_load_example_env", lambda: None)
    extract_to_artifact = demo.extract_to_artifact

    monkeypatch.setenv("NLWEB_EXTERNAL_SOURCE_COMPANY_WEBSITE_URL", "https://company.example/")
    monkeypatch.setenv("NLWEB_EXTERNAL_SOURCE_ENABLED", "false")
    monkeypatch.setenv("NLWEB_EXTERNAL_SOURCE_LLM_ENABLED", "true")
    monkeypatch.delenv("NLWEB_EXTERNAL_SOURCE_EXTRACTOR_BACKEND", raising=False)
    with pytest.raises(
        RuntimeError, match="NLWEB_EXTERNAL_SOURCE_EXTRACTOR_BACKEND must be explicitly configured"
    ):
        asyncio.run(extract_to_artifact("company_website"))


def test_both_extraction_flags_keep_separate_registered_artifacts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import examples.external_hosted_sources.domain_site_extractor.demo as demo

    monkeypatch.setattr(demo, "_load_example_env", lambda: None)
    monkeypatch.setattr(demo, "ROOT", tmp_path)
    monkeypatch.setattr(
        demo,
        "_scenario",
        lambda name: {
            "artifact": "generated/test.jsonld",
            "prompt": "Extract evidence.",
            "schema_hint": {},
            "urls": ["https://company.example/"],
            "site": "company.example",
        },
    )
    monkeypatch.setenv("NLWEB_EXTERNAL_SOURCE_ENABLED", "true")
    monkeypatch.setenv("NLWEB_EXTERNAL_SOURCE_LLM_ENABLED", "true")
    monkeypatch.setenv("NLWEB_EXTERNAL_SOURCE_EXTRACTOR_BACKEND", "scrapegraphai")
    monkeypatch.setenv("NLWEB_EXTERNAL_SOURCE_EXTRACTOR_FACTORY", "fake_module:make_extractor")

    async def fake_single(name, *, artifact_override=None, retrieval_site=None):
        artifact_override.parent.mkdir(parents=True, exist_ok=True)
        backend = os.environ["NLWEB_EXTERNAL_SOURCE_EXTRACTOR_BACKEND"]
        artifact_override.write_text(
            json.dumps(
                {"@context": "https://schema.org", "@graph": [{"@type": "Thing", "name": backend}]}
            ),
            encoding="utf-8",
        )
        manifest = {
            "schema_version": 1,
            "scenario": name,
            "backend": backend,
            "sources": ["https://company.example/"],
            "site": "company.example",
            "retrieval_site": retrieval_site or "company.example",
            "canonical_site_url": "https://external-source.example/",
            "prompt_sha256": "test-prompt",
            "artifact_sha256": hashlib.sha256(artifact_override.read_bytes()).hexdigest(),
        }
        manifest_path = artifact_override.with_name(artifact_override.name + ".manifest.json")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return {
            "backend": backend,
            "records": 1,
            "jsonld": str(artifact_override),
            "provenance": str(manifest_path),
        }

    monkeypatch.setattr(demo, "_extract_single_to_artifact", fake_single)
    result = asyncio.run(demo.extract_to_artifact("company_website"))
    custom_path = Path(result["artifacts"]["custom"])
    llm_path = Path(result["artifacts"]["scrapegraphai"])
    assert custom_path != llm_path
    assert json.loads(custom_path.read_text(encoding="utf-8"))["@graph"][0]["name"] == "custom"
    assert json.loads(llm_path.read_text(encoding="utf-8"))["@graph"][0]["name"] == "scrapegraphai"
    assert Path(str(custom_path) + ".manifest.json").is_file()
    assert Path(str(llm_path) + ".manifest.json").is_file()
    assert not (tmp_path / "generated" / "test.jsonld").exists()
    assert "merged" not in result["message"].lower()


def test_scrapegraphai_requires_explicit_source_host_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("NLWEB_EXTERNAL_SOURCE_ALLOWED_HOSTS", raising=False)
    extractor = ScrapeGraphAIExtractor()
    request = ExtractionRequest(
        scenario="company_website",
        sources=("https://company.example/",),
        prompt="Extract the company name.",
    )
    with pytest.raises(RuntimeError, match="host allowlist"):
        asyncio.run(extractor.extract(request))


def test_scrapegraphai_config_defaults_to_injectable_openrouter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("NLWEB_EXTERNAL_SOURCE_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("NLWEB_EXTERNAL_SOURCE_LLM_MODEL", raising=False)
    config = ScrapeGraphAIConfig.from_environment()
    assert config.provider == "openrouter"
    assert config.model == "openai/gpt-4o-mini"
    assert config.base_url == "https://openrouter.ai/api/v1"
    assert config.api_key == "test-key"


def test_extractor_factory_can_load_a_consumer_owned_drop_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    module = types.ModuleType("test_custom_external_extractor")

    class CustomExtractor:
        async def extract(self, request: ExtractionRequest) -> ExtractionResult:
            return ExtractionResult(
                scenario=request.scenario,
                sources=request.sources,
                payload={"records": []},
                extractor="custom-test",
            )

    module.make_extractor = lambda: CustomExtractor()
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setenv("NLWEB_EXTERNAL_SOURCE_LLM_ENABLED", "true")
    monkeypatch.setenv("NLWEB_EXTERNAL_SOURCE_EXTRACTOR_BACKEND", "custom")
    monkeypatch.setenv("NLWEB_EXTERNAL_SOURCE_ENABLED", "true")
    monkeypatch.setenv(
        "NLWEB_EXTERNAL_SOURCE_EXTRACTOR_FACTORY",
        "test_custom_external_extractor:make_extractor",
    )
    extractor = configured_extractor_from_environment()
    assert isinstance(extractor, CustomExtractor)


def test_non_llm_factory_can_be_enabled_without_llm_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    module = types.ModuleType("test_non_llm_external_extractor")

    class LocalExtractor:
        async def extract(self, request: ExtractionRequest) -> ExtractionResult:
            return ExtractionResult(
                scenario=request.scenario,
                sources=request.sources,
                payload={"records": [{"@type": "WebPage", "name": "Local result"}]},
                extractor="local-test",
            )

    module.make_extractor = lambda: LocalExtractor()
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setenv("NLWEB_EXTERNAL_SOURCE_ENABLED", "true")
    monkeypatch.setenv("NLWEB_EXTERNAL_SOURCE_LLM_ENABLED", "false")
    monkeypatch.setenv("NLWEB_EXTERNAL_SOURCE_EXTRACTOR_BACKEND", "custom")
    monkeypatch.setenv(
        "NLWEB_EXTERNAL_SOURCE_EXTRACTOR_FACTORY",
        "test_non_llm_external_extractor:make_extractor",
    )
    extractor = configured_extractor_from_environment()
    assert isinstance(extractor, LocalExtractor)


def test_non_llm_extractor_has_explicit_optional_factory() -> None:
    from examples.external_hosted_sources.domain_site_extractor.adapter import (
        build_beautifulsoup_extractor,
    )

    extractor = build_beautifulsoup_extractor()
    assert callable(extractor.extract)


def test_beautifulsoup_extractor_normalizes_page_without_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("bs4")
    import httpx

    from examples.external_hosted_sources.domain_site_extractor.adapter import (
        BeautifulSoupExtractor,
    )

    class FakeResponse:
        text = (
            "<html><head><title>Local Services</title>"
            "<meta name='description' content='Independent page summary'>"
            '<script type=\'application/ld+json\'>{"@context":"https://schema.org",'
            '"@type":"Service","name":"Declared AI service",'
            '"description":"Structured capability declaration"}</script></head>'
            "<body><main><h1>AI transformation services</h1>"
            "<p>Unique deterministic retrieval phrase.</p></main></body></html>"
        )
        url = "https://company.example/services"
        is_redirect = False

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str) -> FakeResponse:
            assert url == "https://company.example/services"
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    monkeypatch.setenv("NLWEB_EXTERNAL_SOURCE_ALLOWED_HOSTS", "company.example")
    extractor = BeautifulSoupExtractor()
    result = asyncio.run(
        extractor.extract(
            ExtractionRequest(
                scenario="company_website",
                sources=("https://company.example/services",),
                prompt="Preserve readable page content.",
            )
        )
    )
    record = result.payload["records"][0]
    assert result.extractor == "beautifulsoup"
    assert record["name"] == "Local Services"
    assert "Unique deterministic retrieval phrase" in record["description"]
    service_records = [item for item in result.payload["records"] if item.get("@type") == "Service"]
    assert len(service_records) == 1
    assert service_records[0]["name"] == "Declared AI service"
    assert service_records[0]["description"] == "Structured capability declaration"
    assert result.llm_provider is None


def test_extraction_store_is_separate_and_round_trippable(tmp_path: Path) -> None:
    path = tmp_path / "extracted.sqlite3"
    store = ExtractionStore(path)
    result = ExtractionResult(
        scenario="company_knowledge_base",
        sources=("https://kb.example/",),
        payload={"records": [{"@type": "Article", "headline": "FAQ"}]},
        extractor="test-double",
    )
    row_id = store.save("Extract knowledge-base facts.", result)
    rows = list(store.iter_results())
    assert row_id == 1
    assert rows[0]["scenario"] == "company_knowledge_base"
    assert rows[0]["payload"]["records"][0]["headline"] == "FAQ"


def test_extraction_can_be_projected_to_additive_jsonld() -> None:
    records = extraction_to_jsonld(
        {
            "scenario": "product_service_catalog",
            "payload": {
                "records": [
                    {
                        "@type": "Product",
                        "name": "Platform",
                        "url": "https://example.test/p",
                    }
                ]
            },
        },
        site="https://example.test/",
    )
    assert records == [
        {
            "@context": "https://schema.org",
            "@type": "Product",
            "@id": "https://example.test/p",
            "isPartOf": "https://example.test/",
            "name": "Platform",
            "url": "https://example.test/p",
        }
    ]


def test_prompt_and_scenario_resources_are_machine_readable() -> None:
    import tomllib

    root = Path("examples/external_hosted_sources/domain_site_extractor")
    prompts = tomllib.loads(
        (root / "prompts/extraction_scenarios.toml").read_text(encoding="utf-8")
    )
    sources = tomllib.loads((root / "sources.toml").read_text(encoding="utf-8"))
    expected = {
        "company_website",
        "company_knowledge_base",
        "company_portal",
        "product_service_catalog",
        "company_newsroom",
    }
    assert expected == set(prompts["scenarios"])
    assert expected == set(sources["sources"])


def test_example_resources_exist_without_importing_runtime_dependencies() -> None:
    root = Path("examples/external_hosted_sources/domain_site_extractor")
    assert (root / "prompts/extraction_scenarios.toml").is_file()
    assert (root / "sources.toml").is_file()

    # Keep test discovery independent of optional/runtime widget dependencies. Importing
    # the demo is unnecessary to verify these static resources.
    demo_source = (root / "demo.py").read_text(encoding="utf-8")
    assert "def extract_to_artifact(" in demo_source
    assert "widget.store.upsert" not in demo_source
    assert 'if __name__ == "__main__":' in demo_source


@pytest.mark.skipif(
    os.getenv("NLWEB_EXTERNAL_SOURCE_LLM_ENABLED", "false").lower()
    not in {"1", "true", "yes", "on"},
    reason="Explicit external LLM extraction is disabled by default",
)
def test_configured_external_llm_extraction() -> None:
    source = os.getenv("NLWEB_EXTERNAL_SOURCE_COMPANY_WEBSITE_URL")
    if not source:
        pytest.skip("No hosted source URL configured")
    extractor = configured_extractor_from_environment()
    result = asyncio.run(
        extractor.extract(
            ExtractionRequest(
                scenario="company_website",
                sources=(source,),
                prompt="Extract the company name and a concise description.",
                schema_hint={"records": [{"@type": "Organization", "name": "", "description": ""}]},
            )
        )
    )
    assert result.payload


def test_fastapi_example_mounts_endpoints_and_handles_optional_extraction() -> None:
    # Static inspection avoids initializing the embedding provider during test discovery.
    app_source = Path("examples/external_hosted_sources/domain_site_extractor/app.py").read_text(
        encoding="utf-8"
    )
    assert "app = FastAPI(" in app_source
    assert "await widget.startup()" in app_source
    assert "await widget.close()" in app_source
    assert "mount_fastapi_nlweb(app, widget)" in app_source
    assert "await extract_to_artifact()" in app_source
    assert "NLWEB_EXTERNAL_SOURCE_ENABLED" in app_source
    assert "await widget.sync_sources(force=True)" not in app_source
    assert '"mode": "widget.startup"' in app_source
    assert 'content_sync_on_startup": False' not in app_source
    assert "ingestion_failed" in app_source
    assert '"/external-source/status"' in app_source
    assert "prepare_runtime_source_registry" in app_source
    demo_source = Path("examples/external_hosted_sources/domain_site_extractor/demo.py").read_text(
        encoding="utf-8"
    )
    assert "load_dotenv(_ENV_FILE, override=True)" in demo_source


def test_example_env_explicitly_enables_widget_and_startup_source_sync() -> None:
    env_path = Path("examples/external_hosted_sources/domain_site_extractor/.env.example")
    values = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, value = stripped.split("=", 1)
            values[key] = value
    assert values["NLWEB_ENABLED"].lower() == "true"
    assert values["NLWEB_CONTENT_SYNC_ENABLED"].lower() == "true"
    assert values["NLWEB_CONTENT_SYNC_ON_STARTUP"].lower() == "true"
    assert values["NLWEB_CONTENT_SYNC_INTERVAL_SECONDS"] == "0"
    assert values["NLWEB_CONTENT_SYNC_STATE_FILE"]


def test_fastapi_and_query_demo_resources_exist() -> None:
    root = Path("examples/external_hosted_sources/domain_site_extractor")
    assert (root / "app.py").is_file()
    assert (root / "query_demo.py").is_file()


def test_provider_loader_resolves_relative_paths_from_registry_directory(tmp_path: Path) -> None:
    pytest.importorskip("nlweb_widget")
    from types import SimpleNamespace

    from examples.provider_backends.common.widget import _registry_source_location

    registry_dir = tmp_path / "example"
    registry_dir.mkdir()
    location = _registry_source_location(
        {"location": "content/inbox"}, SimpleNamespace(location="content/inbox"), registry_dir
    )
    assert Path(location) == (registry_dir / "content/inbox").resolve()


def test_example_owned_registry_detection_handles_explicit_example_path(tmp_path: Path) -> None:
    from examples.external_hosted_sources.domain_site_extractor.registry import (
        uses_example_owned_registry,
    )

    example = tmp_path / "domain_site_extractor"
    example.mkdir()
    assert uses_example_owned_registry(example, None) is True
    assert uses_example_owned_registry(example, "nlweb-sources.json") is True
    assert uses_example_owned_registry(example, str(example / "nlweb-sources.json")) is True
    assert uses_example_owned_registry(example, "consumer/sources.json") is False


def test_scenario_registry_maps_one_to_one_to_exact_files_and_corpus_ids() -> None:
    from examples.external_hosted_sources.domain_site_extractor.registry import (
        validate_scenario_registry,
    )

    root = Path("examples/external_hosted_sources/domain_site_extractor").resolve()
    mapping = validate_scenario_registry(root)
    config = json.loads((root / "nlweb-sources.json").read_text(encoding="utf-8"))
    sources = {source["name"]: source for source in config["sources"]}
    assert set(mapping) == {
        "company_website",
        "company_knowledge_base",
        "company_portal",
        "product_service_catalog",
        "company_newsroom",
    }
    assert sources["authoritative_domain"]["kind"] == "custom"
    assert sources["authoritative_domain"]["location"] == "content/inbox"
    assert sources["authoritative_domain"]["site"] == "external-source.example"
    assert (root / sources["authoritative_domain"]["location"]).is_dir()
    assert {path.name for path in (root / "content/inbox").iterdir() if path.is_file()} >= {
        "domain.jsonld",
        "capabilities.md",
        "capabilities.txt",
        "industrial-platforms.pptx",
        "digital-engineering-brief.pdf",
    }
    for scenario, item in mapping.items():
        source = sources[scenario]
        assert source["name"] == scenario
        assert source["site"] == item["site"]
        assert source["location"] == item["artifact"]
        assert source["metadata"]["scenario"] == scenario
        assert source["enabled"] is False  # no extraction artifact is checked in by default
        assert Path(source["location"]).parent == Path("generated")
    assert mapping["company_website"]["site"] == "external-source.example"
    assert mapping["product_service_catalog"]["site"] == "products.external-source.example"
    assert mapping["company_portal"]["site"] == "manuals.products.external-source.example"


def test_runtime_registry_preserves_corpus_ids_and_enables_only_fresh_exact_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shutil

    from examples.external_hosted_sources.domain_site_extractor.registry import (
        prepare_runtime_source_registry,
        site_identifier,
    )

    source_root = Path("examples/external_hosted_sources/domain_site_extractor").resolve()
    target_root = tmp_path / "example"
    shutil.copytree(
        source_root, target_root, ignore=shutil.ignore_patterns("runtime", ".env", "__pycache__")
    )
    generated = target_root / "generated"
    artifact = generated / "products.external-source.example.jsonld"
    artifact.write_text(
        json.dumps(
            {"@context": "https://schema.org", "@graph": [{"@type": "Product", "name": "Test"}]}
        ),
        encoding="utf-8",
    )
    source_url = "https://products.company.example/"
    monkeypatch.setenv("NLWEB_EXTERNAL_SOURCE_CATALOG_URL", source_url)
    from examples.external_hosted_sources.domain_site_extractor.registry import _load_toml

    source_config = _load_toml(target_root / "sources.toml")["sources"]["product_service_catalog"]
    prompt_config = _load_toml(target_root / "prompts" / "extraction_scenarios.toml")["scenarios"][
        "product_service_catalog"
    ]
    prompt_sha = hashlib.sha256(
        json.dumps(prompt_config, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()
    manifest = {
        "schema_version": 1,
        "scenario": "product_service_catalog",
        "sources": [source_url],
        "site": source_config["site"],
        "canonical_site_url": "https://www.company.example/about",
        "prompt_sha256": prompt_sha,
        "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
    }
    artifact.with_name(artifact.name + ".manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    registry_path = prepare_runtime_source_registry(
        target_root, "https://www.company.example/about"
    )
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    sources = {item["name"]: item for item in payload["sources"]}

    assert site_identifier("https://www.company.example/about") == "www.company.example"
    # Canonical URL identity does not overwrite consumer-declared retrieval corpus IDs.
    assert sources["authoritative_domain"]["site"] == "external-source.example"
    assert sources["authoritative_domain"]["enabled"] is True
    assert sources["authoritative_domain"]["location"] == str(
        (target_root / "content/inbox").resolve()
    )
    assert "excluded_filenames" not in sources["authoritative_domain"].get("metadata", {})
    assert sources["product_service_catalog"]["site"] == "products.external-source.example"
    assert sources["product_service_catalog"]["enabled"] is True
    assert (
        Path(sources["product_service_catalog"]["location"]).resolve()
        == (generated / "products.external-source.example.jsonld").resolve()
    )
    assert sources["company_website"]["enabled"] is False
    # A stray/stale artifact not listed in sources.toml is never registered.
    (generated / "unmapped-stale.jsonld").write_text("{}", encoding="utf-8")
    registry_path = prepare_runtime_source_registry(target_root, "https://www.company.example/")
    sources = json.loads(registry_path.read_text(encoding="utf-8"))["sources"]
    assert all("unmapped-stale.jsonld" not in item["location"] for item in sources)


def test_runtime_registry_registers_backend_artifacts_as_distinct_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shutil

    from examples.external_hosted_sources.domain_site_extractor.registry import (
        _prompt_fingerprint,
        backend_corpus_id,
        prepare_runtime_source_registry,
    )

    source_root = Path("examples/external_hosted_sources/domain_site_extractor").resolve()
    target_root = tmp_path / "example"
    shutil.copytree(
        source_root, target_root, ignore=shutil.ignore_patterns("runtime", ".env", "__pycache__")
    )
    monkeypatch.setenv("NLWEB_EXTERNAL_SOURCE_COMPANY_WEBSITE_URL", "https://company.example/")
    canonical_url = "https://company.example/about"
    generated = target_root / "generated"
    generated.mkdir(exist_ok=True)
    scenario = "company_website"
    site = "external-source.example"
    for backend in ("custom", "scrapegraphai", "scrapy_transformers"):
        artifact = generated / f"external-source.example.{backend}.jsonld"
        artifact.write_text(
            json.dumps(
                {"@context": "https://schema.org", "@graph": [{"@type": "Thing", "name": backend}]}
            ),
            encoding="utf-8",
        )
        manifest = {
            "schema_version": 1,
            "scenario": scenario,
            "backend": backend,
            "sources": ["https://company.example/"],
            "site": site,
            "retrieval_site": backend_corpus_id(site, backend),
            "canonical_site_url": canonical_url,
            "prompt_sha256": _prompt_fingerprint(target_root, scenario),
            "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        }
        artifact.with_name(artifact.name + ".manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )

    registry_path = prepare_runtime_source_registry(target_root, canonical_url)
    sources = {
        item["name"]: item
        for item in json.loads(registry_path.read_text(encoding="utf-8"))["sources"]
    }
    assert sources["company_website"]["enabled"] is False
    custom = sources["company_website__custom"]
    llm = sources["company_website__scrapegraphai"]
    assert custom["enabled"] is True
    assert llm["enabled"] is True
    assert custom["location"] != llm["location"]
    assert custom["site"] == site
    assert llm["site"] == f"{site}--scrapegraphai"
    assert custom["metadata"]["backend"] == "custom"
    assert llm["metadata"]["backend"] == "scrapegraphai"
    transformers = sources["company_website__scrapy_transformers"]
    assert transformers["enabled"] is True
    assert transformers["site"] == f"{site}--scrapy_transformers"
    assert transformers["metadata"]["backend"] == "scrapy_transformers"
    assert len({custom["location"], llm["location"], transformers["location"]}) == 3


def test_runtime_registry_preserves_consumer_owned_authoritative_content(tmp_path: Path) -> None:
    import shutil

    from examples.external_hosted_sources.domain_site_extractor.registry import (
        prepare_runtime_source_registry,
    )

    source_root = Path("examples/external_hosted_sources/domain_site_extractor").resolve()
    target_root = tmp_path / "example"
    shutil.copytree(
        source_root, target_root, ignore=shutil.ignore_patterns("runtime", ".env", "__pycache__")
    )
    fixture = target_root / "content" / "inbox" / "domain.jsonld"
    fixture.write_text(
        json.dumps(
            {
                "@type": "Organization",
                "@id": "https://company.example/#org",
                "url": "https://company.example/",
            }
        ),
        encoding="utf-8",
    )
    registry_path = prepare_runtime_source_registry(target_root, "https://company.example/")
    sources = json.loads(registry_path.read_text(encoding="utf-8"))["sources"]
    authoritative = next(item for item in sources if item["name"] == "authoritative_domain")
    assert authoritative["enabled"] is True
    assert authoritative["site"] == "external-source.example"
    assert authoritative["location"] == str((target_root / "content/inbox").resolve())
    assert authoritative["metadata"]["url"] == "https://external-source.example/"
    assert "excluded_filenames" not in authoritative.get("metadata", {})


def test_source_registry_resolves_directory_and_exact_artifact_locations_relative_to_registry_file() -> (
    None
):
    pytest.importorskip("nlweb_widget")
    from nlweb_widget.content.service import load_content_sources

    root = Path("examples/external_hosted_sources/domain_site_extractor").resolve()
    sources = load_content_sources(root / "nlweb-sources.json")
    by_name = {source.name: source for source in sources}
    authoritative = Path(by_name["authoritative_domain"].location)
    generated = Path(by_name["product_service_catalog"].location)
    assert authoritative == (root / "content/inbox").resolve()
    assert authoritative.is_dir()
    assert generated == (root / "generated/products.external-source.example.jsonld").resolve()
    assert not generated.exists()  # missing optional artifact is explicitly disabled at runtime


def test_registry_contract_rejects_scenario_artifact_mismatch(tmp_path: Path) -> None:
    import shutil

    from examples.external_hosted_sources.domain_site_extractor.registry import (
        validate_scenario_registry,
    )

    source_root = Path("examples/external_hosted_sources/domain_site_extractor").resolve()
    target_root = tmp_path / "example"
    shutil.copytree(
        source_root, target_root, ignore=shutil.ignore_patterns("runtime", ".env", "__pycache__")
    )
    registry = target_root / "nlweb-sources.json"
    payload = json.loads(registry.read_text(encoding="utf-8"))
    next(item for item in payload["sources"] if item["name"] == "company_website")["location"] = (
        "generated/other.jsonld"
    )
    registry.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="artifact does not match"):
        validate_scenario_registry(target_root)


def test_exact_file_source_discovery_does_not_scan_neighboring_corpus_artifacts(
    tmp_path: Path,
) -> None:
    from examples.provider_backends.common.ingestion import iter_source_files

    generated = tmp_path / "generated"
    generated.mkdir()
    target = generated / "products.example.jsonld"
    target.write_text("{}", encoding="utf-8")
    (generated / "news.example.jsonld").write_text("{}", encoding="utf-8")
    assert iter_source_files(target) == [target]


@pytest.mark.asyncio
async def test_exact_jsonld_file_ingestion_assigns_only_declared_corpus_without_haystack() -> None:
    from examples.provider_backends.common.ingestion import ingest_directory_async

    class CaptureStore:
        def __init__(self) -> None:
            self.documents = []

        async def upsert(self, document):
            self.documents.append(document)
            return 1

    root = Path("examples/external_hosted_sources/domain_site_extractor").resolve()
    source_file = root / "content" / "inbox" / "domain.jsonld"
    store = CaptureStore()
    result = await ingest_directory_async(
        source_file, store, site="external-source.example", embedding_provider=None
    )
    assert result["processed"] == 1
    assert len(store.documents) == 1
    assert store.documents[0].site == "external-source.example"
    assert store.documents[0].metadata["source_file"] == "domain.jsonld"


def test_runtime_registry_disables_modified_or_unprovenanced_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    from examples.external_hosted_sources.domain_site_extractor.registry import (
        prepare_runtime_source_registry,
    )

    source_root = Path("examples/external_hosted_sources/domain_site_extractor").resolve()
    target_root = tmp_path / "example"
    shutil.copytree(
        source_root, target_root, ignore=shutil.ignore_patterns("runtime", ".env", "__pycache__")
    )
    artifact = target_root / "generated" / "products.external-source.example.jsonld"
    artifact.write_text(
        json.dumps({"@context": "https://schema.org", "@graph": []}), encoding="utf-8"
    )
    monkeypatch.setenv("NLWEB_EXTERNAL_SOURCE_CATALOG_URL", "https://products.company.example/")
    registry_path = prepare_runtime_source_registry(target_root, "https://external-source.example/")
    sources = {
        item["name"]: item
        for item in json.loads(registry_path.read_text(encoding="utf-8"))["sources"]
    }
    assert sources["product_service_catalog"]["enabled"] is False
    assert (
        "provenance manifest is missing"
        in sources["product_service_catalog"]["metadata"]["runtime_disabled_reason"]
    )


def test_source_registry_url_is_used_as_ingestion_fallback(tmp_path: Path) -> None:
    from examples.provider_backends.common.ingestion import schema_document

    path = tmp_path / "domain.jsonld"
    payload = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": "Example Organization",
    }
    document = schema_document(
        path,
        json.dumps(payload),
        "example-corpus",
        fallback_url="https://consumer.example/domain-content",
    )
    assert document.url == "https://consumer.example/domain-content/domain.jsonld"
    assert document.site == "example-corpus"


def test_provider_widget_forwards_source_metadata_url_to_ingestion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import examples.provider_backends.common.widget as builder

    captured: dict[str, object] = {}

    async def fake_ingest_directory_async(*args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        return {"processed": 1}

    class FakeSettings:
        content_sync_state_file = str(tmp_path / ".sync-state.json")

        def model_copy(self, *, update):
            return self

    class FakeStateStore:
        async def get(self, source_name):
            return None

    class FakeSyncService:
        def __init__(self, **kwargs) -> None:
            self.loader = None
            self.state_store = FakeStateStore()

        def register_loader(self, kind, loader) -> None:
            self.loader = loader
            captured["kind"] = kind

    class FakeWidget:
        def __init__(self, **kwargs) -> None:
            self.store = object()

    monkeypatch.setattr(builder, "NLWebSettings", lambda **kwargs: FakeSettings())
    monkeypatch.setattr(builder, "build_embedding_provider", lambda: object())
    sync_service = FakeSyncService()
    monkeypatch.setattr(builder, "ContentSyncService", lambda **kwargs: sync_service)
    monkeypatch.setattr(builder, "NLWebWidget", FakeWidget)
    monkeypatch.setattr(builder, "ingest_directory_async", fake_ingest_directory_async)
    (tmp_path / "nlweb-sources.json").write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "name": "consumer-authoritative-source",
                        "location": "s3://${BUCKET}/",
                        "remote_storage_options": {},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BUCKET", "consumer-bucket")

    widget = builder.build_provider_widget(
        "sqlite", "https://consumer.example/", tmp_path / "app.py"
    )
    assert widget is not None
    source = type(
        "Source",
        (),
        {
            "name": "consumer-authoritative-source",
            "location": str(tmp_path / "content"),
            "site": "consumer-corpus",
            "metadata": {"url": "https://consumer.example/authoritative-content"},
        },
    )()
    result = asyncio.run(sync_service.loader(source))
    assert result["processed"] == 1
    assert result["item_keys"] == []
    assert "source=consumer-authoritative-source" in result["message"]
    assert captured["url"] == "https://consumer.example/authoritative-content"
    assert captured["site"] == "consumer-corpus"
    # Recover the authoritative URI from the registry instead of a duplicate metadata key.
    assert captured["args"][0] == "s3://consumer-bucket/"


def test_generated_jsonld_artifact_shape_is_compatible_with_structured_source_loader() -> None:
    pytest.importorskip("nlweb_widget")
    from examples.provider_backends.common.ingestion import schema_document

    root = Path("examples/external_hosted_sources/domain_site_extractor")
    records = extraction_to_jsonld(
        {
            "scenario": "company_website",
            "payload": {
                "records": [
                    {
                        "@type": "WebPage",
                        "name": "Example Co Services",
                        "url": "https://example.test/services",
                    }
                ]
            },
        },
        site="https://example.test/",
    )
    artifact = {"@context": "https://schema.org", "@graph": records}
    path = root / "generated" / "test-generated.jsonld"
    document = schema_document(
        path,
        json.dumps(artifact),
        "example.test",
        fallback_url="https://fallback.example/",
    )
    assert document.title == "Example Co Services"
    assert document.url == "https://example.test/services"
    assert document.schema_object["@graph"][0]["name"] == "Example Co Services"


def test_standalone_demo_loads_example_env_before_scenario_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import examples.external_hosted_sources.domain_site_extractor.demo as demo

    env_file = tmp_path / ".env"
    env_file.write_text(
        "NLWEB_EXTERNAL_SOURCE_COMPANY_WEBSITE_URL=https://company.example/\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(demo, "_ENV_FILE", env_file)
    monkeypatch.delenv("NLWEB_EXTERNAL_SOURCE_COMPANY_WEBSITE_URL", raising=False)
    demo._load_example_env()
    assert demo._scenario("company_website")["urls"] == ["https://company.example/"]


def test_scenario_artifact_paths_are_declared_and_stable() -> None:
    from examples.external_hosted_sources.domain_site_extractor.demo import ROOT, _scenario

    for name in (
        "company_website",
        "company_knowledge_base",
        "company_portal",
        "product_service_catalog",
        "company_newsroom",
    ):
        scenario = _scenario(name)
        path = (ROOT / scenario["artifact"]).resolve()
        assert path.parent == (ROOT / "generated").resolve()
        assert path.name.startswith(scenario["site"])


def test_authoritative_inbox_is_a_custom_directory_source_and_discovers_supported_files() -> None:
    from examples.provider_backends.common.ingestion import iter_source_files

    root = Path("examples/external_hosted_sources/domain_site_extractor").resolve()
    registry = json.loads((root / "nlweb-sources.json").read_text(encoding="utf-8"))
    source = next(item for item in registry["sources"] if item["name"] == "authoritative_domain")
    inbox = root / source["location"]

    assert source["kind"] == "custom"
    assert source["enabled"] is True
    assert source["metadata"]["url"] == "https://external-source.example/"
    assert inbox.is_dir()
    assert {path.name for path in iter_source_files(inbox)} == {
        "domain.jsonld",
        "capabilities.md",
        "capabilities.txt",
        "industrial-platforms.pptx",
        "digital-engineering-brief.pdf",
    }


def test_directory_ingestion_preserves_site_and_indexes_structured_and_unstructured_inbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    from examples.provider_backends.common.ingestion import ingest_directory_async

    # Stub only the optional Haystack conversion boundary so this regression test also runs
    # in lean build containers. Production still uses the declared haystack-ai dependency.
    class FakeDocument:
        def __init__(self, content: str = "", meta: dict | None = None) -> None:
            self.content = content
            self.meta = meta or {}

    class FakeConverter:
        def run(self, *, sources, meta):
            path = Path(sources[0])
            return {
                "documents": [
                    FakeDocument(content=f"converted {path.name}", meta={"title": path.stem})
                ],
                "failed": [],
                "unclassified": [],
            }

    class FakeSplitter:
        def __init__(self, **kwargs) -> None:
            pass

        def run(self, *, documents):
            return {"documents": documents}

    class FakeCleaner:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def run(self, *, documents):
            return {"documents": documents}

    haystack = types.ModuleType("haystack")
    haystack.Document = FakeDocument
    components = types.ModuleType("haystack.components")
    converters = types.ModuleType("haystack.components.converters")
    converters.MultiFileConverter = FakeConverter
    preprocessors = types.ModuleType("haystack.components.preprocessors")
    preprocessors.DocumentSplitter = FakeSplitter
    preprocessors.DocumentCleaner = FakeCleaner
    for name, module in (
        ("haystack", haystack),
        ("haystack.components", components),
        ("haystack.components.converters", converters),
        ("haystack.components.preprocessors", preprocessors),
    ):
        monkeypatch.setitem(sys.modules, name, module)

    class CaptureStore:
        def __init__(self) -> None:
            self.documents = []

        async def upsert(self, document):
            self.documents.append(document)
            return 1

    root = Path("examples/external_hosted_sources/domain_site_extractor").resolve()
    inbox = root / "content" / "inbox"
    store = CaptureStore()
    result = asyncio.run(
        ingest_directory_async(
            inbox,
            store,
            site="external-source.example",
            url="https://external-source.example/authoritative-content",
            embedding_provider=None,
        )
    )
    expected = {
        "domain.jsonld",
        "capabilities.md",
        "capabilities.txt",
        "industrial-platforms.pptx",
        "digital-engineering-brief.pdf",
    }
    assert result["processed"] == len(expected)
    assert result["total_loaded"] == len(expected)
    assert {item.metadata["source_file"] for item in store.documents} == expected
    assert {item.site for item in store.documents} == {"external-source.example"}
    assert {item.url for item in store.documents} == {
        "https://example.org/organization",
        *{
            f"https://external-source.example/authoritative-content/{name}"
            for name in expected
            if name != "domain.jsonld"
        },
    }
    structured = next(
        item for item in store.documents if item.metadata["source_file"] == "domain.jsonld"
    )
    assert structured.schema_object["@type"] == "Organization"
    assert structured.metadata["grounding"]["citations"][0]["label"] == "Organization profile"
    assert structured.metadata["grounding"]["schema_refs"] == [
        "https://schema.org/Organization",
        "https://example.org/schemas/organization-v1.json",
    ]
    by_artifact = {}
    for item in store.documents:
        by_artifact.setdefault(item.metadata["source_file"], set()).add(item.url)
    assert all(len(urls) == 1 for urls in by_artifact.values())


def test_default_runtime_registry_keeps_authoritative_inbox_enabled_and_uses_absolute_paths(
    tmp_path: Path,
) -> None:
    import shutil

    from examples.external_hosted_sources.domain_site_extractor.registry import (
        prepare_runtime_source_registry,
    )

    source_root = Path("examples/external_hosted_sources/domain_site_extractor").resolve()
    target_root = tmp_path / "example"
    shutil.copytree(
        source_root, target_root, ignore=shutil.ignore_patterns("runtime", ".env", "__pycache__")
    )
    registry_path = prepare_runtime_source_registry(target_root, "https://external-source.example/")
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    authoritative = next(
        item for item in payload["sources"] if item["name"] == "authoritative_domain"
    )
    assert authoritative["kind"] == "custom"
    assert authoritative["enabled"] is True
    assert Path(authoritative["location"]).is_absolute()
    assert Path(authoritative["location"]).is_dir()
    assert authoritative["metadata"]["url"] == "https://external-source.example/"
    assert "excluded_filenames" not in authoritative.get("metadata", {})


def test_optional_evidence_manifest_supplies_type_and_grounding_without_overriding_source_type(
    tmp_path: Path,
) -> None:
    from examples.provider_backends.common.ingestion import (
        EVIDENCE_MANIFEST_NAME,
        _load_evidence_manifest,
        schema_document,
    )

    source = tmp_path / "reference.jsonld"
    source.write_text(
        json.dumps({"@context": "https://schema.org", "@type": "Article", "name": "Reference"}),
        encoding="utf-8",
    )
    grounding = {"source": "https://public.example/reference", "custom": {"keep": True}}
    (tmp_path / EVIDENCE_MANIFEST_NAME).write_text(
        json.dumps(
            {
                "version": "1",
                "artifacts": [
                    {"artifact": "reference.jsonld", "type": "Service", "grounding": grounding}
                ],
            }
        ),
        encoding="utf-8",
    )
    entries = _load_evidence_manifest(tmp_path)
    document = schema_document(
        source,
        source.read_text(encoding="utf-8"),
        "reference",
        manifest_entry=entries["reference.jsonld"],
    )
    assert document.schema_object["@type"] == "Article"
    assert document.metadata["grounding"] == grounding


def test_optional_evidence_manifest_type_is_fallback_when_source_has_no_type(
    tmp_path: Path,
) -> None:
    from examples.provider_backends.common.ingestion import schema_document

    source = tmp_path / "untyped.jsonld"
    payload = {"@context": "https://schema.org", "name": "Untyped record"}
    document = schema_document(
        source,
        json.dumps(payload),
        "reference",
        manifest_entry={
            "type": "Article",
            "grounding": {"source": "https://public.example/untyped"},
        },
    )
    assert document.schema_object["@type"] == "Article"
    assert document.metadata["grounding"] == {"source": "https://public.example/untyped"}


def test_evidence_manifest_rejects_duplicate_and_unsafe_artifact_keys(tmp_path: Path) -> None:
    from examples.provider_backends.common.ingestion import (
        EVIDENCE_MANIFEST_NAME,
        _load_evidence_manifest,
    )

    path = tmp_path / EVIDENCE_MANIFEST_NAME
    path.write_text(
        json.dumps({"version": "1", "artifacts": [{"artifact": "../outside.txt"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="safe relative path"):
        _load_evidence_manifest(tmp_path)
    path.write_text(
        json.dumps({"version": "1", "artifacts": [{"artifact": "a.txt"}, {"artifact": "a.txt"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Duplicate"):
        _load_evidence_manifest(tmp_path)


@pytest.mark.asyncio
async def test_ingestion_manifest_is_control_metadata_and_persists_grounding(
    tmp_path: Path,
) -> None:
    from examples.provider_backends.common.ingestion import (
        EVIDENCE_MANIFEST_NAME,
        ingest_directory_async,
    )

    artifact = tmp_path / "service.jsonld"
    artifact.write_text(
        json.dumps(
            {"@context": "https://schema.org", "@type": "Service", "name": "Source service"}
        ),
        encoding="utf-8",
    )
    grounding = {"source": "https://public.example/service", "policy": {"verified_by": "consumer"}}
    (tmp_path / EVIDENCE_MANIFEST_NAME).write_text(
        json.dumps(
            {
                "version": "1",
                "artifacts": [
                    {"artifact": "service.jsonld", "type": "Product", "grounding": grounding}
                ],
            }
        ),
        encoding="utf-8",
    )

    class CaptureStore:
        def __init__(self) -> None:
            self.documents = []

        async def upsert(self, document):
            self.documents.append(document)

    store = CaptureStore()
    result = await ingest_directory_async(tmp_path, store, site="test", embedding_provider=None)
    assert result["processed"] == 1
    assert [item.metadata["source_file"] for item in store.documents] == ["service.jsonld"]
    assert store.documents[0].schema_object["@type"] == "Service"
    assert store.documents[0].metadata["grounding"] == grounding


def test_structured_artifact_url_wins_over_schema_id(tmp_path: Path) -> None:
    from examples.provider_backends.common.ingestion import schema_document

    path = tmp_path / "source.jsonld"
    document = schema_document(
        path,
        json.dumps(
            {
                "@context": "https://schema.org",
                "@type": "Article",
                "@id": "https://example.test/entities/article-1",
                "url": "https://example.test/reports/article-1.pdf",
                "name": "Article One",
            }
        ),
        "test",
        fallback_url="https://fallback.example/base",
    )
    assert document.url == "https://example.test/reports/article-1.pdf"
    assert document.schema_object["@id"] == "https://example.test/entities/article-1"


@pytest.mark.asyncio
async def test_jsonld_graph_records_are_indexed_as_individual_results(tmp_path: Path) -> None:
    from examples.provider_backends.common.ingestion import ingest_directory_async

    (tmp_path / "catalog.jsonld").write_text(
        json.dumps(
            {
                "@context": "https://schema.org",
                "@graph": [
                    {
                        "@type": "Organization",
                        "name": "Graph organization",
                        "url": "https://example.test/org",
                    },
                    {
                        "@type": "Service",
                        "name": "Graph service",
                        "url": "https://example.test/service",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    class CaptureStore:
        def __init__(self):
            self.documents = []

        async def upsert(self, document):
            self.documents.append(document)

    store = CaptureStore()
    result = await ingest_directory_async(
        tmp_path, store, site="graph-test", embedding_provider=None
    )
    assert result["processed"] == 1
    assert result["indexed"] == 2
    assert {item.title for item in store.documents} == {"Graph organization", "Graph service"}
    assert {item.schema_object["@type"] for item in store.documents} == {"Organization", "Service"}
    assert len({item.id for item in store.documents}) == 2


def test_runtime_registry_preserves_remote_authoritative_location(tmp_path: Path) -> None:
    import shutil

    from examples.external_hosted_sources.domain_site_extractor.registry import (
        prepare_runtime_source_registry,
    )

    source_root = Path("examples/external_hosted_sources/domain_site_extractor").resolve()
    target_root = tmp_path / "remote-example"
    shutil.copytree(
        source_root, target_root, ignore=shutil.ignore_patterns("runtime", ".env", "__pycache__")
    )
    registry = target_root / "nlweb-sources.json"
    payload = json.loads(registry.read_text(encoding="utf-8"))
    item = next(source for source in payload["sources"] if source["name"] == "authoritative_domain")
    item["location"] = "s3://qa-bucket/domain/inbox/"
    item["remote_storage_options"] = {"token": "${REMOTE_TOKEN}"}
    registry.write_text(json.dumps(payload), encoding="utf-8")
    runtime_path = prepare_runtime_source_registry(target_root, "https://customer.example/")
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    remote = next(
        source for source in runtime["sources"] if source["name"] == "authoritative_domain"
    )
    assert remote["location"] == "s3://qa-bucket/domain/inbox/"
    assert remote["metadata"]["remote_storage_options"] == {"token": "${REMOTE_TOKEN}"}


def test_jsonld_script_wrapped_inbox_artifact_is_accepted(tmp_path: Path) -> None:
    from examples.provider_backends.common.ingestion import schema_document

    path = tmp_path / "IPENprj.jsonld"
    path.write_text(
        '<script type="application/ld+json">\n'
        '{"@context":"https://schema.org","@type":"Organization",'
        '"@id":"https://company.example/#organization",'
        '"url":"https://company.example/","name":"Example Company",'
        '"description":"A structured company profile."}\n'
        "</script>\n",
        encoding="utf-8",
    )
    document = schema_document(path, path.read_text(encoding="utf-8"), "company.example")
    assert document.title == "Example Company"
    assert str(document.url) == "https://company.example/"
    assert document.schema_object["@type"] == "Organization"


@pytest.mark.asyncio
async def test_manifest_mismatches_are_reported_without_blocking_healthy_artifacts(
    tmp_path: Path,
) -> None:
    from examples.provider_backends.common.ingestion import (
        EVIDENCE_MANIFEST_NAME,
        ingest_directory_async,
    )

    healthy = tmp_path / "healthy.jsonld"
    healthy.write_text(
        json.dumps({"@context": "https://schema.org", "@type": "Organization", "name": "Healthy"}),
        encoding="utf-8",
    )
    unsupported = tmp_path / "unsupported.xlsx"
    unsupported.write_bytes(b"not a supported source format")
    (tmp_path / EVIDENCE_MANIFEST_NAME).write_text(
        json.dumps(
            {
                "version": "1",
                "artifacts": [
                    {"artifact": "healthy.jsonld", "type": "Organization"},
                    {"artifact": "unsupported.xlsx", "type": "Dataset"},
                    {"artifact": "missing.docx", "type": "Article"},
                ],
            }
        ),
        encoding="utf-8",
    )

    class CaptureStore:
        def __init__(self):
            self.documents = []

        async def upsert(self, document):
            self.documents.append(document)

    store = CaptureStore()
    result = await ingest_directory_async(
        tmp_path, store, site="partial-test", embedding_provider=None
    )
    assert result["processed"] == 1
    assert [doc.title for doc in store.documents] == ["Healthy"]
    assert result["partial"] is True
    assert {item["code"] for item in result["incidents"]} == {
        "unsupported_artifact_format",
        "manifest_artifact_missing",
    }
    assert "Skipped/reported 2 incident(s)" in result["message"]


def test_registry_source_location_preserves_couchdb_uri_placeholders() -> None:
    from types import SimpleNamespace

    from examples.provider_backends.common.widget import _registry_source_location

    source = SimpleNamespace(location=Path(r"C:\example\couchdb+http:\127.0.0.1:5984\nlweb_domain"))
    assert (
        _registry_source_location(
            {"location": "couchdb+${NLWEB_COUCHDB_URL}/${NLWEB_COUCHDB_DATABASE}"}, source
        )
        == "couchdb+${NLWEB_COUCHDB_URL}/${NLWEB_COUCHDB_DATABASE}"
    )


@pytest.mark.asyncio
async def test_docx_artifact_is_ingested_without_multifileconverter(
    tmp_path: Path, monkeypatch
) -> None:
    docx = pytest.importorskip("docx")
    import sys
    from types import ModuleType

    from examples.provider_backends.common.ingestion import (
        EVIDENCE_MANIFEST_NAME,
        ingest_directory_async,
    )

    document = docx.Document()
    document.add_paragraph("Evidence-backed DOCX service description.")
    document.add_table(rows=1, cols=2).rows[0].cells[0].text = "Integration"
    document.save(tmp_path / "service.docx")
    (tmp_path / EVIDENCE_MANIFEST_NAME).write_text(
        json.dumps(
            {"version": "1", "artifacts": [{"artifact": "service.docx", "type": "Service"}]}
        ),
        encoding="utf-8",
    )

    class HaystackDocument:
        def __init__(self, content, meta=None):
            self.content, self.meta = content, (meta or {})

    class Converter:
        def run(self, **kwargs):
            raise AssertionError("DOCX must not use MultiFileConverter")

    class Splitter:
        def __init__(self, **kwargs):
            pass

        def run(self, documents):
            return {"documents": documents}

    class Cleaner:
        def __init__(self, **kwargs):
            pass

        def run(self, documents):
            return {"documents": documents}

    haystack = ModuleType("haystack")
    haystack.__path__ = []
    haystack.Document = HaystackDocument
    components = ModuleType("haystack.components")
    components.__path__ = []
    converters = ModuleType("haystack.components.converters")
    converters.MultiFileConverter = Converter
    preprocessors = ModuleType("haystack.components.preprocessors")
    preprocessors.DocumentSplitter = Splitter
    preprocessors.DocumentCleaner = Cleaner
    monkeypatch.setitem(sys.modules, "haystack", haystack)
    monkeypatch.setitem(sys.modules, "haystack.components", components)
    monkeypatch.setitem(sys.modules, "haystack.components.converters", converters)
    monkeypatch.setitem(sys.modules, "haystack.components.preprocessors", preprocessors)

    class CaptureStore:
        def __init__(self):
            self.documents = []

        async def upsert(self, item):
            self.documents.append(item)

    store = CaptureStore()
    result = await ingest_directory_async(
        tmp_path, store, site="docx-test", embedding_provider=None
    )
    assert result["processed"] == 1
    assert result["indexed"] == 1
    assert "Evidence-backed DOCX service description." in store.documents[0].content
    assert store.documents[0].schema_object["@type"] == "Service"


def test_scrapy_transformers_backend_writes_its_own_artifact_and_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import examples.external_hosted_sources.domain_site_extractor.demo as demo

    monkeypatch.setattr(demo, "_load_example_env", lambda: None)
    monkeypatch.setattr(demo, "ROOT", tmp_path)
    monkeypatch.setattr(
        demo,
        "_scenario",
        lambda name: {
            "artifact": "generated/company.jsonld",
            "prompt": "Extract evidence-backed claims.",
            "schema_hint": {},
            "urls": ["https://company.example/"],
            "site": "company.example",
        },
    )
    monkeypatch.setenv("NLWEB_EXTERNAL_SOURCE_ENABLED", "false")
    monkeypatch.setenv("NLWEB_EXTERNAL_SOURCE_LLM_ENABLED", "true")
    monkeypatch.setenv("NLWEB_EXTERNAL_SOURCE_EXTRACTOR_BACKEND", "scrapy_transformers")
    monkeypatch.setenv("NLWEB_EXTERNAL_SOURCE_ALLOWED_HOSTS", "company.example")

    def fake_run(command, **kwargs):
        output = Path(command[command.index("--output") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "@context": "https://schema.org",
                    "@graph": [{"@type": "Service", "name": "Transformer result"}],
                }
            ),
            encoding="utf-8",
        )
        return __import__("subprocess").CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(demo.subprocess, "run", fake_run)
    result = asyncio.run(demo.extract_to_artifact("company_website"))
    assert result["backend"] == "scrapy_transformers"
    assert Path(result["jsonld"]).name == "company.jsonld"
    assert Path(result["provenance"]).is_file()
    assert (
        json.loads(Path(result["jsonld"]).read_text(encoding="utf-8"))["@graph"][0]["name"]
        == "Transformer result"
    )
