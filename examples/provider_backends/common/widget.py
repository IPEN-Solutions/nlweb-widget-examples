"""Build a provider-backed Widget without changing the production package."""

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from nlweb_widget import NLWebWidget
from nlweb_widget.content.models import ContentSourceKind
from nlweb_widget.content.service import ContentSyncService
from nlweb_widget.content.state import StateStore
from nlweb_widget.settings import NLWebSettings

from .embedding import build_embedding_provider
from .ingestion import ingest_directory_async


async def _replace_source_records(
    store: Any, source_name: str, raw_item_keys: list[str], previous_item_keys: set[str] | None
) -> tuple[set[str], int]:
    """Return current namespaced IDs and remove stale IDs from this source only."""
    current = {f"source-registry:{source_name}:{key}" for key in raw_item_keys}
    stale = sorted((previous_item_keys or set()) - current)
    deleted = 0
    if stale:
        delete = getattr(store, "delete", None)
        if delete is None:
            raise RuntimeError(
                f"Source {source_name!r} removed records, but retrieval store does not support delete(ids); "
                "stale records were not silently ignored."
            )
        deleted = int(await delete(stale) or 0)
    return current, deleted


class _SourceScopedStore:
    """Namespace indexed document IDs by registry source name."""

    def __init__(self, store: Any, source_name: str) -> None:
        self._store = store
        self._source_name = source_name

    def _scoped(self, document: Any) -> Any:
        metadata = dict(getattr(document, "metadata", {}) or {})
        metadata["source_name"] = self._source_name
        return document.model_copy(
            update={
                "id": f"source-registry:{self._source_name}:{document.id}",
                "metadata": metadata,
            }
        )

    async def upsert(self, document: Any) -> Any:
        return await self._store.upsert(self._scoped(document))

    async def upsert_many(self, documents: Any) -> Any:
        scoped = [self._scoped(document) for document in documents]
        if hasattr(self._store, "upsert_many"):
            return await self._store.upsert_many(scoped)
        for document in scoped:
            await self._store.upsert(document)
        return len(scoped)


def _registry_source_location(
    registry_entry: dict[str, Any], source: Any, registry_directory: Path | None = None
) -> str:
    """Resolve relative local paths against the registry that declared them.

    Raw registry strings remain authoritative for URI schemes and environment placeholders,
    but a relative filesystem path must never be interpreted against the process CWD.
    """
    value = registry_entry.get("location")
    if not isinstance(value, str) or not value.strip():
        value = str(source.location)
    value = value.strip()
    if value.startswith(
        (
            "s3://",
            "gs://",
            "gcs://",
            "az://",
            "abfs://",
            "http://",
            "https://",
            "memory://",
            "couchdb+http://",
            "couchdb+https://",
            "couchdb+${",
        )
    ):
        return value
    parsed = urlsplit(value)
    if parsed.scheme and parsed.scheme.lower() != "file":
        return value
    if parsed.scheme.lower() == "file":
        raw_path = unquote(parsed.path)
        # file:///C:/... is represented with a leading slash on Windows.
        if os.name == "nt" and len(raw_path) > 2 and raw_path[0] == "/" and raw_path[2] == ":":
            raw_path = raw_path[1:]
        path = Path(raw_path)
    else:
        path = Path(value).expanduser()
    if not path.is_absolute():
        path = ((registry_directory or Path.cwd()) / path).resolve()
    return str(path)


def _partial_sync_item_keys(
    source_name: str, raw_item_keys: list[str], previous_item_keys: set[str] | None
) -> set[str]:
    """Keep prior IDs during partial syncs so skipped artifacts cannot trigger deletion."""
    current = {f"source-registry:{source_name}:{key}" for key in raw_item_keys}
    return current | set(previous_item_keys or set())


def build_provider_widget(provider: str, domain: str, example_file: str | Path) -> NLWebWidget:
    """Create a provider example using Widget settings and a CUSTOM source loader."""
    example_dir = Path(example_file).resolve().parent
    source_file = example_dir / "nlweb-sources.json"
    provider_env = example_dir / ".env"
    if provider_env.is_file():
        try:
            from dotenv import load_dotenv
        except ImportError as exc:
            raise RuntimeError(
                "Provider examples require python-dotenv to load their provider-owned .env file."
            ) from exc
        # Provider examples deliberately own their runtime environment.  This prevents a
        # workspace/root .env (or VS Code inherited environment) from silently selecting
        # another retrieval backend or vector-index configuration.
        load_dotenv(provider_env, override=True)
    configured_registry = Path(
        os.getenv("NLWEB_CONTENT_SOURCES_FILE", str(source_file))
    ).expanduser()
    if not configured_registry.is_absolute():
        configured_registry = (example_dir / configured_registry).resolve()
    raw_registry_sources = (
        {
            item.get("name"): item
            for item in json.loads(configured_registry.read_text(encoding="utf-8")).get(
                "sources", []
            )
            if isinstance(item, dict) and item.get("name")
        }
        if configured_registry.is_file()
        else {}
    )
    settings = NLWebSettings(_env_file=None)
    updates: dict[str, Any] = {}
    defaults = {
        "enabled": True,
        "retrieval_store": provider,
        "content_sync_enabled": True,
        "content_sync_on_startup": True,
        "content_sources_file": str(source_file),
        "content_sync_interval_seconds": 0.0,
        "content_sync_state_file": str(example_dir / ".nlweb-sync-state.json"),
    }
    env_map = {
        "enabled": "NLWEB_ENABLED",
        "retrieval_store": "NLWEB_RETRIEVAL_STORE",
        "content_sync_enabled": "NLWEB_CONTENT_SYNC_ENABLED",
        "content_sync_on_startup": "NLWEB_CONTENT_SYNC_ON_STARTUP",
        "content_sources_file": "NLWEB_CONTENT_SOURCES_FILE",
        "content_sync_interval_seconds": "NLWEB_CONTENT_SYNC_INTERVAL_SECONDS",
        "content_sync_state_file": "NLWEB_CONTENT_SYNC_STATE_FILE",
    }
    for field, value in defaults.items():
        if env_map[field] not in os.environ:
            updates[field] = value
    settings = settings.model_copy(update=updates)
    embedder = build_embedding_provider()
    sync_service = ContentSyncService(
        state_store=StateStore(settings.content_sync_state_file),
    )
    widget = NLWebWidget(
        domain=domain,
        settings=settings,
        embedding_provider=embedder,
        sync_service=sync_service,
    )

    async def load_provider_sources(source: Any) -> dict[str, Any]:
        # Registry `name` is the stable source identity. Namespace document IDs so
        # complementary sources never overwrite each other merely because filenames match.
        source_name = source.name
        registry_entry = raw_registry_sources.get(source_name, {})
        # The parsed model may coerce URI-like strings containing unresolved env
        # placeholders (notably couchdb+${NLWEB_COUCHDB_URL}/...) into a filesystem path.
        # The raw JSON registry is the source of truth for URI schemes and placeholders.
        raw_location = _registry_source_location(registry_entry, source, configured_registry.parent)

        def resolve_location(match: re.Match[str]) -> str:
            variable = match.group(1)
            value = os.getenv(variable, "").strip()
            if not value:
                raise ValueError(
                    f"Source {source_name!r} requires environment variable {variable}; "
                    "configure it or disable this source."
                )
            return value

        raw_location = re.sub(
            r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", resolve_location, str(raw_location)
        )
        is_document_store = str(raw_location).startswith(("couchdb+http://", "couchdb+https://"))
        remote_options = getattr(source, "remote_storage_options", None) or source.metadata.get(
            "remote_storage_options", {}
        )
        previous = await sync_service.state_store.get(source_name)
        scoped_store = _SourceScopedStore(widget.store, source_name)
        result = await ingest_directory_async(
            raw_location,
            scoped_store,
            site=source.site,
            url=source.metadata.get("url"),
            embedding_provider=embedder,
            exclude_filenames=tuple(source.metadata.get("excluded_filenames", ())),
            remote_storage_options=remote_options,
            document_store_options=source.metadata.get("document_store_options", {})
            if is_document_store
            else None,
        )
        raw_keys = result.get("item_keys", [])
        previous_keys = previous.item_keys if previous else set()
        if result.get("partial"):
            # A partial snapshot is not authoritative for deletion: preserve prior IDs
            # until the conflicting artifact/manifest is repaired and a clean sync runs.
            current_keys = _partial_sync_item_keys(source_name, raw_keys, previous_keys)
            deleted_count = 0
            result["message"] = (
                result.get("message") or "Source partially synchronized"
            ) + "; stale-record deletion withheld because this sync skipped artifacts"
        else:
            current_keys, deleted_count = await _replace_source_records(
                widget.store, source_name, raw_keys, previous_keys
            )
        result["item_keys"] = sorted(current_keys)
        result["deleted_count"] = int(result.get("deleted_count", 0)) + int(deleted_count or 0)
        result["message"] = (
            result.get("message") or "Source synchronized"
        ) + f"; source={source_name}; stale records removed={deleted_count}"
        return result

    sync_service.register_loader(ContentSourceKind.CUSTOM, load_provider_sources)
    return widget
