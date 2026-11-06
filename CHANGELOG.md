# Changelog

## 0.1.8 — approved release (changes from 0.1.7)

- Add a local-first English/Persian retrieval benchmark with a named scenario catalogue, registered corpus/query sources, independent run reports, and JSON/Markdown comparative matrices using Recall, MRR, nDCG, precision, and false-positive measures.
- Support CPU-first Sentence Transformers and opt-in local Ollama benchmark paths, including compatible cross-embedder comparisons; keep hosted inference and public MTEB task downloads outside the default benchmark path.
- Isolate benchmark settings, local SQLite + sqlite-vec indexes, and results from the examples' normal provider/source configuration; require explicit choices for public MTEB tasks, trusted external paths, and model custom code.
- Add model-specific optional dependency groups and early actionable diagnostics while keeping MTEB and the Nomic MegaBlocks GPU optimization disabled by default; document hardware, native-toolchain, memory, and model-code prerequisites.
- Expand the benchmark's scenario-based VS Code workflow and regression coverage without changing its ranking behavior or the Widget runtime contract.
- Preserve the existing independent Scrapy + Ollama, Scrapy + Hugging Face Transformers, custom extraction, remote-storage, and CouchDB examples; extraction outputs and provenance remain separate and are not automatically merged.
- Keep `nlweb-widget` 0.9.12 as the separately versioned runtime dependency. This repository remains a runnable examples/test workspace (`tool.uv.package = false`), not a distributable Python package.

## 0.1.7 — previous approved release

- Frozen approved examples baseline. See the 0.1.8 release notes above for the cumulative change set since this release.
