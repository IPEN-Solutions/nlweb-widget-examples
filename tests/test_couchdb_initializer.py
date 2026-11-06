import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "examples/external_hosted_sources/domain_site_extractor/content/scripts/initialize_couchdb.py"
)
spec = importlib.util.spec_from_file_location("initialize_couchdb", SCRIPT)
initializer = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(initializer)


def test_seed_documents_match_manifest_and_preserve_evidence_attributes():
    docs = initializer.build_seed_documents()
    by_artifact = {doc["artifact"]: doc for doc in docs}
    assert set(by_artifact) == {
        "domain.jsonld",
        "capabilities.md",
        "capabilities.txt",
        "digital-engineering-brief.pdf",
        "industrial-platforms.pptx",
    }
    organization = by_artifact["domain.jsonld"]
    assert organization["type"] == "Organization"
    assert organization["url"] == "https://example.org/organization"
    assert organization["grounding"]["source"] == "https://example.org/organization"
    assert organization["schema_refs"] == [
        "https://schema.org/Organization",
        "https://example.org/schemas/organization-v1.json",
    ]
    markdown = by_artifact["capabilities.md"]
    assert markdown["type"] == "Article"
    assert markdown["citations"][0]["source_url"] == "https://example.org/services/capabilities"
    assert markdown["content"]


def test_seed_refuses_manifest_artifact_mismatch(tmp_path):
    (tmp_path / "a.txt").write_text("source", encoding="utf-8")
    (tmp_path / initializer.MANIFEST_NAME).write_text(
        json.dumps({"artifacts": [{"artifact": "missing.txt", "type": "Article"}]}),
        encoding="utf-8",
    )
    with pytest.raises(initializer.InitializationError, match="do not match"):
        initializer.build_seed_documents(tmp_path)


def test_seed_refuses_conflicting_source_and_manifest_grounding(tmp_path):
    (tmp_path / "domain.jsonld").write_text(
        json.dumps(
            {
                "@context": "https://schema.org",
                "@type": "Organization",
                "name": "Test",
                "description": "Text",
                "grounding": {"source": "https://wrong.example/"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / initializer.MANIFEST_NAME).write_text(
        json.dumps(
            {
                "artifacts": [
                    {
                        "artifact": "domain.jsonld",
                        "type": "Organization",
                        "grounding": {"source": "https://right.example/"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(
        initializer.InitializationError, match="Conflicting source and manifest grounding"
    ):
        initializer.build_seed_documents(tmp_path)


def test_couchdb_endpoint_rejects_embedded_credentials():
    with pytest.raises(initializer.InitializationError, match="Do not embed CouchDB credentials"):
        initializer._safe_endpoint("http://user:secret@127.0.0.1:5984", "nlweb_domain")


def test_proxy_environment_is_bypassed_only_for_loopback():
    assert initializer._uses_environment_proxy("http://localhost:5984/db") is False
    assert initializer._uses_environment_proxy("http://127.0.0.1:5984/db") is False
    assert initializer._uses_environment_proxy("http://127.42.0.5:5984/db") is False
    assert initializer._uses_environment_proxy("http://[::1]:5984/db") is False
    assert initializer._uses_environment_proxy("https://couch.example.com/db") is True


def test_initializer_explains_missing_configuration(monkeypatch):
    monkeypatch.delenv("NLWEB_COUCHDB_URL", raising=False)
    monkeypatch.setattr(initializer, "load_dotenv", lambda *args, **kwargs: None)
    with pytest.raises(initializer.InitializationError, match="CouchDB is not configured"):
        initializer.initialize()


def test_initializer_creates_database_and_bulk_seeds_without_logging_secrets(monkeypatch, capsys):
    monkeypatch.setenv("NLWEB_COUCHDB_URL", "http://127.0.0.1:5984")
    monkeypatch.setenv("NLWEB_COUCHDB_DATABASE", "nlweb_domain")
    monkeypatch.setenv("NLWEB_DOCUMENT_STORE_USERNAME", "example-user")
    monkeypatch.setenv("NLWEB_DOCUMENT_STORE_PASSWORD", "top-secret")
    monkeypatch.setattr(initializer, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        initializer,
        "build_seed_documents",
        lambda: [{"_id": "artifact:sample.txt", "content": "sample"}],
    )

    class Response:
        def __init__(self, status_code, payload=None, text=""):
            self.status_code = status_code
            self._payload = payload or []
            self.text = text

        def json(self):
            return self._payload

    class Client:
        last_auth = None
        last_trust_env = None
        posted = None

        def __init__(self, *, timeout, auth=None, trust_env=True):
            Client.last_auth = auth
            Client.trust_env = trust_env

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def put(self, url):
            assert url == "http://127.0.0.1:5984/nlweb_domain"
            return Response(201)

        def get(self, url):
            return Response(404)

        def post(self, url, json):
            Client.posted = (url, json)
            return Response(201, [{"ok": True, "id": "artifact:sample.txt"}])

    monkeypatch.setattr(initializer.httpx, "Client", Client)
    assert initializer.initialize() == 0
    output = capsys.readouterr().out
    assert "added: 1" in output
    assert "top-secret" not in output
    assert Client.last_auth == ("example-user", "top-secret")
    assert Client.trust_env is False
    assert Client.posted[0].endswith("/nlweb_domain/_bulk_docs")


def test_initializer_does_not_overwrite_conflicting_existing_document(monkeypatch):
    monkeypatch.setenv("NLWEB_COUCHDB_URL", "http://127.0.0.1:5984")
    monkeypatch.delenv("NLWEB_DOCUMENT_STORE_USERNAME", raising=False)
    monkeypatch.delenv("NLWEB_DOCUMENT_STORE_PASSWORD", raising=False)
    monkeypatch.setattr(initializer, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        initializer,
        "build_seed_documents",
        lambda: [{"_id": "artifact:sample.txt", "content": "seed"}],
    )

    class Response:
        status_code = 412
        text = ""

        def __init__(self, status_code, payload=None):
            self.status_code = status_code
            self.payload = payload

        def json(self):
            return self.payload

    class Client:
        posted = False

        def __init__(self, *, timeout, auth=None, trust_env=True):
            Client.trust_env = trust_env

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def put(self, url):
            return Response(412)

        def get(self, url):
            return Response(
                200, {"_id": "artifact:sample.txt", "_rev": "1-abc", "content": "consumer-edited"}
            )

        def post(self, url, json):
            Client.posted = True
            return Response(201, [])

    monkeypatch.setattr(initializer.httpx, "Client", Client)
    with pytest.raises(
        initializer.InitializationError, match="already exists with different content"
    ):
        initializer.initialize()
    assert not Client.posted
