from pathlib import Path

from examples.provider_backends.common.ingestion import SUPPORTED_SUFFIXES, iter_source_files

PROVIDERS = (
    "postgres_pgvector",
    "neo4j",
    "qdrant_edge",
    "qdrant_server",
    "haystack_inmemory",
    "sqlite",
)


def test_provider_corpus_contains_structured_and_unstructured_sources() -> None:
    for provider in PROVIDERS:
        directory = Path("examples/provider_backends") / provider / "content" / "inbox"
        files = iter_source_files(directory)
        suffixes = {path.suffix.lower() for path in files}
        assert {".jsonld", ".txt", ".pdf", ".pptx"} <= suffixes
        assert suffixes <= SUPPORTED_SUFFIXES


def test_provider_sources_are_dynamic_not_filename_enumerated() -> None:
    source_files = Path(
        "examples/provider_backends/postgres_pgvector/nlweb-sources.json"
    ).read_text(encoding="utf-8")
    assert "content/inbox" in source_files
    assert "capabilities.txt" not in source_files
    assert "industrial-platforms.pptx" not in source_files


def test_provider_examples_cover_all_optional_retrieval_backends() -> None:
    actual = {path.name for path in Path("examples/provider_backends").iterdir() if path.is_dir()}
    assert set(PROVIDERS) <= actual


import pytest


@pytest.mark.parametrize("provider", PROVIDERS, ids=PROVIDERS)
def test_individual_provider_example_is_runnable_shape(provider: str) -> None:
    directory = Path("examples/provider_backends") / provider
    assert (directory / ".env.example").is_file()
    assert (directory / "app.py").is_file()
    assert (directory / "query_demo.py").is_file()
    assert (directory / "nlweb-sources.json").is_file()


def test_qdrant_server_example_has_local_service_definition() -> None:
    compose = Path("examples/provider_backends/qdrant_server/infra/docker-compose.yml")
    assert compose.is_file()
    assert "qdrant/qdrant" in compose.read_text(encoding="utf-8")


def test_provider_environment_examples_cover_store_selection() -> None:
    expected = {
        "haystack_inmemory": "NLWEB_RETRIEVAL_STORE=haystack",
        "qdrant_server": "NLWEB_RETRIEVAL_STORE=qdrant",
        "qdrant_edge": "NLWEB_RETRIEVAL_STORE=qdrant_edge",
        "sqlite": "NLWEB_RETRIEVAL_STORE=sqlite",
    }
    for provider, marker in expected.items():
        text = (Path("examples/provider_backends") / provider / ".env.example").read_text(
            encoding="utf-8"
        )
        assert marker in text


def test_embedding_benchmark_example_has_persistence_contract() -> None:
    run = Path("examples/embedding_benchmark/run.py").read_text(encoding="utf-8")
    assert "benchmark_results" in run
    assert "report_prefix" in run
    assert '"cli"' in run


def test_provider_envs_define_multilingual_embedding_controls() -> None:
    for provider in PROVIDERS:
        text = (Path("examples/provider_backends") / provider / ".env.example").read_text(
            encoding="utf-8"
        )
        assert "NLWEB_EMBEDDING_QUERY_PREFIX=" in text
        assert "NLWEB_EMBEDDING_DOCUMENT_PREFIX=" in text


@pytest.mark.asyncio
async def test_provider_custom_ingestion_indexes_all_declared_file_types() -> None:
    """Exercise the real CUSTOM/Haystack MultiFileConverter path over the reference corpus."""
    pytest.importorskip("haystack", reason="full provider integration requires haystack-ai")
    from examples.provider_backends.common.ingestion import ingest_directory_async

    class _CaptureStore:
        def __init__(self) -> None:
            self.documents = []

        async def upsert(self, document):
            self.documents.append(document)
            return 1

    directory = Path("examples/provider_backends/qdrant_edge/content/inbox")
    store = _CaptureStore()

    class _Embedder:
        async def embed(self, texts):
            return [[0.0] for _ in texts]

    result = await ingest_directory_async(
        directory, store, site="local-qa", embedding_provider=_Embedder()
    )
    assert result["processed"] == len(iter_source_files(directory))
    assert result["indexed"] >= len(iter_source_files(directory))
    indexed_sources = {document.metadata.get("source_file") for document in store.documents}
    assert {path.name for path in iter_source_files(directory)} <= indexed_sources


def test_docx_is_a_supported_ingestion_artifact() -> None:
    assert ".docx" in SUPPORTED_SUFFIXES
