from __future__ import annotations

import json
from pathlib import Path

import pytest

from examples.embedding_benchmark.benchmark import (
    Document,
    OllamaEmbedder,
    Query,
    bm25_search,
    evaluate_rankings,
    load_dataset,
    reciprocal_rank_fusion,
)

ROOT = Path(__file__).resolve().parents[1] / "examples" / "embedding_benchmark"


def test_benchmark_has_dedicated_inbox_and_registry() -> None:
    assert (ROOT / "inbox" / "corpus.jsonl").is_file()
    assert (ROOT / "inbox" / "queries.jsonl").is_file()
    registry = json.loads((ROOT / "nlweb-sources.json").read_text(encoding="utf-8"))
    assert registry["name"] == "embedding-benchmark-local-sources"
    assert {item["role"] for item in registry["sources"]} == {
        "retrieval-documents",
        "evaluation-queries-and-judgments",
    }
    env = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "NLWEB_BENCHMARK_RETRIEVAL_STORE=sqlite-vec" in env
    assert "NLWEB_CONTENT_SOURCES_FILE=" not in env


def test_benchmark_dataset_has_valid_cross_lingual_judgments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NLWEB_BENCHMARK_INBOX", raising=False)
    documents, queries, registry = load_dataset(ROOT)
    assert len(documents) >= 8
    assert len(queries) >= 10
    assert registry["name"] == "embedding-benchmark-local-sources"
    assert any(
        query.language == "en" and any(doc_id.startswith("fa-") for doc_id in query.relevant)
        for query in queries
    )
    assert any(
        query.language == "fa" and any(doc_id.startswith("en-") for doc_id in query.relevant)
        for query in queries
    )
    assert any(not query.answerable for query in queries)


def test_registry_cannot_escape_dedicated_inbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NLWEB_BENCHMARK_INBOX", raising=False)
    root = tmp_path / "benchmark"
    inbox = root / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "corpus.jsonl").write_text("{}\n", encoding="utf-8")
    (inbox / "queries.jsonl").write_text("{}\n", encoding="utf-8")
    registry = {
        "sources": [
            {"role": "retrieval-documents", "location": "../other/corpus.jsonl", "enabled": True},
            {
                "role": "evaluation-queries-and-judgments",
                "location": "inbox/queries.jsonl",
                "enabled": True,
            },
        ]
    }
    registry_path = root / "nlweb-sources.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(ValueError, match="escapes the dedicated inbox"):
        load_dataset(root, registry_path)


def test_bm25_normalizes_arabic_persian_letters_and_half_space() -> None:
    documents = [
        Document(
            "fa",
            "fa",
            "مشاوره مهاجرتی",
            "خدمات مشاورهمهاجرتی برای متخصصان",
            "https://example.test/fa",
        ),
        Document(
            "en",
            "en",
            "Product catalogue",
            "SKU-2048 inventory feed integration",
            "https://example.test/en",
        ),
    ]
    results = bm25_search("مشاوره مهاجرتي", documents, 2)
    assert results[0][0].id == "fa"
    assert results[0][1] > 0
    digit_results = bm25_search("SKU-۲۰۴۸", documents, 2)
    assert digit_results[0][0].id == "en"


def test_reciprocal_rank_fusion_combines_independent_rankings() -> None:
    first = Document("first", "en", "A", "alpha", "https://example.test/a")
    second = Document("second", "fa", "B", "beta", "https://example.test/b")
    result = reciprocal_rank_fusion(
        [(first, 0.1), (second, 0.2)],
        [(second, 3.0), (first, 2.0)],
        top_k=2,
    )
    assert {document.id for document, _ in result} == {"first", "second"}
    assert result[0][1] == pytest.approx(result[1][1])


def test_ranking_metrics_exclude_unanswerable_queries_and_report_false_positives() -> None:
    answerable = Query("q1", "en", "query", {"d1": 3, "d2": 1}, True)
    unanswerable = Query("q2", "fa", "no match", {}, False)
    rankings = {"q1": [("d1", 0.1), ("d2", 0.2)], "q2": [("d2", 0.2)]}
    metrics = evaluate_rankings(
        [answerable, unanswerable],
        rankings,
        max_cosine_distance=0.35,
        document_languages={"d1": "en", "d2": "fa"},
    )
    assert metrics["answerable_query_count"] == 1
    assert metrics["unanswerable_query_count"] == 1
    assert metrics["recall_at_1"] == 0.5
    assert metrics["mrr_at_10"] == 1.0
    assert metrics["no_answer_false_positive_rate"] == 1.0
    assert metrics["by_query_evidence_language"]["en->en"]["recall_at_1"] == 1.0
    assert metrics["by_query_evidence_language"]["en->fa"]["recall_at_1"] == 0.0
    assert "en" in metrics["by_query_language"]
    without_threshold = evaluate_rankings(
        [answerable, unanswerable], rankings, max_cosine_distance=None
    )
    assert without_threshold["no_answer_false_positive_rate"] is None


def test_remote_ollama_is_blocked_without_explicit_opt_in() -> None:
    with pytest.raises(ValueError, match="must be localhost"):
        OllamaEmbedder("https://example.com", "nomic-embed-text")
    assert OllamaEmbedder("http://127.0.0.1:11434", "nomic-embed-text").name == "nomic-embed-text"
    remote = OllamaEmbedder("https://example.com", "nomic-embed-text", allow_remote=True)
    assert remote.name == "nomic-embed-text"


def test_sqlite_vec_backend_dependency_is_reported_cleanly() -> None:
    try:
        import sqlite_vec  # noqa: F401
    except ImportError:
        from examples.embedding_benchmark.benchmark import SqliteVecStore

        with pytest.raises(RuntimeError, match="sqlite-vec is required"):
            SqliteVecStore(Path("unused.sqlite3"), 3)
    else:
        pytest.skip("sqlite-vec is installed; full store integration is environment-specific")


def test_runner_writes_reproducible_report_without_real_models_or_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from argparse import Namespace

    from examples.embedding_benchmark import run as run_module

    class FakeEmbedder:
        def __init__(
            self,
            model: str,
            device: str = "cpu",
            batch_size: int = 1,
            revision: str | None = None,
            trust_remote_code: bool = False,
        ) -> None:
            self.model = model
            self.revision = revision
            self.trust_remote_code = trust_remote_code

        def embed(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0, 0.0] for _ in texts]

    class FakeStore:
        def __init__(self, path: Path, dimensions: int) -> None:
            self.path = path
            self.documents = []

        def index(self, documents: list[Document], vectors: list[list[float]]) -> None:
            self.documents = documents

        def search(self, vector: list[float], top_k: int) -> list[tuple[Document, float]]:
            return [
                (document, 0.1 + index * 0.01)
                for index, document in enumerate(self.documents[:top_k])
            ]

        def close(self) -> None:
            return None

    monkeypatch.setattr(run_module, "SentenceTransformersEmbedder", FakeEmbedder)
    monkeypatch.setattr(run_module, "SqliteVecStore", FakeStore)
    monkeypatch.setattr(run_module, "_process_rss_bytes", lambda: None)
    monkeypatch.setenv("NLWEB_BENCHMARK_RESULTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("NLWEB_BENCHMARK_SQLITE_PATH", str(tmp_path / "runtime" / "bench.sqlite3"))
    for name in (
        "NLWEB_BENCHMARK_SOURCES_FILE",
        "NLWEB_BENCHMARK_INBOX",
        "NLWEB_BENCHMARK_QUERY_PREFIX",
        "NLWEB_BENCHMARK_DOCUMENT_PREFIX",
        "NLWEB_BENCHMARK_EMBEDDING_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    args = Namespace(
        backend="sentence-transformers",
        model="fake-model",
        revision=None,
        device="cpu",
        batch_size=1,
        top_k=5,
        max_cosine_distance=0.35,
        ollama_url=None,
        report_prefix="unit-test",
        trust_remote_code=False,
    )
    report_path = run_module.run(args)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["configuration"]["model"] == "fake-model"
    assert report["configuration"]["model_revision"] is None
    assert report["configuration"]["trust_remote_code"] is False
    assert report["configuration"]["retrieval_store"] == "sqlite-vec"
    assert report["configuration"]["external_hosted_apis_used"] is False
    assert set(report["tracks"]) == {"dense_sqlite_vec", "bm25", "hybrid_rrf"}
    assert report["dataset"]["corpus_sha256"]
    assert report["tracks"]["dense_sqlite_vec"]["query_count"] == 13


def test_ollama_http_error_includes_server_response_body(monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import urllib.error

    def fail_request(*args: object, **kwargs: object) -> object:
        raise urllib.error.HTTPError(
            "http://127.0.0.1:11434/api/embed",
            500,
            "Internal Server Error",
            hdrs=None,
            fp=io.BytesIO(b'{"error":"model does not support embeddings"}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", fail_request)
    embedder = OllamaEmbedder("http://127.0.0.1:11434", "multilingual-e5-small-local")
    with pytest.raises(RuntimeError, match="HTTP 500") as exc_info:
        embedder.embed(["query: test"])
    assert "model does not support embeddings" in str(exc_info.value)
    assert "ollama show" in str(exc_info.value)


def test_mteb_adapter_formats_query_and_document_inputs() -> None:

    from examples.embedding_benchmark.mteb_runner import OllamaMTEBEncoder, _texts

    assert _texts({"query": ["What is this?"], "text": ["already combined"]}, "query") == [
        "What is this?"
    ]
    assert _texts({"title": ["Title"], "body": ["Body"], "text": ["Title Body"]}, "document") == [
        "Title\nBody"
    ]

    class FakeEmbedder:
        def __init__(self) -> None:
            self.seen: list[str] = []

        def embed(self, texts: list[str]) -> list[list[float]]:
            self.seen.extend(texts)
            return [[1.0, 0.0] for _ in texts]

    encoder = OllamaMTEBEncoder.__new__(OllamaMTEBEncoder)
    encoder.name = "fake"
    encoder.model_name = "fake"
    encoder.mteb_model_meta = None
    encoder.model_prompts = {"query": "query: ", "document": "passage: "}
    encoder.query_prefix = "query: "
    encoder.document_prefix = "passage: "
    encoder.embedder = FakeEmbedder()
    encoded = encoder.encode(
        [{"query": ["where?", "query: already prefixed"]}],
        task_metadata=None,
        hf_split="test",
        hf_subset="default",
        prompt_type="query",
    )
    assert encoded.shape == (2, 2)
    assert encoder.embedder.seen == ["query: where?", "query: already prefixed"]


def test_mteb_dependency_is_optional_and_default_baseline_is_e5() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    env = (root / "examples" / "embedding_benchmark" / ".env.example").read_text(encoding="utf-8")
    mteb_env = (root / "examples" / "embedding_benchmark" / ".env.mteb.example").read_text(
        encoding="utf-8"
    )
    project = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert "NLWEB_BENCHMARK_EMBEDDING_MODEL=" not in env
    assert "NLWEB_BENCHMARK_OLLAMA_MODEL=" not in env
    assert "NLWEB_BENCHMARK_EMBEDDING_MODEL=intfloat/multilingual-e5-small" in mteb_env
    assert "NLWEB_BENCHMARK_OLLAMA_MODEL=qllama/multilingual-e5-small" in mteb_env
    assert "# benchmark-mteb = [" in project
    assert '#     "mteb>=2.2,<3",' in project
    assert '"mteb>=' not in project.split("dependencies = [", 1)[1].split("]", 1)[0]


def test_scenario_env_template_only_exposes_operational_overrides() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    env = (root / "examples" / "embedding_benchmark" / ".env.example").read_text(encoding="utf-8")
    assert "NLWEB_BENCHMARK_INBOX=inbox" in env
    assert "NLWEB_BENCHMARK_RESULTS_DIR=benchmark_results" in env
    assert "NLWEB_BENCHMARK_ALLOW_REMOTE_OLLAMA=false" in env
    for legacy_model_setting in (
        "NLWEB_BENCHMARK_EMBEDDING_BACKEND=",
        "NLWEB_BENCHMARK_EMBEDDING_MODEL=",
        "NLWEB_BENCHMARK_MODEL_REVISION=",
        "NLWEB_BENCHMARK_EMBEDDING_DEVICE=",
        "NLWEB_BENCHMARK_BATCH_SIZE=",
        "NLWEB_BENCHMARK_TOP_K=",
        "NLWEB_BENCHMARK_MAX_COSINE_DISTANCE=",
        "NLWEB_BENCHMARK_QUERY_PREFIX=",
        "NLWEB_BENCHMARK_DOCUMENT_PREFIX=",
        "NLWEB_BENCHMARK_SOURCES_FILE=",
        "NLWEB_BENCHMARK_SQLITE_PATH=",
    ):
        assert legacy_model_setting not in env


def test_nomic_optional_optimization_groups_are_separate_and_documented() -> None:
    import tomllib

    project_root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    groups = pyproject["dependency-groups"]
    assert groups["benchmark-huggingface-downloads"] == ["hf-xet>=1,<2"]
    # MegaBlocks must remain commented out of the active dependency groups: it is a
    # source-built, GPU/toolchain-sensitive optimization and not suitable for CPU-only QA.
    assert "benchmark-nomic-v2-moe-gpu" not in groups
    project_text = (project_root / "pyproject.toml").read_text(encoding="utf-8")
    assert "# benchmark-nomic-v2-moe-gpu = [" in project_text
    assert "supported NVIDIA GPU/CUDA" in project_text
    guide = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "benchmark-nomic-v2-moe-gpu" in guide
    assert "benchmark-huggingface-downloads" in guide
    assert "disabled by default" in guide.lower()


def test_vscode_tasks_cover_every_predefined_benchmark_scenario() -> None:
    import json
    import tomllib

    project_root = Path(__file__).resolve().parents[1]
    scenarios = tomllib.loads(
        (project_root / "examples/embedding_benchmark/benchmark_scenarios.toml").read_text(
            encoding="utf-8"
        )
    )["scenarios"]
    tasks = json.loads((project_root / ".vscode/tasks.json").read_text(encoding="utf-8"))["tasks"]
    task_commands = {task["command"] for task in tasks}
    assert "uv run python examples/embedding_benchmark/run.py --list-scenarios" in task_commands
    for scenario_name in scenarios:
        assert (
            f"uv run python examples/embedding_benchmark/run.py {scenario_name}" in task_commands
        ), f"Missing VS Code task for scenario {scenario_name!r}"


def test_mteb_runner_requires_explicit_tasks_before_loading_mteb() -> None:
    from argparse import Namespace

    from examples.embedding_benchmark.mteb_runner import run

    with pytest.raises(ValueError, match="Choose one or more MTEB tasks explicitly"):
        run(Namespace(tasks=None, backend="sentence-transformers", model=None, languages=None))


def test_cli_entrypoint_emits_start_and_completion_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    import sys

    from examples.embedding_benchmark import run as run_module

    matrix_json = tmp_path / "matrix.json"
    matrix_markdown = tmp_path / "matrix.md"
    monkeypatch.setattr(
        run_module,
        "run_scenario",
        lambda name: (matrix_json, matrix_markdown, tmp_path / "run.json"),
    )
    monkeypatch.setattr(sys, "argv", ["run.py", "st-e5-small"])

    run_module.main()

    output = capsys.readouterr().out
    assert "[benchmark] starting scenario=st-e5-small" in output
    assert f"[benchmark] completed successfully: comparative_json={matrix_json}" in output
    assert f"comparative_matrix={matrix_markdown}" in output


def test_nomic_model_requires_explicit_code_trust_and_uses_task_prefixes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from argparse import Namespace

    from examples.embedding_benchmark import run as run_module

    captured: dict[str, object] = {}

    class FakeEmbedder:
        def __init__(
            self,
            model: str,
            device: str = "cpu",
            batch_size: int = 1,
            revision: str | None = None,
            trust_remote_code: bool = False,
        ) -> None:
            captured["trust_remote_code"] = trust_remote_code

        def embed(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0, 0.0] for _ in texts]

    class FakeStore:
        def __init__(self, path: Path, dimensions: int) -> None:
            self.documents = []

        def index(self, documents: list[Document], vectors: list[list[float]]) -> None:
            self.documents = documents

        def search(self, vector: list[float], top_k: int) -> list[tuple[Document, float]]:
            return [(document, 0.1) for document in self.documents[:top_k]]

        def close(self) -> None:
            return None

    monkeypatch.setattr(run_module, "SentenceTransformersEmbedder", FakeEmbedder)
    monkeypatch.setattr(run_module, "SqliteVecStore", FakeStore)
    monkeypatch.setattr(run_module, "_process_rss_bytes", lambda: None)
    monkeypatch.setenv("NLWEB_BENCHMARK_RESULTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("NLWEB_BENCHMARK_SQLITE_PATH", str(tmp_path / "runtime" / "bench.sqlite3"))
    monkeypatch.delenv("NLWEB_BENCHMARK_QUERY_PREFIX", raising=False)
    monkeypatch.delenv("NLWEB_BENCHMARK_DOCUMENT_PREFIX", raising=False)
    monkeypatch.delenv("NLWEB_BENCHMARK_EMBEDDING_MODEL", raising=False)
    args = Namespace(
        backend="sentence-transformers",
        model="nomic-ai/nomic-embed-text-v2-moe",
        revision=None,
        device="cpu",
        batch_size=1,
        top_k=5,
        max_cosine_distance=0.35,
        ollama_url=None,
        report_prefix="nomic-test",
        trust_remote_code=True,
    )
    report_path = run_module.run(args)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    config = report["configuration"]
    assert captured["trust_remote_code"] is True
    assert config["trust_remote_code"] is True
    assert config["document_prefix"] == "search_document: "
    assert config["query_prefix"] == "search_query: "


def test_nomic_model_reports_optional_dependency_before_model_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib.util

    from examples.embedding_benchmark.benchmark import SentenceTransformersEmbedder

    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name: None if name == "einops" else object()
    )
    with pytest.raises(RuntimeError, match="uv sync --group benchmark-nomic-v2-moe"):
        SentenceTransformersEmbedder("nomic-ai/nomic-embed-text-v2-moe", trust_remote_code=True)


def test_nomic_dependency_group_is_optional_and_documented() -> None:
    import tomllib

    project_root = ROOT.parents[1]
    pyproject = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["dependency-groups"]["benchmark-nomic-v2-moe"] == ["einops>=0.8,<1"]
    assert "benchmark-nomic-v2-moe" not in pyproject["dependency-groups"].get("dev", [])
    guide = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "uv sync --group benchmark-nomic-v2-moe" in guide


def test_scenario_catalogue_has_all_single_pair_and_all_three_sentence_transformers_combinations() -> (
    None
):
    from examples.embedding_benchmark.run import load_scenarios

    config = load_scenarios()
    scenarios = config["scenarios"]
    expected = {
        "st-e5-small",
        "st-multilingual-minilm",
        "st-nomic-v2-moe",
        "st-e5-small-plus-minilm",
        "st-e5-small-plus-nomic",
        "st-minilm-plus-nomic",
        "st-all-three",
        "ollama-nomic-v2-moe",
        "compare-nomic-v2-moe-embedders",
    }
    assert expected <= set(scenarios)
    assert len(scenarios["st-all-three"]["runs"]) == 3
    assert len(scenarios["st-e5-small-plus-nomic"]["runs"]) == 2
    nomic = next(run for run in scenarios["st-nomic-v2-moe"]["runs"] if "nomic-ai/" in run["model"])
    assert nomic["trust_remote_code"] is True
    compare = scenarios["compare-nomic-v2-moe-embedders"]
    assert len(compare["runs"]) == 2
    assert len({run["backend"] for run in compare["runs"]}) == 2
    assert len({run["model_family"] for run in compare["runs"]}) == 1


def test_source_registry_supports_explicit_custom_jsonl_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NLWEB_BENCHMARK_INBOX", raising=False)
    root = tmp_path / "benchmark"
    inbox = root / "inbox"
    inbox.mkdir(parents=True)
    external = tmp_path / "customer-data"
    external.mkdir()
    (external / "corpus.jsonl").write_text(
        json.dumps(
            {
                "id": "d1",
                "language": "en",
                "title": "Evidence",
                "text": "domain evidence",
                "source_uri": "https://example.test/d1",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (external / "queries.jsonl").write_text(
        json.dumps(
            {
                "id": "q1",
                "language": "en",
                "text": "domain query",
                "relevant": {"d1": 3},
                "answerable": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    registry = {
        "sources": [
            {
                "name": "domain-corpus",
                "kind": "jsonl",
                "location": str(external / "corpus.jsonl"),
                "enabled": True,
                "role": "retrieval-documents",
                "allow_external_path": True,
            },
            {
                "name": "benchmark-queries",
                "kind": "jsonl",
                "location": str(external / "queries.jsonl"),
                "enabled": True,
                "role": "evaluation-queries-and-judgments",
                "allow_external_path": True,
            },
        ]
    }
    registry_path = root / "sources.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    docs, queries, _ = load_dataset(
        root,
        registry_path,
        corpus_source_name="domain-corpus",
        query_source_name="benchmark-queries",
    )
    assert [doc.id for doc in docs] == ["d1"]
    assert [query.id for query in queries] == ["q1"]


def test_comparative_matrix_ranks_primary_metric_and_writes_recommendation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from examples.embedding_benchmark import run as run_module

    def report(path: Path, name: str, score: float) -> Path:
        payload = {
            "configuration": {
                "scenario_run_name": name,
                "embedding_backend": "sentence-transformers",
                "model": name,
                "model_family": "family",
                "model_revision": None,
                "trust_remote_code": False,
            },
            "embedding": {"dimensions": 3, "document_embedding_ms": 10, "query_embedding_ms": 2},
            "memory": {"observed_max_rss_bytes": 100},
            "tracks": {
                "hybrid_rrf": {
                    "recall_at_1": score,
                    "recall_at_5": score,
                    "mrr_at_10": score,
                    "ndcg_at_10": score,
                    "precision_at_10": score,
                },
                "bm25": {},
                "dense_sqlite_vec": {},
            },
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    monkeypatch.setenv("NLWEB_BENCHMARK_RESULTS_DIR", str(tmp_path))
    first = report(tmp_path / "first.json", "lower", 0.4)
    second = report(tmp_path / "second.json", "higher", 0.8)
    json_path, md_path = run_module._write_comparative_matrix(
        "test-scenario",
        {"type": "models_one_embedder", "primary_metric": "tracks.hybrid_rrf.ndcg_at_10"},
        [first, second],
    )
    result = json.loads(json_path.read_text(encoding="utf-8"))
    assert result["runs"][0]["run_name"] == "higher"
    assert "provisional recommendation" in result["recommendation"]
    assert "higher" in md_path.read_text(encoding="utf-8")


def test_run_scenario_orchestrates_runs_and_emits_comparison_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from examples.embedding_benchmark import run as run_module

    scenario_file = tmp_path / "scenarios.toml"
    scenario_file.write_text(
        """[scenario_types.models_one_embedder]
title = \"sweep\"
"""
        """[scenario_types.two_embedders_one_model_family]
title = \"pair\"
"""
        """[scenarios.test-sweep]
type = \"models_one_embedder\"
source_registry = \"nlweb-sources.json\"
corpus_source = \"benchmark-corpus\"
query_source = \"benchmark-queries\"
primary_metric = \"tracks.hybrid_rrf.ndcg_at_10\"
"""
        """[[scenarios.test-sweep.runs]]
name = \"fake\"
backend = \"sentence-transformers\"
model = \"fake-model\"
""",
        encoding="utf-8",
    )
    results = tmp_path / "results"
    monkeypatch.setenv("NLWEB_BENCHMARK_RESULTS_DIR", str(results))

    def fake_run_one(args: object) -> Path:
        path = results / f"{args.report_prefix}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "configuration": {
                        "embedding_backend": args.backend,
                        "model": args.model,
                        "model_revision": None,
                        "trust_remote_code": False,
                    },
                    "embedding": {
                        "dimensions": 3,
                        "document_embedding_ms": 10,
                        "query_embedding_ms": 2,
                    },
                    "memory": {"observed_max_rss_bytes": 100},
                    "tracks": {
                        "dense_sqlite_vec": {"ndcg_at_10": 0.5},
                        "bm25": {"ndcg_at_10": 0.3},
                        "hybrid_rrf": {
                            "recall_at_1": 0.5,
                            "recall_at_5": 0.6,
                            "mrr_at_10": 0.7,
                            "ndcg_at_10": 0.8,
                            "precision_at_10": 0.4,
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        return path

    monkeypatch.setattr(run_module, "run_one", fake_run_one)
    matrix_json, matrix_md, last_report = run_module.run_scenario("test-sweep", scenario_file)
    assert last_report.is_file()
    assert matrix_json.is_file()
    assert matrix_md.is_file()
    payload = json.loads(matrix_json.read_text(encoding="utf-8"))
    assert payload["runs"][0]["run_name"] == "fake"
    assert payload["runs"][0]["primary_metric"] == pytest.approx(0.8)
    persisted_run = json.loads(last_report.read_text(encoding="utf-8"))
    assert persisted_run["configuration"]["invocation_source"] == "cli"
    assert persisted_run["configuration"]["scenario_name"] == "test-sweep"
    assert "provisional recommendation" in payload["recommendation"]
