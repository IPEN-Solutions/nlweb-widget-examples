"""Run the isolated local English/Persian retrieval benchmark."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import sqlite3
import sys
import time
import tomllib
from datetime import UTC, datetime
from pathlib import Path

# Direct script execution sets sys.path[0] to this example directory, not the workspace root.
WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from dotenv import load_dotenv  # noqa: E402

from examples.embedding_benchmark.benchmark import (  # noqa: E402
    OllamaEmbedder,
    SentenceTransformersEmbedder,
    SqliteVecStore,
    bm25_search,
    evaluate_rankings,
    load_dataset,
    percentile,
    reciprocal_rank_fusion,
    timed_embed,
)

ROOT = Path(__file__).resolve().parent


def _env_path(name: str, default: str) -> Path:
    value = Path(os.getenv(name, default)).expanduser()
    return value if value.is_absolute() else (ROOT / value).resolve()


def _process_rss_bytes() -> int | None:
    try:
        import psutil
    except ImportError:
        return None
    try:
        return int(psutil.Process().memory_info().rss)
    except (psutil.Error, OSError):
        return None


def _package_version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_one(args: argparse.Namespace) -> Path:
    load_dotenv(ROOT / ".env", override=False)
    store_name = os.getenv("NLWEB_BENCHMARK_RETRIEVAL_STORE", "sqlite-vec").casefold()
    if store_name != "sqlite-vec":
        raise ValueError(
            "This mutation iteration supports sqlite-vec only; it is the explicit default "
            "and no remote store is configured."
        )
    registry_path = _env_path("NLWEB_BENCHMARK_SOURCES_FILE", "nlweb-sources.json")
    if not registry_path.is_file():
        raise FileNotFoundError(f"Benchmark source registry not found: {registry_path}")
    print(f"[benchmark] registry={registry_path}", flush=True)
    documents, queries, registry = load_dataset(
        ROOT,
        registry_path,
        corpus_source_name=getattr(args, "corpus_source", None),
        query_source_name=getattr(args, "query_source", None),
    )
    print(
        f"[benchmark] dataset loaded: documents={len(documents)} queries={len(queries)}",
        flush=True,
    )
    backend = args.backend or os.getenv(
        "NLWEB_BENCHMARK_EMBEDDING_BACKEND", "sentence-transformers"
    )
    default_model = (
        os.getenv("NLWEB_BENCHMARK_OLLAMA_MODEL", "nomic-embed-text")
        if backend == "ollama"
        else os.getenv(
            "NLWEB_BENCHMARK_EMBEDDING_MODEL",
            "intfloat/multilingual-e5-small",
        )
    )
    model = args.model or default_model
    device = args.device or os.getenv("NLWEB_BENCHMARK_EMBEDDING_DEVICE", "cpu")
    model_revision = (
        args.revision or os.getenv("NLWEB_BENCHMARK_MODEL_REVISION", "").strip() or None
    )
    batch_size = args.batch_size or int(os.getenv("NLWEB_BENCHMARK_BATCH_SIZE", "1"))
    top_k = args.top_k or int(os.getenv("NLWEB_BENCHMARK_TOP_K", "5"))
    max_distance = (
        args.max_cosine_distance
        if args.max_cosine_distance is not None
        else float(os.getenv("NLWEB_BENCHMARK_MAX_COSINE_DISTANCE", "0.35"))
    )
    print(
        f"[benchmark] initializing backend={backend} model={model} device={device}",
        flush=True,
    )
    backend_started = time.perf_counter()
    trust_remote_code = bool(getattr(args, "trust_remote_code", False))
    if backend == "sentence-transformers":
        embedder = SentenceTransformersEmbedder(
            model,
            device=device,
            batch_size=batch_size,
            revision=model_revision,
            trust_remote_code=trust_remote_code,
        )
    elif backend == "ollama":
        allow_remote = os.getenv("NLWEB_BENCHMARK_ALLOW_REMOTE_OLLAMA", "false").casefold() in {
            "1",
            "true",
            "yes",
        }
        ollama_url = args.ollama_url or os.getenv(
            "NLWEB_BENCHMARK_OLLAMA_URL", "http://127.0.0.1:11434"
        )
        embedder = OllamaEmbedder(ollama_url, model, allow_remote=allow_remote)
    else:
        raise ValueError(f"Unsupported embedding backend: {backend}")

    backend_init_ms = (time.perf_counter() - backend_started) * 1000
    rss_samples = {"after_backend_initialization": _process_rss_bytes()}
    document_prefix = (
        getattr(args, "document_prefix", None)
        if getattr(args, "document_prefix", None) is not None
        else os.getenv("NLWEB_BENCHMARK_DOCUMENT_PREFIX", "")
    )
    query_prefix = (
        getattr(args, "query_prefix", None)
        if getattr(args, "query_prefix", None) is not None
        else os.getenv("NLWEB_BENCHMARK_QUERY_PREFIX", "")
    )
    model_key = model.casefold()
    if "nomic-embed-text-v2-moe" in model_key:
        # The model card specifies task prefixes. Replace the example's E5 defaults
        # when the user switches models, while preserving other explicit prefixes.
        if document_prefix in {"", "passage: "}:
            document_prefix = "search_document: "
        if query_prefix in {"", "query: "}:
            query_prefix = "search_query: "
    elif "multilingual-e5" in model_key:
        document_prefix = document_prefix or "passage: "
        query_prefix = query_prefix or "query: "
    document_texts = [f"{document_prefix}{doc.title}\n{doc.text}" for doc in documents]
    query_texts = [f"{query_prefix}{query.text}" for query in queries]
    print("[benchmark] embedding corpus documents", flush=True)
    doc_vectors, doc_embedding_ms = timed_embed(embedder, document_texts)
    rss_samples["after_document_embeddings"] = _process_rss_bytes()
    print("[benchmark] embedding evaluation queries", flush=True)
    query_vectors, query_embedding_ms = timed_embed(embedder, query_texts)
    rss_samples["after_query_embeddings"] = _process_rss_bytes()
    if not doc_vectors or not query_vectors:
        raise ValueError("The benchmark corpus and query set must not be empty")
    dimensions = len(doc_vectors[0])
    if any(len(vector) != dimensions for vector in doc_vectors + query_vectors):
        raise ValueError("Embedding backend returned inconsistent vector dimensions")

    db_path = _env_path("NLWEB_BENCHMARK_SQLITE_PATH", "runtime/benchmark.sqlite3")
    print(f"[benchmark] indexing {len(documents)} documents in {db_path}", flush=True)
    store = SqliteVecStore(db_path, dimensions)
    try:
        started = time.perf_counter()
        store.index(documents, doc_vectors)
        indexing_ms = (time.perf_counter() - started) * 1000
        rss_samples["after_sqlite_indexing"] = _process_rss_bytes()
        vector_rankings: dict[str, list[tuple[str, float]]] = {}
        hybrid_rankings: dict[str, list[tuple[str, float]]] = {}
        vector_latencies: list[float] = []
        hybrid_latencies: list[float] = []
        lexical_rankings: dict[str, list[tuple[str, float]]] = {}
        for query, vector in zip(queries, query_vectors, strict=True):
            started = time.perf_counter()
            found = store.search(vector, max(top_k, 10))
            vector_latencies.append((time.perf_counter() - started) * 1000)
            vector_rankings[query.id] = [(doc.id, distance) for doc, distance in found]
            lexical = bm25_search(query.text, documents, max(top_k, 10))
            lexical_rankings[query.id] = [(doc.id, score) for doc, score in lexical]
            started = time.perf_counter()
            hybrid = reciprocal_rank_fusion(found, lexical, top_k=max(top_k, 10))
            hybrid_latencies.append((time.perf_counter() - started) * 1000)
            hybrid_rankings[query.id] = [(doc.id, score) for doc, score in hybrid]
    finally:
        store.close()

    # The threshold applies only to dense cosine distances; RRF scores use a different scale.
    document_languages = {document.id: document.language for document in documents}
    dense_metrics = evaluate_rankings(
        queries, vector_rankings, max(top_k, 10), max_distance, document_languages
    )
    lexical_metrics = evaluate_rankings(
        queries, lexical_rankings, max(top_k, 10), None, document_languages
    )
    hybrid_metrics = evaluate_rankings(
        queries, hybrid_rankings, max(top_k, 10), None, document_languages
    )
    results_dir = _env_path("NLWEB_BENCHMARK_RESULTS_DIR", "benchmark_results")
    results_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d_%H-%M-%S")
    report_path = results_dir / f"{args.report_prefix}.{timestamp}.json"
    inbox_path = _env_path("NLWEB_BENCHMARK_INBOX", "inbox")
    source_entries = {
        item.get("name"): item for item in registry.get("sources", []) if item.get("enabled")
    }

    def registered_source_path(source_name: str, role: str) -> Path:
        source = source_entries.get(source_name)
        if source is None:
            source = next(
                item
                for item in registry.get("sources", [])
                if item.get("role") == role and item.get("enabled")
            )
        location = Path(source["location"])
        if location.is_absolute():
            return location
        if location.parts and location.parts[0] == "inbox":
            return (inbox_path / Path(*location.parts[1:])).resolve()
        return (registry_path.parent / location).resolve()

    corpus_path = registered_source_path(
        getattr(args, "corpus_source", None) or "benchmark-corpus", "retrieval-documents"
    )
    queries_path = registered_source_path(
        getattr(args, "query_source", None) or "benchmark-queries",
        "evaluation-queries-and-judgments",
    )
    payload = {
        "schema_version": "2.0",
        "created_at": datetime.now(UTC).isoformat(),
        "runner": "embedding_benchmark",
        "benchmark_version": "0.1.8.dev1",
        "dataset": {
            "registry": str(registry_path),
            "registry_name": registry.get("name"),
            "corpus_path": str(corpus_path),
            "corpus_sha256": _file_sha256(corpus_path),
            "query_path": str(queries_path),
            "query_sha256": _file_sha256(queries_path),
            "document_count": len(documents),
            "query_count": len(queries),
        },
        "configuration": {
            "embedding_backend": backend,
            "model": model,
            "model_revision": model_revision if backend == "sentence-transformers" else None,
            "trust_remote_code": trust_remote_code if backend == "sentence-transformers" else False,
            "device": device,
            "batch_size": batch_size,
            "retrieval_store": store_name,
            "sqlite_path": str(db_path),
            "top_k": top_k,
            "max_cosine_distance": max_distance,
            "corpus_source": getattr(args, "corpus_source", None) or "benchmark-corpus",
            "query_source": getattr(args, "query_source", None) or "benchmark-queries",
            "query_prefix": query_prefix,
            "document_prefix": document_prefix,
            "similarity_metric": "cosine distance",
            "sentence_transformers_normalizes_embeddings": backend == "sentence-transformers",
            "external_hosted_apis_used": False,
        },
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "sqlite": sqlite3.sqlite_version,
            "sentence_transformers": _package_version("sentence-transformers"),
            "sqlite_vec": _package_version("sqlite-vec"),
            "numpy": _package_version("numpy"),
            "nlweb_widget": _package_version("nlweb-widget"),
        },
        "embedding": {
            "backend_initialization_ms": backend_init_ms,
            "dimensions": dimensions,
            "document_embedding_ms": doc_embedding_ms,
            "query_embedding_ms": query_embedding_ms,
        },
        "memory": {
            "rss_samples_bytes": rss_samples,
            "observed_max_rss_bytes": max(
                (value for value in rss_samples.values() if value is not None),
                default=None,
            ),
            "measurement_note": (
                "RSS snapshots are sampled phase checkpoints, not a continuously sampled "
                "process peak; values are null when psutil is unavailable."
            ),
        },
        "index": {
            "indexing_ms": indexing_ms,
            "database_size_bytes": db_path.stat().st_size if db_path.exists() else None,
        },
        "retrieval_latency_ms": {
            "dense_p50": percentile(vector_latencies, 0.50),
            "dense_p95": percentile(vector_latencies, 0.95),
            "hybrid_p50": percentile(hybrid_latencies, 0.50),
            "hybrid_p95": percentile(hybrid_latencies, 0.95),
        },
        "tracks": {
            "dense_sqlite_vec": dense_metrics,
            "bm25": lexical_metrics,
            "hybrid_rrf": hybrid_metrics,
        },
    }
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"backend={backend} model={model} store={store_name} dimensions={dimensions}")
    for name, metrics in payload["tracks"].items():
        print(
            f"{name}: Recall@1={metrics['recall_at_1']:.3f} "
            f"Recall@5={metrics['recall_at_5']:.3f} "
            f"MRR@10={metrics['mrr_at_10']:.3f} "
            f"nDCG@10={metrics['ndcg_at_10']:.3f}"
        )
    print(f"report={report_path}")
    return report_path


SCENARIOS_PATH = ROOT / "benchmark_scenarios.toml"


def load_scenarios(path: Path = SCENARIOS_PATH) -> dict[str, object]:
    """Load and validate the workspace-owned scenario catalogue."""
    with path.open("rb") as stream:
        config = tomllib.load(stream)
    scenario_types = config.get("scenario_types", {})
    scenarios = config.get("scenarios", {})
    if not isinstance(scenario_types, dict) or not isinstance(scenarios, dict) or not scenarios:
        raise ValueError(f"Scenario file must define scenario_types and scenarios: {path}")
    for name, scenario in scenarios.items():
        if not isinstance(scenario, dict):
            raise ValueError(f"Scenario {name!r} must be a TOML table")
        scenario_type = scenario.get("type")
        if scenario_type not in scenario_types:
            raise ValueError(f"Scenario {name!r} references unknown type {scenario_type!r}")
        runs = scenario.get("runs")
        if not isinstance(runs, list) or not runs:
            raise ValueError(f"Scenario {name!r} must define one or more [[runs]] entries")
        if (
            scenario_type == "models_one_embedder"
            and len({item.get("backend") for item in runs}) != 1
        ):
            raise ValueError(f"Scenario {name!r} must use one embedder/backend for every model")
        if scenario_type == "two_embedders_one_model_family":
            if len(runs) != 2 or len({item.get("backend") for item in runs}) != 2:
                raise ValueError(f"Scenario {name!r} must compare exactly two different embedders")
            families = {item.get("model_family") for item in runs}
            if len(families) != 1 or None in families:
                raise ValueError(
                    f"Scenario {name!r} must declare the same model_family for both runs"
                )
        for run_config in runs:
            if run_config.get("backend") not in {"sentence-transformers", "ollama"}:
                raise ValueError(
                    f"Scenario {name!r} has unsupported backend {run_config.get('backend')!r}"
                )
            if not run_config.get("model"):
                raise ValueError(f"Scenario {name!r} has a run without model")
            if (
                run_config.get("trust_remote_code", False)
                and run_config.get("backend") != "sentence-transformers"
            ):
                raise ValueError("trust_remote_code is only valid for sentence-transformers runs")
    return config


def _metric_value(report: dict[str, object], metric_path: str) -> float | None:
    current: object = report
    for part in metric_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return float(current) if isinstance(current, (float, int)) else None


def _write_comparative_matrix(
    scenario_name: str,
    scenario: dict[str, object],
    report_paths: list[Path],
) -> tuple[Path, Path]:
    results_dir = _env_path("NLWEB_BENCHMARK_RESULTS_DIR", "benchmark_results")
    results_dir.mkdir(parents=True, exist_ok=True)
    metric_path = str(scenario.get("primary_metric", "tracks.hybrid_rrf.ndcg_at_10"))
    rows: list[dict[str, object]] = []
    for report_path in report_paths:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        config = report["configuration"]
        tracks = report["tracks"]
        row: dict[str, object] = {
            "run_name": config.get("scenario_run_name", report_path.stem),
            "backend": config["embedding_backend"],
            "model": config["model"],
            "model_family": config.get("model_family"),
            "revision": config.get("model_revision"),
            "trust_remote_code": config.get("trust_remote_code", False),
            "dimensions": report["embedding"]["dimensions"],
            "document_embedding_ms": report["embedding"]["document_embedding_ms"],
            "query_embedding_ms": report["embedding"]["query_embedding_ms"],
            "observed_max_rss_bytes": report["memory"]["observed_max_rss_bytes"],
            "report_path": str(report_path),
            "primary_metric": _metric_value(report, metric_path),
            "tracks": {
                track: {
                    key: metrics.get(key)
                    for key in (
                        "recall_at_1",
                        "recall_at_5",
                        "mrr_at_10",
                        "ndcg_at_10",
                        "precision_at_10",
                    )
                }
                for track, metrics in tracks.items()
            },
        }
        rows.append(row)
    rows.sort(
        key=lambda row: (row["primary_metric"] is not None, row["primary_metric"] or -1.0),
        reverse=True,
    )
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
    recommended = rows[0] if rows and rows[0]["primary_metric"] is not None else None
    recommendation = (
        f"Best observed result for this scenario: {recommended['run_name']} "
        f"({recommended['backend']} / {recommended['model']}) with {metric_path}="
        f"{recommended['primary_metric']:.4f}. This is a provisional recommendation only: "
        "the included corpus is a small evaluation seed, so validate on a larger, held-out, "
        "domain-specific judged dataset before production selection."
        if recommended
        else "No recommendation could be computed because the configured primary metric was missing."
    )
    created_at = datetime.now(UTC).isoformat()
    matrix = {
        "schema_version": "1.0",
        "scenario": scenario_name,
        "scenario_type": scenario["type"],
        "created_at": created_at,
        "primary_metric": metric_path,
        "recommendation": recommendation,
        "runs": rows,
    }
    stamp = datetime.now(UTC).strftime("%Y-%m-%d_%H-%M-%S")
    stem = f"scenario-{scenario_name}.{stamp}"
    json_path = results_dir / f"{stem}.json"
    markdown_path = results_dir / f"{stem}.md"
    json_path.write_text(json.dumps(matrix, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    columns = [
        "Rank",
        "Run",
        "Embedder",
        "Model",
        "Dense nDCG@10",
        "BM25 nDCG@10",
        "Hybrid Recall@5",
        "Hybrid MRR@10",
        "Hybrid nDCG@10",
        "Embedding ms",
    ]
    lines = [
        f"# Benchmark comparison: {scenario_name}",
        "",
        f"Primary ranking metric: `{metric_path}`",
        "",
        "| " + " | ".join(columns) + " |",
        "|" + "|".join(["---"] * len(columns)) + "|",
    ]
    for row in rows:
        dense = row["tracks"].get("dense_sqlite_vec", {})
        bm25 = row["tracks"].get("bm25", {})
        hybrid = row["tracks"].get("hybrid_rrf", {})

        def fmt(value: object) -> str:
            return f"{value:.4f}" if isinstance(value, (int, float)) else "—"

        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["rank"]),
                    str(row["run_name"]),
                    str(row["backend"]),
                    str(row["model"]),
                    fmt(dense.get("ndcg_at_10")),
                    fmt(bm25.get("ndcg_at_10")),
                    fmt(hybrid.get("recall_at_5")),
                    fmt(hybrid.get("mrr_at_10")),
                    fmt(hybrid.get("ndcg_at_10")),
                    fmt((row["document_embedding_ms"] or 0) + (row["query_embedding_ms"] or 0)),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            recommendation,
            "",
            "## Interpretation",
            "",
            "Compare only runs using the same corpus, query set, relevance judgments, retrieval store, and metric definitions. Cross-embedder results use each model's required prefixes; the Ollama quantization and Sentence Transformers weights are not bit-identical artifacts. Embedding time is shown separately from retrieval quality. The first-ranked run is the best observed score for the configured primary metric, not a universal production winner.",
            "",
        ]
    )
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, markdown_path


def run_scenario(
    scenario_name: str, scenario_file: Path = SCENARIOS_PATH
) -> tuple[Path, Path, Path]:
    load_dotenv(ROOT / ".env", override=False)
    config = load_scenarios(scenario_file)
    scenarios = config["scenarios"]
    if scenario_name not in scenarios:
        choices = ", ".join(sorted(scenarios))
        raise ValueError(f"Unknown scenario {scenario_name!r}. Available scenarios: {choices}")
    scenario = scenarios[scenario_name]
    base_env = os.environ.copy()
    report_paths: list[Path] = []
    try:
        for index, run_config in enumerate(scenario["runs"], 1):
            # Each run gets a fresh local SQLite index and a fully specified runtime profile.
            registry = str((ROOT / scenario.get("source_registry", "nlweb-sources.json")).resolve())
            os.environ["NLWEB_BENCHMARK_SOURCES_FILE"] = registry
            os.environ["NLWEB_BENCHMARK_SQLITE_PATH"] = str(
                _env_path("NLWEB_BENCHMARK_RESULTS_DIR", "benchmark_results")
                / "indexes"
                / f"{scenario_name}-{index}.sqlite3"
            )
            os.environ["NLWEB_BENCHMARK_EMBEDDING_BACKEND"] = run_config["backend"]
            os.environ["NLWEB_BENCHMARK_EMBEDDING_MODEL"] = run_config["model"]
            os.environ["NLWEB_BENCHMARK_OLLAMA_MODEL"] = run_config["model"]
            os.environ["NLWEB_BENCHMARK_MODEL_REVISION"] = str(run_config.get("revision", ""))
            os.environ["NLWEB_BENCHMARK_DOCUMENT_PREFIX"] = str(
                run_config.get("document_prefix", "")
            )
            os.environ["NLWEB_BENCHMARK_QUERY_PREFIX"] = str(run_config.get("query_prefix", ""))
            args = argparse.Namespace(
                backend=run_config["backend"],
                model=run_config["model"],
                revision=run_config.get("revision"),
                device=run_config.get("device", "cpu"),
                batch_size=int(run_config.get("batch_size", 1)),
                top_k=int(scenario.get("top_k", 5)),
                max_cosine_distance=float(scenario.get("max_cosine_distance", 0.35)),
                ollama_url=run_config.get("ollama_url"),
                report_prefix=f"{scenario_name}-{run_config.get('name', index)}",
                trust_remote_code=bool(run_config.get("trust_remote_code", False)),
                document_prefix=str(run_config.get("document_prefix", "")),
                query_prefix=str(run_config.get("query_prefix", "")),
                corpus_source=str(scenario.get("corpus_source", "benchmark-corpus")),
                query_source=str(scenario.get("query_source", "benchmark-queries")),
            )
            print(
                f"[benchmark] scenario={scenario_name} run={run_config.get('name', index)} ({index}/{len(scenario['runs'])})",
                flush=True,
            )
            report_path = run_one(args)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            # Preserve the existing persistence contract: each scenario-run report
            # records that it was produced through the scenario CLI workflow.
            report["configuration"]["invocation_source"] = "cli"
            report["configuration"]["scenario_name"] = scenario_name
            report["configuration"]["scenario_run_name"] = run_config.get("name", f"run-{index}")
            report["configuration"]["model_family"] = run_config.get("model_family")
            report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            report_paths.append(report_path)
    finally:
        os.environ.clear()
        os.environ.update(base_env)
    matrix_json, matrix_markdown = _write_comparative_matrix(scenario_name, scenario, report_paths)
    print(f"[benchmark] comparative_json={matrix_json}", flush=True)
    print(f"[benchmark] comparative_matrix={matrix_markdown}", flush=True)
    return matrix_json, matrix_markdown, report_paths[-1]


def run(args: argparse.Namespace):
    scenario_name = getattr(args, "scenario", None)
    if scenario_name:
        return run_scenario(scenario_name)
    # Kept for unit tests and internal single-run composition; CLI uses scenarios only.
    return run_one(args)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a predefined workspace-owned embedding benchmark scenario."
    )
    parser.add_argument("scenario", nargs="?", help="Scenario name from benchmark_scenarios.toml")
    parser.add_argument(
        "--list-scenarios", action="store_true", help="List configured scenario names and types"
    )
    args = parser.parse_args()
    try:
        config = load_scenarios()
        if args.list_scenarios:
            for name, scenario in sorted(config["scenarios"].items()):
                print(f"{name}\t{scenario['type']}\t{scenario.get('description', '')}")
            return
        if not args.scenario:
            parser.error("provide a scenario name, or use --list-scenarios")
        print(f"[benchmark] starting scenario={args.scenario}", flush=True)
        matrix_json, matrix_markdown, _ = run_scenario(args.scenario)
        print(
            f"[benchmark] completed successfully: comparative_json={matrix_json} "
            f"comparative_matrix={matrix_markdown}",
            flush=True,
        )
    except Exception as exc:
        print(f"[benchmark] FAILED: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        raise


if __name__ == "__main__":
    main()
