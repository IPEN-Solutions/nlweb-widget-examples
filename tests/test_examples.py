from pathlib import Path


def test_all_reference_examples_exist() -> None:
    expected = {
        "fastapi_retail",
        "flask_marketing",
        "django_services",
        "starlette_catalog",
        "stdlib_directory",
    }
    actual = {
        path.name
        for path in Path("examples").iterdir()
        if path.is_dir() and not path.name.startswith("__")
    }
    assert expected <= actual


def test_new_capability_examples_are_present() -> None:
    assert Path("examples/provider_backends/qdrant_edge/app.py").is_file()
    assert Path("examples/provider_backends/qdrant_edge/.env.example").is_file()
    assert Path("examples/provider_backends/sqlite/app.py").is_file()
    assert Path("examples/provider_backends/sqlite/.env.example").is_file()
    assert Path("examples/embedding_benchmark/run.py").is_file()
    assert "SqliteVecStore" in Path("examples/embedding_benchmark/run.py").read_text(
        encoding="utf-8"
    )


def test_provider_examples_use_haystack_multifile_for_custom_unstructured_sources() -> None:
    ingestion = Path("examples/provider_backends/common/ingestion.py").read_text(encoding="utf-8")
    assert "MultiFileConverter" in ingestion
    assert "ContentSourceKind.CUSTOM" in ingestion
    assert 'source_type": "haystack-multifile"' in ingestion
