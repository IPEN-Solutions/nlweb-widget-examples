"""Core local-first benchmark helpers. Only explicitly selected local Ollama is contacted."""

from __future__ import annotations

import importlib.util
import json
import math
import os
import sqlite3
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class Document:
    id: str
    language: str
    title: str
    text: str
    source_uri: str


@dataclass(frozen=True)
class Query:
    id: str
    language: str
    text: str
    relevant: dict[str, int]
    answerable: bool


class Embedder(Protocol):
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class SentenceTransformersEmbedder:
    def __init__(
        self,
        model_name: str,
        device: str = "cpu",
        batch_size: int = 1,
        revision: str | None = None,
        trust_remote_code: bool = False,
    ) -> None:
        if device.casefold() != "cpu":
            raise ValueError(
                "The benchmark defaults to CPU; use --device cpu to keep resource use predictable."
            )
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        if "nomic-embed-text-v2-moe" in model_name.casefold() and trust_remote_code:
            # Fail before loading repository-supplied executable code when its
            # known runtime dependency is absent; this gives a deterministic fix.
            if importlib.util.find_spec("einops") is None:
                raise RuntimeError(
                    "The Nomic Embed v2 MoE model requires the optional `einops` dependency. "
                    "Install it with `uv sync --group benchmark-nomic-v2-moe`, then rerun. "
                    "Only use --trust-remote-code after reviewing and trusting the model repository."
                )
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "Install the existing sentence-transformers dependency to use this backend."
            ) from exc
        self.name = model_name
        self.batch_size = batch_size
        self.revision = revision
        self.trust_remote_code = trust_remote_code
        # Model repositories can supply executable Python. Keep this disabled by
        # default; callers must explicitly opt in for models that require it.
        self.model = SentenceTransformer(
            model_name,
            device="cpu",
            revision=revision,
            trust_remote_code=trust_remote_code,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self.model.encode(
            texts,
            batch_size=self.batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [[float(value) for value in vector] for vector in vectors]


class OllamaEmbedder:
    def __init__(self, base_url: str, model_name: str, allow_remote: bool = False) -> None:
        parsed = urllib.parse.urlparse(base_url)
        host = (parsed.hostname or "").casefold()
        local_hosts = {"localhost", "127.0.0.1", "::1"}
        if host not in local_hosts and not allow_remote:
            raise ValueError(
                "Ollama URL must be localhost by default; set "
                "NLWEB_BENCHMARK_ALLOW_REMOTE_OLLAMA=true to opt in to a remote host."
            )
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Ollama URL must be an absolute http(s) URL")
        self.base_url = base_url.rstrip("/")
        self.name = model_name

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        # Keep request size small for the constrained local development profile.
        for text in texts:
            payload = json.dumps({"model": self.name, "input": text}).encode("utf-8")
            request = urllib.request.Request(
                f"{self.base_url}/api/embed",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    result = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                # HTTPError is also a URLError, but its response body often contains
                # the actionable Ollama model/runtime error (e.g. unsupported model
                # architecture or an allocation failure). Preserve that diagnostic.
                try:
                    detail = exc.read().decode("utf-8", errors="replace").strip()
                except Exception:
                    detail = ""
                suffix = f"; response={detail[:1000]}" if detail else ""
                raise RuntimeError(
                    f"Ollama returned HTTP {exc.code} for {exc.url}{suffix}. "
                    "Check `ollama show <model>`, `ollama --version`, and whether "
                    "the selected model supports `/api/embed`."
                ) from exc
            except (urllib.error.URLError, TimeoutError) as exc:
                raise RuntimeError(
                    f"Could not reach local Ollama at {self.base_url}: {exc}. "
                    "Check that Ollama is running and that its local API is reachable."
                ) from exc
            embeddings = result.get("embeddings")
            if (
                not isinstance(embeddings, list)
                or not embeddings
                or not isinstance(embeddings[0], list)
            ):
                raise RuntimeError(
                    "Ollama /api/embed returned no embeddings; check the local model name "
                    "and Ollama version."
                )
            vectors.append([float(value) for value in embeddings[0]])
        return vectors


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"Expected a JSON object at {path}:{line_number}")
            rows.append(value)
    return rows


def load_dataset(
    root: Path,
    registry_path: Path | None = None,
    *,
    corpus_source_name: str | None = None,
    query_source_name: str | None = None,
) -> tuple[list[Document], list[Query], dict[str, Any]]:
    registry_path = registry_path or root / "nlweb-sources.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    sources = registry.get("sources", [])

    def select_source(role: str, requested_name: str | None) -> dict[str, Any]:
        matches = [
            item
            for item in sources
            if item.get("role") == role
            and (requested_name is None or item.get("name") == requested_name)
        ]
        if not matches:
            label = f" named {requested_name!r}" if requested_name else ""
            raise ValueError(f"Benchmark registry has no {role!r} source{label}.")
        source = matches[0]
        if not source.get("enabled"):
            raise ValueError(
                f"Benchmark source {source.get('name')!r} is disabled; enable it in the source registry."
            )
        if source.get("kind", "jsonl").casefold() != "jsonl":
            raise ValueError(
                f"Unsupported benchmark source kind {source.get('kind')!r}; currently supported: jsonl."
            )
        return source

    corpus_source = select_source("retrieval-documents", corpus_source_name)
    query_source = select_source("evaluation-queries-and-judgments", query_source_name)
    enabled = {
        "retrieval-documents": corpus_source,
        "evaluation-queries-and-judgments": query_source,
    }
    configured_inbox = Path(os.getenv("NLWEB_BENCHMARK_INBOX", "inbox")).expanduser()
    inbox = (
        configured_inbox
        if configured_inbox.is_absolute()
        else (registry_path.parent / configured_inbox).resolve()
    )
    allowed_root = inbox.resolve()

    def source_path(location: str, source: dict[str, Any]) -> Path:
        relative = Path(location)
        if relative.is_absolute():
            path = relative.resolve()
        elif relative.parts and relative.parts[0] == "inbox":
            path = (allowed_root / Path(*relative.parts[1:])).resolve()
        else:
            path = (registry_path.parent / relative).resolve()
        if not path.is_relative_to(allowed_root) and not source.get("allow_external_path", False):
            raise ValueError(
                f"Benchmark registry path escapes the dedicated inbox: {path}. "
                "For an intentional domain-specific file, set allow_external_path = true "
                "on that trusted registry entry."
            )
        return path

    corpus_path = source_path(
        enabled["retrieval-documents"]["location"], enabled["retrieval-documents"]
    )
    queries_path = source_path(
        enabled["evaluation-queries-and-judgments"]["location"],
        enabled["evaluation-queries-and-judgments"],
    )
    documents = [Document(**row) for row in read_jsonl(corpus_path)]
    queries = [Query(**row) for row in read_jsonl(queries_path)]
    doc_ids = {doc.id for doc in documents}
    if len(doc_ids) != len(documents):
        raise ValueError("Corpus contains duplicate document IDs")
    query_ids = [query.id for query in queries]
    if len(set(query_ids)) != len(query_ids):
        raise ValueError("Query set contains duplicate query IDs")
    for query in queries:
        unknown = set(query.relevant) - doc_ids
        if unknown:
            raise ValueError(
                f"Query {query.id} refers to unknown relevant document IDs: {sorted(unknown)}"
            )
        if query.answerable != bool(query.relevant):
            raise ValueError(
                f"Query {query.id}: answerable must agree with whether "
                "relevance judgments are present"
            )
    return documents, queries, registry


class SqliteVecStore:
    """Small disposable evaluation index backed by sqlite-vec; vectors are rebuilt per run."""

    def __init__(self, path: Path, dimensions: int) -> None:
        try:
            import sqlite_vec
        except ImportError as exc:
            raise RuntimeError(
                "sqlite-vec is required. Install the Widget's SQLite extra "
                "in the examples environment."
            ) from exc
        self.sqlite_vec = sqlite_vec
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.enable_load_extension(True)
        try:
            self.sqlite_vec.load(self.connection)
        finally:
            self.connection.enable_load_extension(False)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS documents ("
            "row_id INTEGER PRIMARY KEY, doc_id TEXT UNIQUE NOT NULL, "
            "language TEXT NOT NULL, title TEXT NOT NULL, text TEXT NOT NULL, "
            "source_uri TEXT NOT NULL)"
        )
        self.connection.execute("DROP TABLE IF EXISTS benchmark_vectors")
        self.connection.execute(
            f"CREATE VIRTUAL TABLE benchmark_vectors USING "
            f"vec0(embedding float[{int(dimensions)}] distance_metric=cosine)"
        )
        self.connection.execute("DELETE FROM documents")
        self.connection.commit()

    def index(self, documents: list[Document], vectors: list[list[float]]) -> None:
        if len(documents) != len(vectors):
            raise ValueError("Document/vector count mismatch")
        if not vectors:
            return
        dimensions = len(vectors[0])
        if dimensions < 1 or any(len(vector) != dimensions for vector in vectors):
            raise ValueError("Embedding vectors must have a consistent non-zero dimension")
        if len({doc.id for doc in documents}) != len(documents):
            raise ValueError("Document IDs must be unique")
        with self.connection:
            for document, vector in zip(documents, vectors, strict=True):
                cursor = self.connection.execute(
                    "INSERT INTO documents(doc_id, language, title, text, source_uri) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        document.id,
                        document.language,
                        document.title,
                        document.text,
                        document.source_uri,
                    ),
                )
                self.connection.execute(
                    "INSERT INTO benchmark_vectors(rowid, embedding) VALUES (?, ?)",
                    (cursor.lastrowid, self.sqlite_vec.serialize_float32(vector)),
                )

    def search(self, vector: list[float], top_k: int) -> list[tuple[Document, float]]:
        if top_k < 1:
            raise ValueError("top_k must be at least 1")
        rows = self.connection.execute(
            "SELECT d.doc_id, d.language, d.title, d.text, d.source_uri, v.distance "
            "FROM benchmark_vectors AS v JOIN documents AS d ON d.row_id = v.rowid "
            "WHERE v.embedding MATCH ? AND k = ? ORDER BY v.distance",
            (self.sqlite_vec.serialize_float32(vector), top_k),
        ).fetchall()
        return [(Document(row[0], row[1], row[2], row[3], row[4]), float(row[5])) for row in rows]

    def close(self) -> None:
        self.connection.close()


def _tokens(value: str) -> list[str]:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.replace("ي", "ی").replace("ك", "ک").replace("ـ", "")
    value = value.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    value = value.replace("\u200c", " ")
    value = "".join(char for char in value if not unicodedata.combining(char))
    punctuation = ".,!?;:()[]{}\"'«»،؛؟"
    return [token.strip(punctuation) for token in value.split() if token.strip(punctuation)]


def bm25_search(
    query: str, documents: list[Document], top_k: int, k1: float = 1.5, b: float = 0.75
) -> list[tuple[Document, float]]:
    """Small dependency-free BM25 implementation with Persian-aware text normalization."""
    query_tokens = _tokens(query)
    if not query_tokens or not documents:
        return []
    tokenized = {doc.id: _tokens(f"{doc.title} {doc.text}") for doc in documents}
    lengths = {doc_id: len(tokens) for doc_id, tokens in tokenized.items()}
    average_length = sum(lengths.values()) / max(1, len(lengths))
    token_sets = {doc_id: set(tokens) for doc_id, tokens in tokenized.items()}
    document_frequency = Counter(
        token for token in set(query_tokens) for doc_id in token_sets if token in token_sets[doc_id]
    )
    scores: list[tuple[Document, float]] = []
    for document in documents:
        tokens = tokenized[document.id]
        counts = Counter(tokens)
        score = 0.0
        for token in query_tokens:
            frequency = counts[token]
            if not frequency:
                continue
            idf = math.log(
                1
                + (len(documents) - document_frequency[token] + 0.5)
                / (document_frequency[token] + 0.5)
            )
            denominator = frequency + k1 * (
                1 - b + b * lengths[document.id] / max(1.0, average_length)
            )
            score += idf * frequency * (k1 + 1) / denominator
        scores.append((document, score))
    scores.sort(key=lambda item: item[1], reverse=True)
    return scores[:top_k]


def reciprocal_rank_fusion(
    *rankings: list[tuple[Document, float]], top_k: int = 5, constant: int = 60
) -> list[tuple[Document, float]]:
    scores: dict[str, float] = {}
    documents: dict[str, Document] = {}
    for ranking in rankings:
        for rank, (document, _) in enumerate(ranking, 1):
            documents[document.id] = document
            scores[document.id] = scores.get(document.id, 0.0) + 1.0 / (constant + rank)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top_k]
    return [(documents[doc_id], score) for doc_id, score in ranked]


def _dcg(grades: list[int]) -> float:
    return sum((2**grade - 1) / math.log2(index + 2) for index, grade in enumerate(grades))


def evaluate_rankings(
    queries: list[Query],
    rankings: dict[str, list[tuple[str, float]]],
    top_k: int = 10,
    max_cosine_distance: float | None = 0.35,
    document_languages: dict[str, str] | None = None,
) -> dict[str, Any]:
    per_query: list[dict[str, Any]] = []
    recalls = {k: [] for k in (1, 3, 5, 10)}
    reciprocal_ranks: list[float] = []
    ndcgs: list[float] = []
    precisions: list[float] = []
    no_answer_false_positives: list[bool] = []
    for query in queries:
        ranking = rankings.get(query.id, [])
        ids = [doc_id for doc_id, _ in ranking]
        grades = [int(query.relevant.get(doc_id, 0)) for doc_id in ids]
        relevant_ids = {doc_id for doc_id, grade in query.relevant.items() if grade > 0}
        first_relevant_rank = next(
            (index for index, doc_id in enumerate(ids, 1) if doc_id in relevant_ids), None
        )
        reciprocal_rank = 1 / first_relevant_rank if first_relevant_rank else 0.0
        ideal = sorted(query.relevant.values(), reverse=True)[:top_k]
        ndcg = (_dcg(grades[:top_k]) / _dcg(ideal)) if ideal and _dcg(ideal) else 0.0
        precision = sum(1 for doc_id in ids[:top_k] if doc_id in relevant_ids) / max(
            1, min(top_k, len(ids))
        )
        query_recalls = {
            k: (len(set(ids[:k]) & relevant_ids) / len(relevant_ids) if query.answerable else None)
            for k in recalls
        }
        if query.answerable:
            reciprocal_ranks.append(reciprocal_rank)
            ndcgs.append(ndcg)
            precisions.append(precision)
            for k in recalls:
                recalls[k].append(query_recalls[k])
        first_score = ranking[0][1] if ranking else None
        accepted = (
            (first_score is not None and first_score <= max_cosine_distance)
            if max_cosine_distance is not None
            else None
        )
        if not query.answerable and accepted is not None:
            no_answer_false_positives.append(accepted)
        relevant_by_language: dict[str, dict[str, int]] = {}
        for doc_id, grade in query.relevant.items():
            language = (document_languages or {}).get(doc_id, "unknown")
            relevant_by_language.setdefault(language, {})[doc_id] = grade
        per_query.append(
            {
                "query_id": query.id,
                "query_language": query.language,
                "relevant_document_languages": sorted(relevant_by_language),
                "relevant_by_language": relevant_by_language,
                "answerable": query.answerable,
                "recall_at_1": query_recalls[1],
                "recall_at_3": query_recalls[3],
                "recall_at_5": query_recalls[5],
                "recall_at_10": query_recalls[10],
                "top_results": [
                    {
                        "document_id": doc_id,
                        "score": score,
                        "relevance": int(query.relevant.get(doc_id, 0)),
                    }
                    for doc_id, score in ranking[:top_k]
                ],
                "first_relevant_rank": first_relevant_rank,
                "reciprocal_rank": reciprocal_rank,
                "ndcg_at_10": ndcg,
                "precision_at_10": precision,
                "accepted_by_distance_threshold": accepted,
                "no_answer_false_positive": (
                    bool(not query.answerable and accepted) if accepted is not None else None
                ),
            }
        )
    answerable_count = sum(query.answerable for query in queries)
    unanswerable_count = len(queries) - answerable_count
    by_query_language = {
        language: _summarize_query_rows(
            [row for row in per_query if row["query_language"] == language],
            max_cosine_distance is not None,
        )
        for language in sorted({row["query_language"] for row in per_query})
    }
    direction_rows: dict[str, list[dict[str, Any]]] = {}
    for row in per_query:
        for evidence_language, relevant_in_language in row["relevant_by_language"].items():
            ranked_ids = [result["document_id"] for result in row["top_results"]]
            relevant_ids_in_language = set(relevant_in_language)
            first_rank = next(
                (
                    index
                    for index, doc_id in enumerate(ranked_ids, 1)
                    if doc_id in relevant_ids_in_language
                ),
                None,
            )
            grades_in_language = [int(relevant_in_language.get(doc_id, 0)) for doc_id in ranked_ids]
            ideal_in_language = sorted(relevant_in_language.values(), reverse=True)[:top_k]
            direction_row = dict(row)
            direction_row.update(
                {
                    "recall_at_1": (
                        len(set(ranked_ids[:1]) & relevant_ids_in_language)
                        / len(relevant_ids_in_language)
                    ),
                    "recall_at_3": (
                        len(set(ranked_ids[:3]) & relevant_ids_in_language)
                        / len(relevant_ids_in_language)
                    ),
                    "recall_at_5": (
                        len(set(ranked_ids[:5]) & relevant_ids_in_language)
                        / len(relevant_ids_in_language)
                    ),
                    "recall_at_10": (
                        len(set(ranked_ids[:10]) & relevant_ids_in_language)
                        / len(relevant_ids_in_language)
                    ),
                    "reciprocal_rank": 1 / first_rank if first_rank else 0.0,
                    "ndcg_at_10": (
                        _dcg(grades_in_language[:top_k]) / _dcg(ideal_in_language)
                        if ideal_in_language and _dcg(ideal_in_language)
                        else 0.0
                    ),
                    "precision_at_10": (
                        sum(
                            1 for doc_id in ranked_ids[:top_k] if doc_id in relevant_ids_in_language
                        )
                        / max(1, min(top_k, len(ranked_ids)))
                    ),
                }
            )
            direction = f"{row['query_language']}->{evidence_language}"
            direction_rows.setdefault(direction, []).append(direction_row)
    by_direction = {
        direction: _summarize_query_rows(rows, max_cosine_distance is not None)
        for direction, rows in sorted(direction_rows.items())
    }
    return {
        "query_count": len(queries),
        "recall_at_1": _mean(recalls[1]),
        "recall_at_3": _mean(recalls[3]),
        "recall_at_5": _mean(recalls[5]),
        "recall_at_10": _mean(recalls[10]),
        "mrr_at_10": _mean(reciprocal_ranks),
        "ndcg_at_10": _mean(ndcgs),
        "precision_at_10": _mean(precisions),
        "no_answer_false_positive_rate": (
            sum(no_answer_false_positives) / unanswerable_count
            if unanswerable_count and max_cosine_distance is not None
            else None
        ),
        "ranking_metrics_scope": "answerable queries only",
        "answerable_query_count": answerable_count,
        "unanswerable_query_count": unanswerable_count,
        "by_query_language": by_query_language,
        "by_query_evidence_language": by_direction,
        "per_query": per_query,
    }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _summarize_query_rows(
    rows: list[dict[str, Any]], has_distance_threshold: bool
) -> dict[str, Any]:
    answerable = [row for row in rows if row["answerable"]]
    unanswerable = [row for row in rows if not row["answerable"]]
    false_positives = [
        bool(row["no_answer_false_positive"])
        for row in unanswerable
        if row["no_answer_false_positive"] is not None
    ]
    summary: dict[str, Any] = {
        "query_count": len(rows),
        "answerable_query_count": len(answerable),
        "unanswerable_query_count": len(unanswerable),
    }
    metrics = (
        "recall_at_1",
        "recall_at_3",
        "recall_at_5",
        "recall_at_10",
        "reciprocal_rank",
        "ndcg_at_10",
        "precision_at_10",
    )
    for metric in metrics:
        values = [float(row[metric]) for row in answerable if row.get(metric) is not None]
        key = "mrr_at_10" if metric == "reciprocal_rank" else metric
        summary[key] = _mean(values)
    summary["no_answer_false_positive_rate"] = (
        sum(false_positives) / len(unanswerable)
        if has_distance_threshold and unanswerable and len(false_positives) == len(unanswerable)
        else None
    )
    return summary


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))]


def timed_embed(embedder: Embedder, texts: list[str]) -> tuple[list[list[float]], float]:
    started = time.perf_counter()
    vectors = embedder.embed(texts)
    return vectors, (time.perf_counter() - started) * 1000
