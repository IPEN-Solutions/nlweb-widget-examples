from __future__ import annotations

import pytest
from nlweb_widget import ContentDocument

from examples.provider_backends.common.widget import _replace_source_records, _SourceScopedStore


class Store:
    def __init__(self):
        self.docs = {}
        self.deleted = []

    async def upsert(self, document):
        self.docs[document.id] = document

    async def delete(self, ids):
        self.deleted.extend(ids)
        for item in ids:
            self.docs.pop(item, None)
        return len(ids)


@pytest.mark.asyncio
async def test_source_namespaces_same_artifact_name_and_replaces_only_own_stale_ids():
    store = Store()
    a = _SourceScopedStore(store, "authoritative_domain")
    b = _SourceScopedStore(store, "remote_domain")
    base = ContentDocument(
        id="source:domain.jsonld", url="https://example.org/", title="Domain", content="old"
    )
    await a.upsert(base)
    await b.upsert(base.model_copy(update={"content": "other source"}))
    assert set(store.docs) == {
        "source-registry:authoritative_domain:source:domain.jsonld",
        "source-registry:remote_domain:source:domain.jsonld",
    }
    current, deleted = await _replace_source_records(
        store,
        "authoritative_domain",
        ["source:domain.jsonld"],
        {
            "source-registry:authoritative_domain:source:domain.jsonld",
            "source-registry:authoritative_domain:source:removed.md",
        },
    )
    assert current == {"source-registry:authoritative_domain:source:domain.jsonld"}
    assert deleted == 1
    assert "source-registry:remote_domain:source:domain.jsonld" in store.docs
    assert "source-registry:authoritative_domain:source:removed.md" in store.deleted


def test_registry_source_names_are_unique():
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for path in root.rglob("nlweb-sources.json"):
        sources = json.loads(path.read_text(encoding="utf-8")).get("sources", [])
        names = [item.get("name") for item in sources]
        assert len(names) == len(set(names)), path


def test_partial_sync_preserves_previous_source_ids() -> None:
    from examples.provider_backends.common.widget import _partial_sync_item_keys

    previous = {
        "source-registry:remote:source:healthy-before.jsonld",
        "source-registry:remote:source:temporarily-skipped.docx",
    }
    current = _partial_sync_item_keys("remote", ["source:healthy-before.jsonld"], previous)
    assert current == previous
