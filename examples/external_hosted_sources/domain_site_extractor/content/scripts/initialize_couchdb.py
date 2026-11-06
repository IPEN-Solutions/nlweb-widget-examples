"""Seed the example CouchDB database from the checked-in inbox and evidence manifest.

This is an opt-in, idempotent first-use convenience. It never deletes documents or
silently overwrites consumer-edited records.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from dotenv import load_dotenv

EXAMPLE_ROOT = Path(__file__).resolve().parents[2]
INBOX = EXAMPLE_ROOT / "content" / "inbox"
MANIFEST_NAME = "nlweb-evidence-manifest.json"
SUPPORTED = {".json", ".jsonld", ".md", ".txt", ".pdf", ".pptx"}


class InitializationError(RuntimeError):
    """Expected setup, manifest, source, or CouchDB failure with actionable context."""


def _read_text_artifact(path: Path) -> tuple[str, str, dict[str, Any]]:
    suffix = path.suffix.casefold()
    if suffix in {".json", ".jsonld"}:
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InitializationError(
                f"Cannot parse structured artifact {path.name}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise InitializationError(f"Structured artifact {path.name} must contain a JSON object")
        schema = payload.get("schema_object", payload)
        if not isinstance(schema, dict):
            raise InitializationError(
                f"Structured artifact {path.name} has a non-object schema payload"
            )
        graph = schema.get("@graph")
        primary = (
            next((row for row in graph if isinstance(row, dict)), {})
            if isinstance(graph, list)
            else {}
        )
        title = str(
            payload.get("title")
            or payload.get("name")
            or primary.get("name")
            or schema.get("name")
            or path.stem
        )
        content = str(
            payload.get("description")
            or primary.get("description")
            or schema.get("description")
            or json.dumps(schema, ensure_ascii=False)
        )
        source_type = schema.get("@type") or primary.get("@type")
        source_url = (
            payload.get("url")
            or schema.get("url")
            or primary.get("url")
            or payload.get("@id")
            or schema.get("@id")
            or primary.get("@id")
        )
        return (
            title,
            content,
            {"source_type": source_type, "source_url": source_url, "schema_object": schema},
        )
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            text = "\n\n".join((page.extract_text() or "") for page in reader.pages).strip()
        except Exception as exc:
            raise InitializationError(
                f"Cannot extract text from PDF artifact {path.name}: {exc}"
            ) from exc
        if not text:
            raise InitializationError(
                f"PDF artifact {path.name} contains no extractable text; OCR is not performed"
            )
        return (
            path.stem.replace("-", " "),
            text,
            {"source_type": None, "source_url": None, "schema_object": {}},
        )
    if suffix == ".pptx":
        try:
            from pptx import Presentation

            presentation = Presentation(str(path))
            chunks = []
            for number, slide in enumerate(presentation.slides, start=1):
                lines = [
                    shape.text.strip()
                    for shape in slide.shapes
                    if getattr(shape, "has_text_frame", False) and shape.text.strip()
                ]
                if lines:
                    chunks.append(f"Slide {number}\n" + "\n".join(lines))
            text = "\n\n".join(chunks).strip()
        except Exception as exc:
            raise InitializationError(
                f"Cannot extract text from PowerPoint artifact {path.name}: {exc}"
            ) from exc
        if not text:
            raise InitializationError(
                f"PowerPoint artifact {path.name} contains no extractable text"
            )
        return (
            path.stem.replace("-", " "),
            text,
            {"source_type": None, "source_url": None, "schema_object": {}},
        )
    try:
        text = path.read_text(encoding="utf-8-sig").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise InitializationError(f"Cannot read text artifact {path.name}: {exc}") from exc
    if not text:
        raise InitializationError(f"Text artifact {path.name} is empty")
    return (
        path.stem.replace("-", " "),
        text,
        {"source_type": None, "source_url": None, "schema_object": {}},
    )


def build_seed_documents(inbox: Path = INBOX) -> list[dict[str, Any]]:
    """Validate manifest-to-inbox mapping and convert every declared artifact to a CouchDB doc."""
    manifest_path = inbox / MANIFEST_NAME
    if not manifest_path.is_file():
        raise InitializationError(f"Required evidence manifest is missing: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InitializationError(f"Cannot parse evidence manifest {manifest_path}: {exc}") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("artifacts"), list):
        raise InitializationError("Evidence manifest must contain an 'artifacts' list")

    entries: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(manifest["artifacts"]):
        if not isinstance(entry, dict) or not isinstance(entry.get("artifact"), str):
            raise InitializationError(
                f"Manifest artifacts[{index}] must declare a relative 'artifact' path"
            )
        key = entry["artifact"].replace("\\", "/")
        relative = Path(key)
        if relative.is_absolute() or ".." in relative.parts or key.startswith("/"):
            raise InitializationError(f"Manifest artifact path is unsafe: {key!r}")
        if key in entries:
            raise InitializationError(f"Manifest contains duplicate artifact entry: {key}")
        entries[key] = entry

    discovered = {
        p.name
        for p in inbox.iterdir()
        if p.is_file() and p.name != MANIFEST_NAME and p.suffix.casefold() in SUPPORTED
    }
    declared = set(entries)
    if discovered != declared:
        missing = sorted(declared - discovered)
        unlisted = sorted(discovered - declared)
        raise InitializationError(
            "Evidence manifest and inbox do not match; "
            f"missing declared artifacts={missing}, unlisted supported artifacts={unlisted}. "
            "Resolve the manifest/inbox mismatch before seeding CouchDB."
        )

    documents = []
    for artifact in sorted(entries):
        path = inbox / artifact
        entry = entries[artifact]
        title, content, extracted = _read_text_artifact(path)
        grounding = entry.get("grounding")
        schema = extracted["schema_object"]
        source_grounding = schema.get("grounding") if isinstance(schema, dict) else None
        if source_grounding is not None and grounding is not None and source_grounding != grounding:
            raise InitializationError(
                f"Conflicting source and manifest grounding for {artifact}; resolve the source or manifest explicitly"
            )
        source_type = extracted.get("source_type")
        declared_type = source_type or entry.get("type")
        citations = grounding.get("citations", []) if isinstance(grounding, dict) else []
        schema_refs = grounding.get("schema_refs", []) if isinstance(grounding, dict) else []
        citation_url = (
            next(
                (
                    c.get("source_url")
                    for c in citations
                    if isinstance(c, dict) and c.get("source_url")
                ),
                None,
            )
            if isinstance(citations, list)
            else None
        )
        public_url = (
            extracted.get("source_url")
            or citation_url
            or (grounding.get("source") if isinstance(grounding, dict) else None)
        )
        document: dict[str, Any] = {
            "_id": f"artifact:{artifact}",
            "title": title,
            "content": content,
            "artifact": artifact,
            "document_type": path.suffix.casefold().lstrip("."),
            "seed_source": f"nlweb-widget-examples:{EXAMPLE_ROOT.name}",
        }
        if declared_type:
            document["type"] = declared_type
        if public_url:
            document["url"] = str(public_url)
        if isinstance(grounding, dict):
            document["grounding"] = grounding
        if isinstance(citations, list) and citations:
            document["citations"] = citations
        if isinstance(schema_refs, list) and schema_refs:
            document["schema_refs"] = schema_refs
        documents.append(document)
    return documents


def _uses_environment_proxy(url: str) -> bool:
    """Use configured proxies for remote hosts, but bypass them for loopback services."""
    hostname = (urlsplit(url).hostname or "").casefold()
    return hostname not in {"localhost", "127.0.0.1", "::1"} and not hostname.startswith("127.")


def _safe_endpoint(base_url: str, database: str) -> str:
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise InitializationError("NLWEB_COUCHDB_URL must be an absolute http:// or https:// URL")
    if parsed.username or parsed.password:
        raise InitializationError(
            "Do not embed CouchDB credentials in NLWEB_COUCHDB_URL; use the username/password environment variables"
        )
    if not database or any(ch in database for ch in "/?#"):
        raise InitializationError(
            "NLWEB_COUCHDB_DATABASE must be a single database name, such as 'nlweb_domain'"
        )
    return (
        urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))
        + "/"
        + quote(database, safe="")
    )


def initialize() -> int:
    load_dotenv(EXAMPLE_ROOT / ".env", override=False)
    base_url = os.getenv("NLWEB_COUCHDB_URL", "").strip().rstrip("/")
    if not base_url:
        raise InitializationError(
            f"CouchDB is not configured. Copy {EXAMPLE_ROOT / '.env.example'} to {EXAMPLE_ROOT / '.env'} "
            "and set NLWEB_COUCHDB_URL (and credentials if authentication is enabled)."
        )
    database = os.getenv("NLWEB_COUCHDB_DATABASE", "nlweb_domain").strip() or "nlweb_domain"
    timeout = float(os.getenv("NLWEB_DOCUMENT_STORE_TIMEOUT_SECONDS", "20"))
    username = os.getenv("NLWEB_DOCUMENT_STORE_USERNAME", "").strip()
    password = os.getenv("NLWEB_DOCUMENT_STORE_PASSWORD", "")
    auth = (username, password) if username and password else None
    if bool(username) != bool(password):
        raise InitializationError(
            "Set both NLWEB_DOCUMENT_STORE_USERNAME and NLWEB_DOCUMENT_STORE_PASSWORD, or leave both empty for an unauthenticated local instance"
        )
    endpoint = _safe_endpoint(base_url, database)
    seed_documents = build_seed_documents()
    try:
        with httpx.Client(
            timeout=timeout, auth=auth, trust_env=_uses_environment_proxy(endpoint)
        ) as client:
            response = client.put(endpoint)
            if response.status_code not in {201, 202, 412}:
                if response.status_code in {401, 403}:
                    raise InitializationError(
                        "CouchDB rejected database creation; check credentials and database-creation permissions"
                    )
                raise InitializationError(
                    f"CouchDB database setup failed with HTTP {response.status_code}: {response.text[:500]}"
                )
            created = response.status_code in {201, 202}
            existing: dict[str, dict[str, Any]] = {}
            for document in seed_documents:
                get_response = client.get(f"{endpoint}/{quote(document['_id'], safe='')}")
                if get_response.status_code == 404:
                    continue
                if get_response.status_code in {401, 403}:
                    raise InitializationError(
                        "CouchDB denied document reads; check credentials and database permissions"
                    )
                if get_response.status_code != 200:
                    raise InitializationError(
                        f"Could not inspect existing document {document['_id']!r}: HTTP {get_response.status_code}"
                    )
                prior = get_response.json()
                comparable = {k: v for k, v in prior.items() if not k.startswith("_")}
                expected = {k: v for k, v in document.items() if not k.startswith("_")}
                if comparable != expected:
                    raise InitializationError(
                        f"CouchDB document {document['_id']!r} already exists with different content or evidence attributes. "
                        "Nothing was overwritten; review/edit the document manually or use a different database."
                    )
                existing[document["_id"]] = prior
            pending = [doc for doc in seed_documents if doc["_id"] not in existing]
            if pending:
                bulk = client.post(f"{endpoint}/_bulk_docs", json={"docs": pending})
                if bulk.status_code not in {201, 202}:
                    raise InitializationError(
                        f"CouchDB bulk seed request failed with HTTP {bulk.status_code}: {bulk.text[:500]}"
                    )
                outcomes = bulk.json()
                failures = [
                    item for item in outcomes if isinstance(item, dict) and item.get("error")
                ]
                if failures:
                    brief = [
                        {
                            "id": item.get("id"),
                            "error": item.get("error"),
                            "reason": item.get("reason"),
                        }
                        for item in failures
                    ]
                    raise InitializationError(
                        f"CouchDB reported document conflicts/errors while seeding: {json.dumps(brief, ensure_ascii=False)}"
                    )
    except httpx.ConnectError as exc:
        raise InitializationError(
            f"Cannot connect to CouchDB at {base_url!r}; confirm the service is running and the URL/port are correct"
        ) from exc
    except httpx.TimeoutException as exc:
        raise InitializationError(
            f"CouchDB request timed out after {timeout:g} seconds; check service health and network reachability"
        ) from exc
    except httpx.HTTPError as exc:
        raise InitializationError(
            f"CouchDB HTTP request failed: {type(exc).__name__}: {exc}"
        ) from exc

    print(f"CouchDB database: {database} ({'created' if created else 'already existed'})")
    print(
        f"Seed artifacts: {len(seed_documents)}; already present unchanged: {len(existing)}; added: {len(pending)}"
    )
    print("No existing consumer documents were overwritten or deleted.")
    return 0


def main() -> int:
    try:
        return initialize()
    except (InitializationError, ValueError) as exc:
        print(f"CouchDB initialization failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
