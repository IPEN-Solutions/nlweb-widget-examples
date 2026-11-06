"""Helpers for loading scenario-owned Schema.org/JSON-LD domain projections."""

import json
import os
from pathlib import Path
from typing import Any

from nlweb_widget import ContentDocument, NLWebWidget
from nlweb_widget.content.models import ContentSourceKind
from nlweb_widget.content.service import ContentSyncService
from nlweb_widget.content.state import StateStore
from nlweb_widget.settings import NLWebSettings

from examples.provider_backends.common.ingestion import ingest_directory_async
from examples.provider_backends.common.widget import _replace_source_records, _SourceScopedStore


def load_documents(example_file: str | Path) -> list[Any]:
    """Load an example's local ``data.json`` into widget content documents."""
    import json

    from nlweb_widget import ContentDocument

    path = Path(example_file).with_name("data.json")
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"Expected a list of domain records in {path}")
    return [ContentDocument.model_validate(item) for item in raw]


def build_example_widget(domain: str, example_file: str | Path) -> NLWebWidget:
    """Build an example widget with environment-overridable projection settings."""
    example_dir = Path(example_file).resolve().parent
    source_path = example_dir / "data.json"
    registry_path = example_dir / "nlweb-sources.json"
    env_file = example_dir / ".env"
    if env_file.is_file():
        try:
            from dotenv import load_dotenv
        except ImportError as exc:
            raise RuntimeError(
                "Framework examples require python-dotenv to load their example-owned .env file"
            ) from exc
        load_dotenv(env_file, override=True)
    configured_registry = Path(
        os.getenv("NLWEB_CONTENT_SOURCES_FILE", str(registry_path))
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
        "content_sync_enabled": True,
        "content_sync_on_startup": True,
        "content_sources_file": str(source_path.with_name("nlweb-sources.json")),
        "content_sync_interval_seconds": 0.0,
        "content_sync_state_file": str(source_path.with_name(".nlweb-sync-state.json")),
    }
    env_map = {
        "enabled": "NLWEB_ENABLED",
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
    sync_service = ContentSyncService(state_store=StateStore(settings.content_sync_state_file))
    widget = NLWebWidget(domain=domain, settings=settings, sync_service=sync_service)

    async def load_example_source(source: Any) -> dict[str, Any]:
        source_name = source.name
        registry_entry = raw_registry_sources.get(source_name, {})
        registry_location = registry_entry.get("location")
        location = (
            registry_location
            if isinstance(registry_location, str) and "://" in registry_location
            else source.location
        )
        import re

        def resolve_location(match: re.Match[str]) -> str:
            variable = match.group(1)
            value = os.getenv(variable, "").strip()
            if not value:
                raise ValueError(
                    f"Source {source_name!r} requires environment variable {variable}; configure it or disable this source."
                )
            return value

        location = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", resolve_location, str(location))
        previous = await sync_service.state_store.get(source_name)
        scoped_store = _SourceScopedStore(widget.store, source_name)
        if location.lower().endswith("data.json") and not location.startswith(
            (
                "http://",
                "https://",
                "s3://",
                "gs://",
                "gcs://",
                "az://",
                "abfs://",
                "couchdb+http://",
                "couchdb+https://",
            )
        ):
            import json

            payload = json.loads(Path(location).read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                raise ValueError(f"Scenario source {location} must contain a JSON list")
            documents = [ContentDocument.model_validate(item) for item in payload]
            for document in documents:
                # Keep a source-specific ID and use registry site as the query scope.
                document = document.model_copy(update={"site": source.site})
                await scoped_store.upsert(document)
            raw_keys = [document.id for document in documents]
            result = {
                "total_loaded": len(documents),
                "item_keys": raw_keys,
                "message": "Loaded scenario JSON records",
            }
        else:
            result = await ingest_directory_async(
                location,
                scoped_store,
                site=source.site,
                url=source.metadata.get("url"),
                embedding_provider=getattr(widget, "_embedding_provider", None),
                remote_storage_options=getattr(source, "remote_storage_options", None)
                or source.metadata.get("remote_storage_options", {}),
                document_store_options=source.metadata.get("document_store_options", {}),
            )
        current_keys, deleted_count = await _replace_source_records(
            widget.store,
            source_name,
            list(result.get("item_keys", [])),
            previous.item_keys if previous else set(),
        )
        result["item_keys"] = sorted(current_keys)
        result["deleted_count"] = int(result.get("deleted_count", 0)) + deleted_count
        return result

    sync_service.register_loader(ContentSourceKind.CUSTOM, load_example_source)
    return widget


def example_source_file(example_file: str | Path) -> Path:
    """Return the checked-in source registry for a framework example."""
    return Path(example_file).with_name("nlweb-sources.json")
