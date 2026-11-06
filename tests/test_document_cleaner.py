from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from examples.provider_backends.common.ingestion import _clean_converted_content


def test_markdown_structure_is_preserved_exactly():
    markdown = "# Heading\n\n- first item\n  - nested item\n\n| A | B |\n|---|---|\n| x | y |\n\n```python\nif  x:\n    print(  'keep spacing' )\n```\n"
    assert _clean_converted_content(Path("guide.md"), SimpleNamespace(content=markdown)) == markdown


def test_non_markdown_cleanup_retains_query_terms_and_reduces_whitespace():
    import pytest

    pytest.importorskip(
        "haystack",
        reason="Haystack is a mandatory package dependency; install project dependencies to exercise DocumentCleaner",
    )
    from haystack import Document

    raw = (
        "Industrial   platforms\n\n\n support   manufacturing systems and evidence-backed services."
    )
    cleaned = _clean_converted_content(Path("brief.txt"), Document(content=raw))
    query_terms = {
        "industrial",
        "platforms",
        "manufacturing",
        "systems",
        "evidence-backed",
        "services",
    }
    before = {term for term in query_terms if term in raw.casefold()}
    after = {term for term in query_terms if term in cleaned.casefold()}
    assert after == before
    assert len(cleaned) < len(raw)
    # This is lexical anchor preservation, not a claim of semantic-retrieval improvement.


def test_cleanup_does_not_change_lexical_top_result_for_reference_queries():
    import pytest

    pytest.importorskip(
        "haystack", reason="Install project dependencies to exercise the real Haystack cleaner"
    )
    from haystack import Document

    corpus = {
        "guide": "Industrial   platforms\n\n\n support   manufacturing systems and evidence-backed services.",
        "billing": "Billing support covers invoices, payments, and account statements.",
        "security": "Security guidance explains authentication, authorization, and data protection.",
    }
    cleaned = {
        key: _clean_converted_content(Path(f"{key}.txt"), Document(content=value))
        for key, value in corpus.items()
    }
    queries = [
        "industrial platforms manufacturing",
        "billing invoices payments",
        "security authentication data protection",
    ]

    def rank(documents, query):
        terms = set(query.casefold().split())
        return sorted(
            documents,
            key=lambda key: sum(term in documents[key].casefold().split() for term in terms),
            reverse=True,
        )

    before = [rank(corpus, query)[0] for query in queries]
    after = [rank(cleaned, query)[0] for query in queries]
    assert after == before
