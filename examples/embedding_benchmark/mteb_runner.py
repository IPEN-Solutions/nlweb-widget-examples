"""Optional MTEB public-task runner; only runs when explicitly invoked."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from dotenv import load_dotenv

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from examples.embedding_benchmark.benchmark import OllamaEmbedder  # noqa: E402

ROOT = Path(__file__).resolve().parent


def _texts(batch: dict[str, Any], prompt_type: Any) -> list[str]:
    """Extract text from MTEB's batched text/query/corpus inputs in stable order."""
    prompt = getattr(prompt_type, "value", prompt_type)
    if prompt == "query" and batch.get("query") is not None:
        values = batch["query"]
    elif prompt == "document" and batch.get("body") is not None:
        bodies = batch["body"]
        titles = batch.get("title") or [""] * len(bodies)
        values = [f"{title}\n{body}".strip() for title, body in zip(titles, bodies, strict=True)]
    elif batch.get("text") is not None:
        values = batch["text"]
    elif batch.get("query") is not None:
        values = batch["query"]
    elif batch.get("body") is not None:
        bodies = batch["body"]
        titles = batch.get("title") or [""] * len(bodies)
        values = [f"{title}\n{body}".strip() for title, body in zip(titles, bodies, strict=True)]
    else:
        raise ValueError(f"Unsupported MTEB text batch fields: {sorted(batch)}")
    if isinstance(values, str):
        return [values]
    return [str(value) for value in values]


class OllamaMTEBEncoder:
    """MTEB EncoderProtocol-compatible adapter for an explicitly local Ollama model."""

    def __init__(
        self,
        model_name: str,
        revision: str | None = None,
        *,
        device: str | None = None,
        base_url: str = "http://127.0.0.1:11434",
        allow_remote: bool = False,
        query_prefix: str = "query: ",
        document_prefix: str = "passage: ",
        **_: Any,
    ) -> None:
        del revision, device
        self.name = model_name
        self.model_name = model_name
        self.mteb_model_meta = None
        self.model_prompts = {"query": query_prefix, "document": document_prefix}
        self.query_prefix = query_prefix
        self.document_prefix = document_prefix
        self.embedder = OllamaEmbedder(base_url, model_name, allow_remote=allow_remote)

    @staticmethod
    def _prefix(text: str, prefix: str) -> str:
        return text if not prefix or text.startswith(prefix) else prefix + text

    def encode(
        self,
        inputs: Any,
        *,
        task_metadata: Any,
        hf_split: str,
        hf_subset: str,
        prompt_type: Any = None,
        **kwargs: Any,
    ) -> np.ndarray:
        del task_metadata, hf_split, hf_subset, kwargs
        prompt = getattr(prompt_type, "value", prompt_type)
        prefix = self.document_prefix if prompt == "document" else self.query_prefix
        texts: list[str] = []
        for batch in inputs:
            texts.extend(self._prefix(value, prefix) for value in _texts(batch, prompt_type))
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        return np.asarray(self.embedder.embed(texts), dtype=np.float32)


def _version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def run(args: argparse.Namespace) -> Path:
    load_dotenv(ROOT / ".env", override=False)
    load_dotenv(ROOT / ".env.mteb", override=False)
    if not args.tasks:
        raise ValueError(
            "Choose one or more MTEB tasks explicitly with --tasks. Public datasets may "
            "download on first use; this prevents large downloads from happening silently."
        )
    try:
        import mteb
    except ImportError as exc:
        raise RuntimeError(
            "MTEB is intentionally disabled in the default project configuration. "
            "Only opt in on a modern 64-bit machine with a compatible native CPU/SIMD "
            "stack and adequate RAM. Locally uncomment the benchmark-mteb dependency "
            "group in pyproject.toml, then run `uv sync --group benchmark-mteb`; "
            "verify `import pyarrow, sklearn` first. See the embedding benchmark guide."
        ) from exc

    backend = args.backend or os.getenv(
        "NLWEB_BENCHMARK_EMBEDDING_BACKEND", "sentence-transformers"
    )
    model_name = args.model or (
        os.getenv("NLWEB_BENCHMARK_OLLAMA_MODEL", "qllama/multilingual-e5-small")
        if backend == "ollama"
        else os.getenv("NLWEB_BENCHMARK_EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
    )
    query_prefix = os.getenv("NLWEB_BENCHMARK_QUERY_PREFIX", "")
    document_prefix = os.getenv("NLWEB_BENCHMARK_DOCUMENT_PREFIX", "")
    if "multilingual-e5" in model_name.casefold():
        query_prefix = query_prefix or "query: "
        document_prefix = document_prefix or "passage: "
    started = time.perf_counter()
    if backend == "sentence-transformers":
        # MTEB's model registry applies the model-specific E5 query/passage prompts.
        model = mteb.get_model(model_name, revision=args.revision, device="cpu")
    elif backend == "ollama":
        allow_remote = os.getenv("NLWEB_BENCHMARK_ALLOW_REMOTE_OLLAMA", "false").casefold() in {
            "1",
            "true",
            "yes",
        }
        base_url = args.ollama_url or os.getenv(
            "NLWEB_BENCHMARK_OLLAMA_URL", "http://127.0.0.1:11434"
        )
        model = OllamaMTEBEncoder(
            model_name,
            base_url=base_url,
            allow_remote=allow_remote,
            query_prefix=query_prefix,
            document_prefix=document_prefix,
        )
    else:
        raise ValueError(f"Unsupported backend: {backend}")

    tasks = mteb.get_tasks(tasks=args.tasks, languages=args.languages or None)
    results_dir = Path(os.getenv("NLWEB_BENCHMARK_MTEB_RESULTS_DIR", "mteb_results")).expanduser()
    if not results_dir.is_absolute():
        results_dir = (ROOT / results_dir).resolve()
    results_dir.mkdir(parents=True, exist_ok=True)
    run_dir = (
        results_dir / f"{args.report_prefix}.{datetime.now(UTC).strftime('%Y-%m-%d_%H-%M-%S')}"
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    results = mteb.evaluate(
        model, tasks=tasks, output_folder=str(run_dir), encode_kwargs={"batch_size": 1}
    )
    report = {
        "schema_version": "1.0",
        "created_at": datetime.now(UTC).isoformat(),
        "runner": "embedding_benchmark.mteb_runner",
        "mteb_version": _version("mteb"),
        "backend": backend,
        "model": model_name,
        "model_revision": args.revision if backend == "sentence-transformers" else None,
        "device": "cpu" if backend == "sentence-transformers" else "local-ollama",
        "tasks": args.tasks,
        "languages": args.languages,
        "query_prefix": query_prefix,
        "document_prefix": document_prefix,
        "retrieval_store": "MTEB task-native evaluation (not sqlite-vec)",
        "hosted_inference_api_used": False,
        "public_dataset_downloads_may_occur": True,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "mteb_result_directory": str(run_dir),
        "result_summary": str(results),
        "note": (
            "MTEB results are a separate public-task track. Compare only matched tasks, "
            "language subsets, model weights/quantization, prompts, and revisions. "
            "The Ollama E5 variant may be quantized differently from the Hugging Face weights."
        ),
    }
    report_path = run_dir / "benchmark-run.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"MTEB backend={backend} model={model_name} tasks={','.join(args.tasks)}")
    print(f"report={report_path}")
    return report_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Optional MTEB public-task evaluation; no hosted inference APIs."
    )
    parser.add_argument("--backend", choices=("sentence-transformers", "ollama"))
    parser.add_argument(
        "--model", help="Model ID; defaults to multilingual-e5-small for the selected backend."
    )
    parser.add_argument("--revision", help="Optional Sentence Transformers model revision.")
    parser.add_argument(
        "--tasks", nargs="+", help="Explicit MTEB task names; public datasets may download."
    )
    parser.add_argument(
        "--languages", nargs="+", help="Optional MTEB language codes, e.g. eng fas."
    )
    parser.add_argument(
        "--ollama-url", help="Local Ollama base URL; remote hosts require explicit opt-in."
    )
    parser.add_argument("--report-prefix", default="mteb")
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
