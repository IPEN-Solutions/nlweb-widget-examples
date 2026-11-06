# Local-first Scrapy + Hugging Face Transformers extraction

This is a separate local LLM-backed extraction path alongside Scrapy + Ollama and ScrapeGraphAI. It loads `Qwen/Qwen2.5-0.5B-Instruct` directly with Hugging Face Transformers; it does **not** require an Ollama server or Ollama model installation.

## Minimal profile for a dual-core CPU and 4 GB RAM

The example now uses conservative defaults intended for low-resource local development. This is a best-effort profile, not a guarantee of fit on every machine: Windows, other running applications, and model-cache state affect available memory.

- CPU inference with at most two PyTorch intra-op threads and one inter-op thread.
- `low_cpu_mem_usage=True` while loading model weights (requires the `accelerate` package, included in the optional extra).
- At most 1,024 input tokens, 2,000 page-text characters, and 96 generated tokens per page by default.
- A sequential crawl limited by default to three pages and depth one.
- Tokenizer parallelism disabled and common CPU math thread counts capped at two.
- The general examples `.env.example` uses embedding batch size `1`; avoid running embedding/indexing and local Qwen inference at the same time on a 4 GB machine.

The model and Python dependencies need several GB of disk space and the first run downloads model files from Hugging Face. Keep enough free disk space and memory. If the machine starts paging heavily or inference is unusably slow, reduce the crawl to one page or run without other memory-heavy applications.

## Install

```powershell
uv sync --extra local-scrapy-transformers
```

Optional settings live in `examples/external_hosted_sources/domain_site_extractor/.env.example`; copy it to `.env` in that directory and adjust only as needed. The code defaults remain conservative even if no `.env` file is present.

| Variable | Default | Purpose |
|---|---:|---|
| `NLWEB_HF_MODEL` | `Qwen/Qwen2.5-0.5B-Instruct` | Hugging Face model ID |
| `NLWEB_HF_DEVICE` | `cpu` | Inference device; use `cuda` only with a compatible GPU/PyTorch install |
| `NLWEB_HF_TORCH_THREADS` | `2` | PyTorch intra-op CPU threads |
| `NLWEB_HF_MAX_NEW_TOKENS` | `96` | Maximum generated tokens per page |
| `NLWEB_HF_MAX_INPUT_TOKENS` | `1024` | Tokenizer input truncation limit |
| `NLWEB_HF_MAX_PAGE_CHARS` | `2000` | Maximum page-text characters passed to the prompt |
| `NLWEB_SCRAPY_MAX_PAGES` | `3` | Default crawl page limit; CLI `--max-pages` overrides it |
| `NLWEB_SCRAPY_DEPTH_LIMIT` | `1` | Default crawl depth; CLI `--depth-limit` overrides it |
| `OMP_NUM_THREADS` / `MKL_NUM_THREADS` | `2` | CPU math-library thread limits |
| `TOKENIZERS_PARALLELISM` | `false` | Avoid tokenizer worker oversubscription |

## Run independently

Start with a one-page smoke test on constrained hardware:

```powershell
uv run --extra local-scrapy-transformers python -m examples.external_hosted_sources.domain_site_extractor.local_scrapy_transformers https://your-domain.example/ --allowed-hosts your-domain.example --max-pages 1 --depth-limit 0
```

For a small crawl, omit the last two flags to use the three-page/depth-one defaults. The default output is `generated/local-scrapy-transformers.jsonld`. Each page item is also preserved in `runtime/local-scrapy-transformers-items.jsonl` and written to `runtime/extracted-content.sqlite3` with `extractor=scrapy_transformers`, provider `huggingface-transformers`, and the configured model ID. This extraction database is separate from the Widget retrieval database. The crawler is sequential, obeys `robots.txt`, and follows links only within the allowed host list. JavaScript-rendered content is not rendered by Scrapy. Use only sites you are authorized to crawl.

## Use as the configured LLM extraction backend

Set the scenario URL and explicit extraction switches in the private `.env` for `domain_site_extractor`:

```dotenv
NLWEB_EXTERNAL_SOURCE_LLM_ENABLED=true
NLWEB_EXTERNAL_SOURCE_EXTRACTOR_BACKEND=scrapy_transformers
NLWEB_EXTERNAL_SOURCE_ALLOWED_HOSTS=your-domain.example
NLWEB_EXTERNAL_SOURCE_COMPANY_WEBSITE_URL=https://your-domain.example/
```

Install the optional extra before running the existing extraction demo/app. The configured backend writes a backend-specific JSON-LD artifact and provenance manifest. When the custom non-LLM path is also enabled, its artifact remains separate; no automatic merge, overwrite, or reconciliation is performed. The custom artifact keeps the scenario's configured retrieval corpus ID, while the Transformers artifact uses `<scenario-site>--scrapy_transformers`. For example, a scenario ID `company.example.hosted-source` yields `company.example.hosted-source--scrapy_transformers` for this backend. Filter `/ask` by the desired corpus ID to avoid seeing overlapping records from both independent backends in the same answer; an unfiltered query can still return results from both.

## Evidence and limitations

Valid JSON-LD script objects are preserved as source records rather than reconstructed by the model. The model is asked to extract only page-text-supported claims. A claim is retained only when its `source_url` exactly matches the current page and its evidence quotation occurs verbatim in the visible page text. Model-derived records carry `nlwebEvidenceStatus: unverified-extraction`; this is not an authenticity or truth guarantee. If model loading, generation, or output parsing fails, the crawl still emits available JSON-LD and page text and omits model-derived claims for that page.

The model is small but can still be slow on a dual-core CPU and may omit valid claims or produce malformed output. Review generated artifacts before enabling them as retrieval sources. This example is independent from the Ollama-backed script and writes to a distinct artifact path.
