# Scenario-based multilingual embedding benchmark

The benchmark is an isolated, local-first retrieval comparison workflow. Its runtime catalogue is `examples/embedding_benchmark/benchmark_scenarios.toml`; the command line accepts a scenario name rather than individual model/backend flags. This keeps each run reproducible and makes the scenario file the workspace-owned extension point.

## List and run scenarios

Run these commands from the Examples workspace root:

```powershell
uv run python examples/embedding_benchmark/run.py --list-scenarios
uv run python examples/embedding_benchmark/run.py st-e5-small
uv run python examples/embedding_benchmark/run.py st-all-three
uv run python examples/embedding_benchmark/run.py ollama-nomic-v2-moe
uv run python examples/embedding_benchmark/run.py compare-nomic-v2-moe-embedders
```

The catalogue defines two scenario types: one embedder compared across one or more models against one corpus, and two embedders compared against a compatible baseline model family and one corpus. The nine predefined scenarios cover the three Sentence Transformers models (`intfloat/multilingual-e5-small`, `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, and `nomic-ai/nomic-embed-text-v2-moe`), all pairwise combinations and the all-three sweep, the local Ollama `nomic-embed-text-v2-moe.Q4_K_S-local` model, and a cross-embedder Nomic comparison.

VS Code tasks provide one task to list scenarios and one task for each configured scenario. They invoke the same name-only CLI and do not duplicate runtime configuration.

## Scenario configuration and corpus sources

Each scenario selects the source registry, corpus source, query source, retrieval settings, and primary ranking metric. Each run defines its backend, model, revision (if pinned), device, batch size, model-family identity, task prefixes, and `trust_remote_code` setting. Add a new model or backend by adding a run entry to `benchmark_scenarios.toml`; add compatible corpus data by registering its JSONL source in `examples/embedding_benchmark/nlweb-sources.json` and referencing the registered source name from a scenario.

The default corpus is the small static JSONL fixture registered as `benchmark-corpus`, paired with the existing `benchmark-queries` source. It is intentionally fast and reproducible. For domain-specific evaluation, configure a corpus source with representative content and keep the query set and relevance judgments appropriate to that domain. Do not compare runs if their corpora, query sets, judgments, or metric definitions differ. External data paths require explicit opt-in where the runner's path guard applies.

## Comparative reports and recommendations

Each model run gets an independent SQLite index and a JSON report. At scenario completion the runner writes a comparative JSON summary and a Markdown matrix containing dense, BM25, hybrid retrieval metrics and embedding time. The recommendation ranks runs by the configured primary metric and is provisional: the default fixture is small and cannot establish a universal production winner. Validate promising models on domain-owned queries and relevance judgments before selecting one for production.

Each run report preserves `configuration.invocation_source = "cli"`, scenario name and run name for the workspace persistence contract.

## Environment and optional dependencies

The scenario catalogue owns model/backend and evaluation runtime parameters. The benchmark `.env.example` is reserved for operational paths and the explicit remote-Ollama security gate; it is not the source of model settings. MTEB is a separate optional workflow and reads `.env.mteb` from `.env.mteb.example`.

Install the Nomic custom-code import dependency and optional Hugging Face Xet download acceleration as needed:

```powershell
uv sync --group benchmark-nomic-v2-moe --group benchmark-huggingface-downloads
```

The Nomic scenario requires `trust_remote_code = true` and uses `search_document: ` / `search_query: ` prefixes. Review the model repository's code and pin a trusted immutable revision before running it. `hf-xet` may improve downloads from compatible Hugging Face Hub repositories; it does not change embedding inference performance or retrieval quality.

Nomic's model card recommends its MegaBlocks fork for best GPU performance. That source-built optimization is disabled by default in `pyproject.toml` and must remain so on CPU-only or low-resource systems. It may require a compatible NVIDIA GPU/CUDA stack, compatible PyTorch, native build tools, and sufficient RAM/disk. Only on a compatible GPU machine, review those prerequisites and deliberately uncomment the `benchmark-nomic-v2-moe-gpu` dependency group before installing it. The model's slower fallback path remains usable without MegaBlocks; the warning is not itself a benchmark failure.

## Optional MTEB evaluation and hardware prerequisites

MTEB is intentionally not enabled in the default dependency groups. Its `mteb -> datasets -> PyArrow` native dependency chain has produced Windows `STATUS_ILLEGAL_INSTRUCTION` (`0xC000001D`) on legacy x86-64 CPUs without AVX. Opt in only on a modern 64-bit CPU with a compatible SIMD/native-wheel stack (AVX2-capable hardware is a sensible baseline), Python/platform-compatible wheels, and adequate memory: 8 GB is a practical minimum for small tasks; 16 GB+ is recommended for larger multilingual tasks. Verify `import pyarrow` and `import sklearn` in the target environment before enabling the group. Keep it disabled on machines where native imports crash.

## Ollama `/api/embed` HTTP 500

`ollama list` only proves that a model is installed; it does not prove that the model supports embeddings. The benchmark calls `POST http://127.0.0.1:11434/api/embed`. Use `ollama --version`, `ollama show <model>`, and `ollama ps`, then test `/api/embed` directly with the selected model. The runner includes the HTTP error response body when Ollama returns an error. If the endpoint returns HTTP 500, inspect the response and Ollama server logs for unsupported model architecture, model-loading, or memory-allocation errors. A browser request to the base URL is not a valid embedding endpoint test.
