from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from examples.provider_backends.common import ingestion


@pytest.mark.asyncio
async def test_remote_storage_options_forwarded_to_fsspec(monkeypatch):
    seen = {}

    class FakeFS:
        def isfile(self, path):
            return False

        def find(self, path):
            seen["find"] = path
            return [f"{path}/sample.jsonld"]

        def isdir(self, path):
            return False

        def open(self, path, mode):
            from io import BytesIO

            return BytesIO(b'{"@type":"Organization","name":"Remote"}')

    def url_to_fs(url, **kwargs):
        seen["url"] = url
        seen["kwargs"] = kwargs
        return FakeFS(), "bucket"

    monkeypatch.setitem(
        sys.modules, "fsspec", SimpleNamespace(core=SimpleNamespace(url_to_fs=url_to_fs))
    )
    monkeypatch.setenv("TEST_REMOTE_SECRET", "resolved-secret")
    monkeypatch.setenv("TEST_REMOTE_KEY", "resolved-key")
    monkeypatch.setenv("TEST_REMOTE_ENDPOINT", "s3.eu-central-003.backblazeb2.com")
    monkeypatch.setenv("TEST_REMOTE_REGION", "us-west-002")

    class Store:
        async def upsert(self, document):
            return None

    try:
        await ingestion.ingest_directory_async(
            "s3://bucket/",
            Store(),
            site="remote",
            embedding_provider=None,
            remote_storage_options={
                "key": "${TEST_REMOTE_KEY}",
                "secret": "${TEST_REMOTE_SECRET}",
                "prefix": "domain/inbox",
                "client_kwargs": {
                    "endpoint_url": "${TEST_REMOTE_ENDPOINT}",
                    "region_name": "${TEST_REMOTE_REGION}",
                },
            },
        )
    except Exception:
        # This fake filesystem exercises URI/options forwarding; converter availability is unrelated.
        pass
    assert seen["url"] == "s3://bucket/"
    assert seen["kwargs"] == {
        "key": "resolved-key",
        "secret": "resolved-secret",
        "client_kwargs": {
            "endpoint_url": "https://s3.eu-central-003.backblazeb2.com",
            "region_name": "us-west-002",
        },
    }
    assert seen["find"] == "bucket/domain/inbox"
