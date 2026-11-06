import json
from pathlib import Path

import pytest

from examples.provider_backends.common.ingestion import ingest_directory_async


class FakeStore:
    def __init__(self):
        self.documents = []

    async def upsert(self, document):
        self.documents.append(document)


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "rows": [
                {
                    "id": "service:industrial-platforms",
                    "doc": {
                        "_id": "service:industrial-platforms",
                        "_rev": "2-abc",
                        "title": "Industrial platforms",
                        "type": "Service",
                        "url": "https://example.org/services/industrial-platforms",
                        "content": "Evidence-backed service description.",
                        "grounding": {
                            "source": "https://example.org/services/industrial-platforms"
                        },
                        "citations": [
                            {
                                "label": "Service page",
                                "source_url": "https://example.org/services/industrial-platforms",
                            }
                        ],
                        "schema_refs": ["https://schema.org/Service"],
                    },
                },
                {"id": "_design/example", "doc": {"_id": "_design/example", "content": "skip"}},
                {"id": "empty", "doc": {"_id": "empty", "title": "Empty"}},
            ]
        }


class FakeAsyncClient:
    last_url = None
    last_auth = None
    last_trust_env = None

    def __init__(self, *, timeout, auth=None, trust_env=True):
        self.timeout = timeout
        self.auth = auth
        FakeAsyncClient.last_trust_env = trust_env

    async def __aenter__(self):
        FakeAsyncClient.last_auth = self.auth
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url):
        FakeAsyncClient.last_url = url
        return FakeResponse()


@pytest.mark.asyncio
async def test_couchdb_ingestion_keeps_document_evidence_without_manifest(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setenv("NLWEB_COUCHDB_URL", "http://localhost:5984")
    monkeypatch.setenv("NLWEB_COUCHDB_DATABASE", "nlweb_domain")
    monkeypatch.setenv("NLWEB_DOCUMENT_STORE_USERNAME", "example-user")
    monkeypatch.setenv("NLWEB_DOCUMENT_STORE_PASSWORD", "example-password")
    store = FakeStore()

    result = await ingest_directory_async(
        "couchdb+http://127.0.0.1:5984/ignored",
        store,
        site="example.org",
        url="https://example.org/",
        embedding_provider=object(),
        remote_storage_options={
            "username": "${NLWEB_DOCUMENT_STORE_USERNAME}",
            "password": "${NLWEB_DOCUMENT_STORE_PASSWORD}",
        },
    )

    assert result["status"] == "ok"
    assert result["indexed"] == 1
    assert len(store.documents) == 1
    document = store.documents[0]
    assert document.id == "couchdb:nlweb_domain:service:industrial-platforms"
    assert document.url == "https://example.org/services/industrial-platforms"
    assert document.metadata["grounding"]["source"].endswith("industrial-platforms")
    assert document.metadata["citations"][0]["label"] == "Service page"
    assert document.metadata["schema_refs"] == ["https://schema.org/Service"]
    assert FakeAsyncClient.last_auth == ("example-user", "example-password")
    assert FakeAsyncClient.last_trust_env is False
    assert (
        FakeAsyncClient.last_url
        == "http://localhost:5984/nlweb_domain/_all_docs?include_docs=true&limit=500"
    )


def test_couchdb_ingestion_proxy_policy_is_loopback_scoped():
    from examples.provider_backends.common import ingestion

    assert ingestion._uses_environment_proxy("http://localhost:5984/db") is False
    assert ingestion._uses_environment_proxy("http://127.0.0.1:5984/db") is False
    assert ingestion._uses_environment_proxy("https://couch.example.com/db") is True


def test_document_store_registry_entry_is_disabled_by_default():
    root = Path(__file__).resolve().parents[1]
    path = root / "examples/external_hosted_sources/domain_site_extractor/nlweb-sources.json"
    sources = json.loads(path.read_text(encoding="utf-8"))["sources"]
    entry = next(
        source for source in sources if source["name"] == "authoritative_domain_document_store"
    )
    assert entry["enabled"] is False
    assert entry["location"] == "couchdb+${NLWEB_COUCHDB_URL}/${NLWEB_COUCHDB_DATABASE}"
    assert "grounding" not in entry["metadata"]  # evidence belongs to each stored document
    assert "username" in entry["metadata"]["document_store_options"]
    assert entry["metadata"]["document_store_options"]["database"] == "${NLWEB_COUCHDB_DATABASE}"
    assert "nlweb_domain" not in entry["location"]
    assert "document_store_location" not in entry["metadata"]


def test_all_env_examples_document_generic_remote_options_and_document_store():
    root = Path(__file__).resolve().parents[1]
    env_examples = list(root.rglob(".env.example"))
    assert env_examples
    for path in env_examples:
        # The embedding benchmark deliberately owns a separate, benchmark-only
        # environment contract; it must not acquire unrelated provider settings.
        if "embedding_benchmark" in path.parts:
            continue
        content = path.read_text(encoding="utf-8")
        assert "NLWEB_REMOTE_STORAGE_OPTIONS_JSON=" not in content, path
        assert "NLWEB_REMOTE_STORAGE_BUCKET=" in content, path
        assert "NLWEB_REMOTE_STORAGE_ENDPOINT_URL=" in content, path
        assert "NLWEB_COUCHDB_URL=" in content, path
        assert "NLWEB_COUCHDB_DATABASE=" in content, path
        assert "NLWEB_DOCUMENT_STORE_TIMEOUT_SECONDS=" in content, path
        assert "NLWEB_EXTERNAL_SOURCE_EXTRACTOR_BACKEND=" in content, path
        for required in (
            "NLWEB_REMOTE_STORAGE_ACCESS_KEY=",
            "NLWEB_REMOTE_STORAGE_SECRET_KEY=",
            "NLWEB_REMOTE_STORAGE_REGION=",
            "NLWEB_DOCUMENT_STORE_USERNAME=",
            "NLWEB_DOCUMENT_STORE_PASSWORD=",
        ):
            assert required in content, (path, required)
    adapter_env = root / "examples/external_hosted_sources/domain_site_extractor/.env.example"
    adapter_content = adapter_env.read_text(encoding="utf-8")
    assert "NLWEB_COUCHDB_URL=" in adapter_content
    assert "NLWEB_DOCUMENT_STORE_TIMEOUT_SECONDS=" in adapter_content


def test_remote_storage_extra_installs_s3_filesystem_backend():
    root = Path(__file__).resolve().parents[1]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    remote_extra = pyproject.split("remote-storage = [", 1)[1].split("]", 1)[0]
    assert "fsspec" in remote_extra
    assert "s3fs" in remote_extra


def test_registry_options_are_only_present_for_remote_storage():
    root = Path(__file__).resolve().parents[1]
    registries = list(root.rglob("nlweb-sources.json"))
    assert registries
    for path in registries:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for source in payload.get("sources", []):
            if source.get("name") == "authoritative_domain_remote_storage":
                assert "remote_storage_options" in source, f"{path}: {source.get('name')}"
            else:
                assert "remote_storage_options" not in source, f"{path}: {source.get('name')}"
            metadata = source.get("metadata", {})
            assert "document_store_location" not in metadata, f"{path}: {source.get('name')}"
            assert "enabled_when_artifact_exists" not in metadata, f"{path}: {source.get('name')}"


def test_every_registry_has_disabled_couchdb_source_and_source_identity_is_unique():
    root = Path(__file__).resolve().parents[1]
    registries = list(root.rglob("nlweb-sources.json"))
    assert registries
    for path in registries:
        # This registry is a local retrieval fixture, not a provider registry.
        if "embedding_benchmark" in path.parts:
            continue
        sources = json.loads(path.read_text(encoding="utf-8")).get("sources", [])
        names = [source.get("name") for source in sources]
        assert len(names) == len(set(names)), path
        entry = next(
            source
            for source in sources
            if source.get("name") == "authoritative_domain_document_store"
        )
        remote = next(
            source
            for source in sources
            if source.get("name") == "authoritative_domain_remote_storage"
        )
        assert remote["enabled"] is False
        assert remote["location"] == "s3://${NLWEB_REMOTE_STORAGE_BUCKET}/"
        assert "remote_location" not in remote.get("metadata", {})
        assert remote["remote_storage_options"]["key"] == "${NLWEB_REMOTE_STORAGE_ACCESS_KEY}"
        assert remote["remote_storage_options"]["secret"] == "${NLWEB_REMOTE_STORAGE_SECRET_KEY}"
        assert (
            remote["remote_storage_options"]["client_kwargs"]["region_name"]
            == "${NLWEB_REMOTE_STORAGE_REGION}"
        )
        assert (
            remote["remote_storage_options"]["client_kwargs"]["endpoint_url"]
            == "${NLWEB_REMOTE_STORAGE_ENDPOINT_URL}"
        )
        scenario = next(
            (source for source in sources if source.get("name") == "scenario-domain-data"), None
        )
        if scenario is not None:
            assert scenario["kind"] == "custom"
        assert entry["enabled"] is False, path
        assert (
            entry["metadata"]["document_store_options"]["database"] == "${NLWEB_COUCHDB_DATABASE}"
        )
        assert "document_store_location" not in entry["metadata"]


def test_each_owned_inbox_has_manifest_and_initializer():
    root = Path(__file__).resolve().parents[1]
    inboxes = list(root.glob("examples/**/content/inbox"))
    assert inboxes
    for inbox in inboxes:
        assert (inbox / "nlweb-evidence-manifest.json").is_file(), inbox
        assert (inbox.parent / "scripts" / "initialize_couchdb.py").is_file(), inbox
