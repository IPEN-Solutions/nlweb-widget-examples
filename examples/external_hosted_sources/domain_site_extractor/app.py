"""FastAPI example that runs the optional external-source adapter when enabled.

The configured extractor is attempted before Widget startup so a successfully generated
JSON-LD artifact is ingested by the ordinary content-sync lifecycle. Extraction failures
are recorded and do not prevent the existing Widget sources or endpoints from starting.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from nlweb_widget.content.service import load_content_sources
from nlweb_widget.content.state import StateStore
from nlweb_widget.integrations.fastapi_integration import mount_fastapi_nlweb

from examples.provider_backends.common.widget import build_provider_widget

from .demo import extract_to_artifact
from .registry import (
    prepare_runtime_source_registry,
    runtime_scenario_status,
    uses_example_owned_registry,
)

logger = logging.getLogger(__name__)

# The builder loads this example's .env too, but the domain argument is evaluated before
# the builder call, so load it first to keep domain identity consistent in direct runs.
_example_env = Path(__file__).resolve().parent / ".env"
if _example_env.is_file():
    from dotenv import load_dotenv

    load_dotenv(_example_env, override=True)

_site_url = os.getenv("NLWEB_EXTERNAL_SOURCE_SITE", "https://external-source.example/")
widget = build_provider_widget("sqlite", _site_url, __file__)
# Keep the checked-in registry immutable. The runtime copy resolves exact file paths, preserves
# consumer-declared corpus IDs, and excludes only the untouched placeholder fixture for real sites.
# An explicitly supplied custom registry remains the consumer's responsibility.
if uses_example_owned_registry(Path(__file__).resolve().parent):
    _runtime_registry = prepare_runtime_source_registry(Path(__file__).resolve().parent, _site_url)
    widget.settings = widget.settings.model_copy(
        update={"content_sources_file": str(_runtime_registry)}
    )


def _enabled(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "on"}


async def _startup_sync_report() -> dict[str, Any]:
    """Read the outcome written by Widget.startup() without triggering a second sync."""
    configured = {
        "mode": "widget.startup",
        "performed": False,
        "state_file": widget.settings.content_sync_state_file,
        "failed": 0,
        "succeeded": 0,
        "results": [],
    }
    if not (
        widget.settings.enabled
        and widget.settings.content_sync_enabled
        and widget.settings.content_sync_on_startup
    ):
        configured["message"] = (
            "Startup source synchronization was not requested because one or more Widget "
            "enablement settings are false."
        )
        return configured

    state_store = StateStore(widget.settings.content_sync_state_file)
    for source in load_content_sources(widget.settings.content_sources_file):
        if not source.enabled:
            continue
        state = await state_store.get(source.name)
        status = state.last_status if state and state.last_status else "unknown"
        result = {
            "source": source.name,
            "site": source.site,
            "kind": source.kind.value,
            "status": status,
            "total_loaded": len(state.item_keys) if state else 0,
            "message": (
                state.last_error
                if state and state.last_error
                else "Outcome read from the Widget startup sync state."
                if state
                else "No startup sync outcome was recorded for this source."
            ),
        }
        configured["results"].append(result)
    configured["performed"] = bool(configured["results"]) and all(
        item["status"] != "unknown" for item in configured["results"]
    )
    configured["failed"] = sum(item["status"] == "error" for item in configured["results"])
    configured["succeeded"] = sum(item["status"] == "ok" for item in configured["results"])
    configured["message"] = (
        "Read source outcomes recorded by Widget.startup(); no additional synchronization was run."
    )
    return configured


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Acquire external data only after explicit opt-in. The generated artifact is then
    # synchronized through the same Widget source registry as the checked-in corpus.
    if _enabled("NLWEB_EXTERNAL_SOURCE_ENABLED") or _enabled("NLWEB_EXTERNAL_SOURCE_LLM_ENABLED"):
        try:
            app.state.external_source_status = {
                "state": "extracting",
                "message": (
                    "External extraction was explicitly enabled; the configured adapter is running."
                ),
            }
            extraction_result = await extract_to_artifact()
            extraction_state = "completed"
            extraction_message = (
                "Extraction completed; the generated JSON-LD artifact is ready for normal "
                "Widget source synchronization."
            )
        except Exception as exc:  # Keep ordinary retrieval available if optional extraction fails.
            logger.exception("Optional external-source extraction failed; continuing app startup")
            extraction_result = None
            extraction_state = "failed"
            extraction_message = (
                "External extraction failed; the app will continue with the checked-in and "
                "any previously generated sources. See server logs and the status endpoint "
                "for details."
            )
            extraction_error = {"error_type": type(exc).__name__, "error": str(exc)}
        else:
            extraction_error = {}
    else:
        extraction_result = None
        extraction_state = "disabled"
        extraction_message = (
            "External extraction is disabled. Existing configured sources will still be "
            "synchronized."
        )
        extraction_error = {}

    # Refresh only the example-owned registry after extraction: an artifact created during
    # this lifespan must be enabled, while absent scenario artifacts remain explicitly disabled.
    if uses_example_owned_registry(Path(__file__).resolve().parent):
        _runtime_registry = prepare_runtime_source_registry(
            Path(__file__).resolve().parent, _site_url
        )
        widget.settings = widget.settings.model_copy(
            update={"content_sources_file": str(_runtime_registry)}
        )

    # Keep the provider-example lifecycle: Widget.startup() owns the one startup sync pass.
    # Do not disable that pass and then call sync_sources(force=True) separately; the duplicate
    # manual path bypassed the established startup behavior for directory-backed inbox sources.
    await widget.startup()
    try:
        sync_report = await _startup_sync_report()
        sync_failed = bool(sync_report["failed"])
        failed_sources = [
            str(item.get("source") or "unknown")
            for item in sync_report.get("results", [])
            if item.get("status") == "error"
        ]
        sync_unconfirmed = bool(
            widget.settings.enabled
            and widget.settings.content_sync_enabled
            and widget.settings.content_sync_on_startup
            and not sync_report["performed"]
        )
        app.state.external_source_status = {
            "state": (
                "ingestion_failed"
                if sync_failed
                else "sync_unconfirmed"
                if sync_unconfirmed
                else extraction_state
            ),
            "message": (
                "Configured content source(s) failed during Widget startup: "
                + ", ".join(failed_sources or ["unknown source"])
                + ". Inspect the corresponding source_sync.results entries and server logs."
                if sync_failed
                else "Widget startup did not record all enabled source outcomes; inspect the sync "
                "state file and server logs."
                if sync_unconfirmed
                else extraction_message
            ),
            "extraction": {
                "state": extraction_state,
                "result": extraction_result,
                **extraction_error,
            },
            "source_sync": sync_report,
            "scenario_artifacts": (
                runtime_scenario_status(_runtime_registry)
                if not os.getenv("NLWEB_CONTENT_SOURCES_FILE")
                else []
            ),
            "retrieval_store": widget.settings.retrieval_store,
            "sqlite_path": (
                widget.settings.sqlite_path if widget.settings.retrieval_store == "sqlite" else None
            ),
        }
        if sync_failed or sync_unconfirmed:
            logger.error(
                "Widget startup source synchronization needs attention: %s",
                sync_report,
            )
        yield
    finally:
        await widget.close()


app = FastAPI(
    title="External Hosted Domain Source Adapter Example",
    lifespan=lifespan,
)


@app.get("/external-source/status", tags=["external-source-example"])
async def external_source_status() -> dict[str, Any]:
    """Report whether optional extraction was disabled, completed, or failed."""
    return getattr(
        app.state,
        "external_source_status",
        {"state": "not_started", "message": "Application lifespan has not run."},
    )


mount_fastapi_nlweb(app, widget)
