# Local-first cross-lingual retrieval benchmark

This benchmark evaluates English/Persian retrieval independently from Widget runtime configuration. It owns its `inbox/`, `nlweb-sources.json`, `.env`, SQLite index, and `benchmark_results/`. It does **not** read or mutate the global `NLWEB_CONTENT_SOURCES_FILE`, provider-backend registries, or other example inboxes.

## Resource-conscious defaults

- Retrieval store: local SQLite + `sqlite-vec` (`NLWEB_BENCHMARK_RETRIEVAL_STORE=sqlite-vec`). The vector index is disposable and rebuilt for each run.
- Embeddings: CPU Sentence Transformers, `intfloat/multilingual-e5-small`, CPU, batch size 1. E5 `query: ` and `passage: ` prefixes are applied by default.
- Ollama is opt-in and connects to `127.0.0.1` by default. Remote Ollama hosts are rejected unless `NLWEB_BENCHMARK_ALLOW_REMOTE_OLLAMA=true` is explicitly set.
- No hosted embedding, generation, reranking, or retrieval APIs are called. The Sentence Transformers model may be downloaded from its public model repository on first use; this is a model-file download, not hosted inference. Ollama requires the selected embedding model to already be available locally.
- No LLM generation, external reranker, or multimodal parser runs as part of the default benchmark.

Copy `.env.example` to `.env` in this directory only for operational overrides. The scenario-based CLI takes model/backend/revision/device/batch size/prefix/top-k/distance threshold and source names from `benchmark_scenarios.toml` and `nlweb-sources.json`; those scenario parameters are intentionally absent from `.env.example`. The shared `.env` is still used for the benchmark inbox/results directories and the explicit security gate for remote Ollama endpoints. The separate MTEB runner can optionally load `.env.mteb`; use `.env.mteb.example` as its template. Keep the default `NLWEB_BENCHMARK_INBOX=inbox` unless deliberately relocating the benchmark fixtures together.

## Run a predefined scenario

The workspace-owned `benchmark_scenarios.toml` is the runtime catalogue. The CLI takes only a scenario name; backend, model(s), prefixes, custom-code trust, source registry entries, batch size, retrieval settings, and report naming are read from the TOML file. List the available scenarios with:

```powershell
uv run python examples/embedding_benchmark/run.py --list-scenarios
```

Run a single model, a predefined multi-model sweep, the local Ollama model, or the cross-embedder comparison by passing the chosen name:

```powershell
uv run python examples/embedding_benchmark/run.py st-e5-small
uv run python examples/embedding_benchmark/run.py st-e5-small-plus-minilm
uv run python examples/embedding_benchmark/run.py st-all-three
uv run python examples/embedding_benchmark/run.py ollama-nomic-v2-moe
uv run python examples/embedding_benchmark/run.py compare-nomic-v2-moe-embedders
```

The catalogue includes every non-empty combination of the three predefined Sentence Transformers models (three single-model scenarios, three pairs, and the all-three sweep), the predefined local Ollama Nomic Embed v2 MoE quantized model, and a two-embedder comparison of the compatible Nomic model family. Scenario definitions specify model-specific input prefixes and `trust_remote_code`; for example, the Hugging Face Nomic entry explicitly opts into remote model code and requires the optional `einops` group described below. Review that model code and pin a trusted revision before running it.

Each model gets a separate report and SQLite index. Individual run reports preserve `configuration.invocation_source = "cli"` alongside the scenario and run names for compatibility with the workspace persistence contract. At scenario completion the runner writes both a JSON summary and a Markdown comparative matrix under `benchmark_results/`. The default ranking metric is hybrid RRF `nDCG@10`; the matrix also shows hybrid Recall@5, MRR@10, embedding time, and selected runtime details. The recommendation is provisional and ranks only the observed scenario results. The included corpus is a small evaluation seed, not enough by itself to choose a production model. Use a reviewed, held-out domain-specific corpus and relevance judgments for a final decision.

## Corpus and query sources

Scenarios choose a named corpus source and query source from `nlweb-sources.json`. The enabled default is the small static `inbox/corpus.jsonl` fixture paired with `inbox/queries.jsonl`, registered as `benchmark-corpus` and `benchmark-queries`; this keeps smoke runs local and fast. To use domain-specific data, enable and edit the supplied `domain-corpus-jsonl` entry, then change a scenario's `corpus_source` to that name. Keep the existing `benchmark-queries` source name and configure its path to your judged query JSONL (set `allow_external_path = true` if the file is outside the dedicated inbox). Query entries must carry stable IDs and relevance judgments against the selected corpus. You may add additional named corpus JSONL entries and reference them from scenario definitions.

Only `jsonl` source entries are currently implemented by this benchmark runner. External paths are rejected by default; the supplied domain-specific corpus entry uses `allow_external_path = true` as an explicit registry-level opt-in. Use that only for paths you control and trust. Do not point this benchmark at a general Widget/global source registry: the benchmark expects a corpus plus paired judged queries, not an arbitrary unjudged content feed.

## Models that require custom repository code

The Sentence Transformers backend keeps `trust_remote_code` disabled by default for ad-hoc/internal use. Scenario entries may explicitly set `trust_remote_code = true` for models that require custom code. Some model repositories provide executable Python needed to implement their architecture. Review and trust that repository before running its scenario, and prefer pinning a reviewed immutable `revision` in the scenario TOML so custom code is not silently updated between runs.

The Nomic Embed v2 MoE model requires `einops` in addition to the default environment. This dependency is isolated in the opt-in `benchmark-nomic-v2-moe` dependency group, so it is not installed for users who run the default E5 benchmark. For improved downloads from compatible Hugging Face Hub Xet repositories, install the separate `benchmark-huggingface-downloads` group (`hf-xet`); Hub downloads fall back to the supported standard transport when Xet is not available. Hugging Face documents `hf_xet` as its chunk-based deduplicating transfer integration ([download guide](https://huggingface.co/docs/huggingface_hub/main/guides/download)).

```powershell
uv sync --group benchmark-nomic-v2-moe --group benchmark-huggingface-downloads
```

Nomic's model card also recommends its `megablocks` fork for best GPU performance. This optimization is **disabled by default**: the `benchmark-nomic-v2-moe-gpu` dependency group is commented out in `pyproject.toml`. It is source-built and may require a compatible NVIDIA GPU/CUDA stack, a compatible installed PyTorch build, native build tools, and sufficient RAM/disk. Do not enable it on CPU-only or low-resource systems (including the dual-core/4 GB profile). The model can use its slower built-in fallback when MegaBlocks is unavailable; the warning is not itself a benchmark failure.

Only on a compatible GPU machine, review the prerequisites and uncomment the documented group in `pyproject.toml`, then opt in explicitly:

```powershell
uv sync --group benchmark-nomic-v2-moe
uv sync --group benchmark-nomic-v2-moe --group benchmark-nomic-v2-moe-gpu --no-build-isolation-package megablocks
```

The upstream Nomic model card recommends MegaBlocks for best GPU performance ([model card](https://huggingface.co/nomic-ai/nomic-embed-text-v2-moe)). This optional build path is not validated by the default CPU benchmark QA.
The model card documents the custom-code requirement and its task prefixes (`search_document: ` for corpus text and `search_query: ` for queries). The predefined Nomic scenarios set those prefixes explicitly in `benchmark_scenarios.toml`. If `einops` is absent, the runner stops before loading the model repository code and prints the installation command.

```powershell
uv run python examples/embedding_benchmark/run.py st-nomic-v2-moe
```

A successful load is not enough to prove the Ollama and Sentence Transformers artifacts are numerically identical. Record each backend's model/quantization and prompts, rebuild the index for each embedding model, and compare the same corpus and judgments.

## Optional MTEB public benchmark

MTEB is a separate public-task evaluation layer, not a requirement for the local English/Persian domain benchmark. Its optional model/backend/prefix/results overrides belong in `.env.mteb` (copied from `.env.mteb.example`), not in the scenario runner's `.env.example`. It is **disabled in the default `pyproject.toml` dependency groups** because its `mteb -> datasets -> PyArrow` native dependency chain crashed with Windows `STATUS_ILLEGAL_INSTRUCTION` (`0xC000001D`) on a legacy Intel Core 2 Duo machine without AVX. This is a native CPU/library compatibility failure, not a Python exception.

Only opt in if your environment has a modern 64-bit CPU and compatible SIMD/native wheels (AVX2-capable hardware is a sensible baseline), Python/platform-compatible wheels, adequate free disk/network access, and sufficient RAM. Treat **8 GB RAM as a practical minimum for small tasks; 16 GB or more is recommended** for larger multilingual tasks. Before enabling MTEB, verify that `import pyarrow` and `import sklearn` succeed in the exact environment. Public tasks may download large datasets and model files; the runner does not call hosted inference APIs.

To opt in locally, uncomment the `benchmark-mteb` group in `pyproject.toml` and run:

```powershell
uv sync --group benchmark-mteb
```

Keep that local opt-in uncommitted if you want the default project environment to remain lightweight. If native imports fail or the process exits with `0xC000001D`, disable the group again and use the local domain benchmark instead. Task names must be explicit so large public datasets are never downloaded silently.

Choose task names from the [MTEB task documentation](https://docs.mteb.org/), starting with a relatively small retrieval task such as `SynPerQARetrieval` for Persian, then run the same task/language selection against both backends. Large multilingual retrieval tasks can require substantial memory, disk space and downloads:

```powershell
uv run --group benchmark-mteb python examples/embedding_benchmark/mteb_runner.py --backend sentence-transformers --model intfloat/multilingual-e5-small --tasks SynPerQARetrieval --languages fas
uv run --group benchmark-mteb python examples/embedding_benchmark/mteb_runner.py --backend ollama --model qllama/multilingual-e5-small --tasks SynPerQARetrieval --languages fas
```

The Ollama model is an Ollama-distributed conversion of the same E5-small model family; its quantization may differ from the Hugging Face weights, so report it as a backend/packaging comparison rather than claiming bit-identical inference. Both runs use the E5 query/document prefixes. Compare matching tasks, languages, revisions and prompts; MTEB results are stored under the benchmark's `mteb_results/` directory, separately from `benchmark_results/`. Use small tasks first on a 4 GB machine; public retrieval datasets can require substantial RAM, disk space and downloads.

## Evaluation design

- `inbox/corpus.jsonl`: versioned document fixtures with stable IDs, language, title, text, and source URI.
- `inbox/queries.jsonl`: English, Persian, and mixed-language queries, bidirectional cross-lingual relevance judgments, graded relevance, spelling variation (Arabic/Persian letters, half-spaces, and Persian digits), hard negatives, and unanswerable examples.
- `nlweb-sources.json`: benchmark-owned source registry. It is not a Widget-global source registry.
- Retrieval tracks: dense sqlite-vec cosine-distance ranking, a dependency-free BM25 lexical baseline with Persian-aware normalization, and reciprocal-rank-fusion hybrid ranking.
- Metrics: Recall@1/3/5/10, MRR@10, nDCG@10, Precision@10, per-query results, query-language and query-to-evidence-language slices, and a dense-only distance-threshold false-positive rate for unanswerable questions. The BM25 implementation is a compact baseline; validate it against a mature lexical engine before treating scores as production-equivalent. RSS is sampled at phase checkpoints when `psutil` is available; it is not a continuously sampled peak-memory profiler.
- Operational data: embedding/indexing time, dense and hybrid retrieval p50/p95, vector dimensions, SQLite file size, platform/runtime versions, model/configuration, and dataset hashes.
- Results are written to `benchmark_results/` as JSON. Reports capture dataset hashes, model/revision, prefix settings, runtime library versions, similarity metric, and configuration. The database is written to `runtime/benchmark.sqlite3`; both locations are local runtime output and are not source-of-truth data.

## Interpretation and limits

The included corpus is a small smoke/evaluation seed, not a statistically sufficient final quality benchmark. Expand it with reviewed domain-specific queries and judgments before selecting a production model. Keep tuning queries separate from a held-out evaluation set. Compare the same corpus and judgments across backends, and compare model changes only after reindexing with that model's embeddings. Dense cosine-distance thresholds are model-dependent and must be calibrated on labeled answerable/unanswerable queries; the default threshold is a starting point, not a universal confidence score.

This iteration evaluates retrieval, not generated `/ask` answer correctness or grounding. A later phase may add an explicitly opt-in end-to-end test, but any generation must remain local by default and must never run silently as part of this benchmark.

## Ollama HTTP 500 troubleshooting

A model appearing in `ollama list` confirms it is installed, but does not guarantee that it implements Ollama's embedding API. The benchmark uses `POST /api/embed`; on HTTP errors it now includes Ollama's response body in the failure message when available. Check the model metadata and server version:

```powershell
ollama --version
ollama show multilingual-e5-small-local
ollama ps
```

Then test the exact API used by the benchmark:

```powershell
$body = @{ model = "multilingual-e5-small-local"; input = "query: What is the company?" } | ConvertTo-Json
Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/embed" -Method Post -ContentType "application/json" -Body $body
```

If this returns HTTP 500, inspect its response body and the Ollama server logs. Confirm that the imported model format/architecture is supported for embeddings and that the model fits available RAM. A browser request to the base URL returning an empty response is not a meaningful health check; the base URL is not the embedding endpoint. Do not substitute a chat/generation endpoint: the benchmark expects a vector array from `/api/embed`.
