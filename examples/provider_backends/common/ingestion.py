"""Dynamic file ingestion for provider-backed domain examples."""

import json
import os
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from nlweb_widget import ContentDocument
from nlweb_widget.content import ContentSourceKind

SUPPORTED_SUFFIXES = {".json", ".jsonld", ".md", ".pdf", ".pptx", ".txt", ".docx"}
EVIDENCE_MANIFEST_NAME = "nlweb-evidence-manifest.json"
_JSONLD_SCRIPT_RE = re.compile(
    r"<script\b(?=[^>]*\btype\s*=\s*(['\"]?)application/ld\+json\1)[^>]*>(.*?)</script\s*>",
    re.IGNORECASE | re.DOTALL,
)


def _uses_environment_proxy(url: str) -> bool:
    """Respect proxy settings for remote hosts, bypass them for loopback services."""
    hostname = (urlsplit(url).hostname or "").casefold()
    return hostname not in {"localhost", "127.0.0.1", "::1"} and not hostname.startswith("127.")


def _load_structured_payload(text: str, path: Path) -> dict[str, Any]:
    """Load JSON or a complete application/ld+json script wrapper.

    JSON-LD files are often exported by crawlers/CMS tools as the literal HTML
    script element rather than as a bare JSON document. Accept that single
    wrapper without treating arbitrary HTML as structured source.
    """
    candidate = text.lstrip("\ufeff").strip()
    if candidate[:7].casefold() == "<script":
        match = _JSONLD_SCRIPT_RE.fullmatch(candidate)
        if match is None:
            raise ValueError(
                f"Structured source {path} is HTML-wrapped but is not one complete "
                "application/ld+json script element"
            )
        candidate = match.group(2).strip()
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON-LD source {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Structured source must contain one JSON-LD object: {path}")
    return payload


def iter_source_files(
    directory: str | Path, *, exclude_filenames: set[str] | tuple[str, ...] = ()
) -> list[Path]:
    """Discover supported files in a directory or accept one exact supported file.

    Exclusions are filename-based and apply only to directory discovery, allowing a
    placeholder structured fixture to be omitted without suppressing adjacent source files.
    """
    excluded = {name.casefold() for name in exclude_filenames}
    # The manifest is ingestion control metadata, never an ordinary content artifact.
    excluded.add(EVIDENCE_MANIFEST_NAME.casefold())
    path = Path(directory)
    if path.is_file():
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise ValueError(f"Unsupported source file type: {path}")
        return [] if path.name.casefold() in excluded else [path]
    if not path.is_dir():
        raise FileNotFoundError(f"Content source path does not exist: {path}")
    return sorted(
        (
            item
            for item in path.iterdir()
            if item.is_file()
            and item.suffix.lower() in SUPPORTED_SUFFIXES
            and item.name.casefold() not in excluded
        ),
        key=lambda item: item.name.lower(),
    )


def schema_document(
    path: Path,
    text: str,
    site: str,
    *,
    fallback_url: str | None = None,
    manifest_entry: dict[str, Any] | None = None,
) -> ContentDocument:
    payload = _load_structured_payload(text, path)
    schema = payload.get("schema_object", payload)
    if not isinstance(schema, dict):
        raise ValueError(f"Structured source schema must be an object: {path}")
    graph_records = schema.get("@graph", [])
    primary_record = (
        next(
            (record for record in graph_records if isinstance(record, dict)),
            {},
        )
        if isinstance(graph_records, list)
        else {}
    )
    title = str(
        payload.get("name")
        or payload.get("title")
        or primary_record.get("name")
        or schema.get("name")
        or path.stem
    )
    # Source/converter URL wins over @id; configured registry URL is a base
    # mapping and receives the artifact name when it is not already a file URL.
    explicit_url = payload.get("url") or schema.get("url") or primary_record.get("url")
    identifier = payload.get("@id") or schema.get("@id") or primary_record.get("@id")
    url = str(explicit_url or identifier or _artifact_fallback_url(fallback_url, path.name) or "")

    manifest_type = manifest_entry.get("type") if manifest_entry else None
    source_type = schema.get("@type") or primary_record.get("@type")
    if not source_type and manifest_type:
        if isinstance(graph_records, list) and primary_record:
            # Add the fallback to the primary graph node only; do not falsely
            # label the graph container as a domain entity.
            primary_record["@type"] = manifest_type
        else:
            schema["@type"] = manifest_type

    manifest_grounding = manifest_entry.get("grounding") if manifest_entry else None
    source_grounding = schema.get("grounding")
    if (
        source_grounding is not None
        and manifest_grounding is not None
        and source_grounding != manifest_grounding
    ):
        raise ValueError(
            f"Conflicting source and manifest grounding for artifact {path.name}; resolve explicitly"
        )
    grounding = manifest_grounding if manifest_grounding is not None else source_grounding
    metadata: dict[str, Any] = {"source_file": path.name, "source_type": "structured"}
    if isinstance(grounding, dict):
        metadata["grounding"] = grounding
    content = str(payload.get("description") or _flatten(schema))
    return ContentDocument(
        id=f"source:{path.name}",
        url=url,
        title=title,
        content=content,
        schema_object=schema,
        site=site,
        metadata=metadata,
    )


async def ingest_couchdb_documents_async(
    location: str,
    store: Any,
    *,
    site: str,
    url: str | None = None,
    document_store_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ingest CouchDB documents directly, using document fields as retrieval metadata.

    The source documents carry their own type, grounding, citations and schema references;
    this path intentionally does not require nlweb-evidence-manifest.json.
    """
    import httpx

    parsed = urlsplit(
        location.replace("couchdb+http://", "http://", 1).replace("couchdb+https://", "https://", 1)
    )
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("CouchDB location must use couchdb+http:// or couchdb+https://")
    database = parsed.path.strip("/").split("/", 1)[0]
    base_url = (
        os.getenv("NLWEB_COUCHDB_URL", "").strip().rstrip("/") or f"{scheme}://{parsed.netloc}"
    )
    options = dict(document_store_options or {})

    def resolve(value: Any) -> Any:
        if isinstance(value, str):
            match = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", value)
            return os.getenv(match.group(1), "") if match else value
        if isinstance(value, dict):
            return {k: resolve(v) for k, v in value.items()}
        return value

    options = resolve(options)
    database = str(
        options.get("database") or os.getenv("NLWEB_COUCHDB_DATABASE", "").strip() or database
    ).strip()
    if not database or "/" in database:
        raise ValueError("CouchDB database name must be one path segment")
    username = options.get("username") or os.getenv("NLWEB_DOCUMENT_STORE_USERNAME") or None
    password = options.get("password") or os.getenv("NLWEB_DOCUMENT_STORE_PASSWORD") or None
    auth = (username, password) if username and password else None
    endpoint = f"{base_url}/{quote(database, safe='')}/_all_docs?include_docs=true"
    timeout = float(os.getenv("NLWEB_DOCUMENT_STORE_TIMEOUT_SECONDS", "20"))
    async with httpx.AsyncClient(
        timeout=timeout, auth=auth, trust_env=_uses_environment_proxy(base_url)
    ) as client:
        rows: list[dict[str, Any]] = []
        page_limit = 500
        next_url = f"{endpoint}&limit={page_limit}"
        while next_url:
            response = await client.get(next_url)
            response.raise_for_status()
            payload = response.json()
            page = payload.get("rows") if isinstance(payload, dict) else None
            if not isinstance(page, list):
                raise ValueError("CouchDB _all_docs response must contain a rows list")
            rows.extend(page)
            if len(page) < page_limit or not page:
                next_url = ""
            else:
                last_id = str(page[-1].get("id", "")) if isinstance(page[-1], dict) else ""
                if not last_id:
                    raise ValueError("CouchDB _all_docs pagination row is missing its document ID")
                next_url = f"{endpoint}&limit={page_limit}&startkey={quote(json.dumps(last_id), safe='')}&skip=1"
    indexed = 0
    item_keys: list[str] = []
    for row in rows:
        raw = row.get("doc") if isinstance(row, dict) else None
        if not isinstance(raw, dict) or raw.get("_deleted"):
            continue
        doc_id = str(raw.get("_id") or row.get("id") or "").strip()
        if not doc_id or doc_id.startswith("_design/") or doc_id.startswith("_local/"):
            continue
        title = str(raw.get("title") or raw.get("name") or doc_id)
        content_value = raw.get("content", raw.get("text", raw.get("description", "")))
        content = content_value if isinstance(content_value, str) else _flatten(content_value)
        if not content.strip():
            continue
        source_url = str(raw.get("url") or raw.get("source_url") or url or "")
        declared_type = raw.get("type") or raw.get("@type")
        grounding = raw.get("grounding")
        citations = raw.get("citations")
        schema_refs = raw.get("schema_refs")
        metadata = {
            "source_type": "document_store",
            "source_document_id": doc_id,
            "source_revision": raw.get("_rev"),
        }
        if isinstance(grounding, dict):
            metadata["grounding"] = grounding
        if isinstance(citations, list):
            metadata["citations"] = citations
        if isinstance(schema_refs, list):
            metadata["schema_refs"] = schema_refs
        if isinstance(raw.get("metadata"), dict):
            metadata.update(raw["metadata"])
        schema_object = {"name": title, "description": content}
        if declared_type:
            schema_object["@type"] = declared_type
        if source_url:
            schema_object["url"] = source_url
        # Keep source-specific attributes in the schema object for downstream consumers.
        for key in ("grounding", "citations", "schema_refs", "artifact", "document_type"):
            if key in raw:
                schema_object[key] = raw[key]
        document = ContentDocument(
            id=f"couchdb:{database}:{doc_id}",
            url=source_url,
            title=title,
            content=content,
            schema_object=schema_object,
            site=site,
            metadata=metadata,
        )
        await store.upsert(document)
        item_keys.append(document.id)
        indexed += 1
    return {
        "status": "ok",
        "processed": len(rows),
        "indexed": indexed,
        "item_keys": item_keys,
        "source": "couchdb",
        "database": database,
    }


def _artifact_fallback_url(base_url: str | None, artifact_name: str) -> str | None:
    """Map an artifact to a declared public base without inventing a host."""
    if not base_url or not base_url.strip():
        return None
    base_url = base_url.strip()
    parts = urlsplit(base_url)
    if not parts.scheme or not parts.netloc:
        return base_url.rstrip("/") + "/" + quote(artifact_name)
    final_segment = parts.path.rsplit("/", 1)[-1]
    if final_segment and "." in final_segment:
        return base_url
    path = parts.path.rstrip("/") + "/" + quote(artifact_name)
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def _load_evidence_manifest(directory: Path) -> dict[str, dict[str, Any]]:
    manifest_path = directory / EVIDENCE_MANIFEST_NAME
    if not manifest_path.exists():
        return {}
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid evidence manifest {manifest_path}: {exc}") from exc
    if not isinstance(payload, dict) or str(payload.get("version")) != "1":
        raise ValueError("Evidence manifest must be an object with version '1'")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("Evidence manifest 'artifacts' must be a list")
    entries: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(artifacts):
        if not isinstance(entry, dict):
            raise ValueError(f"Evidence manifest artifacts[{index}] must be an object")
        artifact = entry.get("artifact")
        if not isinstance(artifact, str) or not artifact.strip():
            raise ValueError(f"Evidence manifest artifacts[{index}] requires 'artifact'")
        normalized = PurePosixPath(artifact.replace("\\", "/"))
        if (
            normalized.is_absolute()
            or ".." in normalized.parts
            or normalized.as_posix() in {".", ""}
        ):
            raise ValueError(
                f"Evidence manifest artifact key must be a safe relative path: {artifact!r}"
            )
        key = normalized.as_posix()
        if key in entries:
            raise ValueError(f"Duplicate evidence manifest artifact key: {key}")
        declared_type = entry.get("type")
        if declared_type is not None and (
            not isinstance(declared_type, str) or not declared_type.strip()
        ):
            raise ValueError(f"Evidence manifest type for {key} must be a non-empty string")
        grounding = entry.get("grounding")
        if grounding is not None and not isinstance(grounding, dict):
            raise ValueError(f"Evidence manifest grounding for {key} must be an object")
        entries[key] = {**entry, "artifact": key}
    return entries


def _flatten(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(
            f"{key}: {_flatten(item)}" for key, item in value.items() if key != "@context"
        )
    if isinstance(value, list):
        return " ".join(_flatten(item) for item in value)
    return str(value)


async def ingest_directory_async(
    directory: str | Path,
    store: Any,
    *,
    site: str,
    url: str | None = None,
    embedding_provider: Any,
    exclude_filenames: set[str] | tuple[str, ...] = (),
    remote_storage_options: dict[str, Any] | None = None,
    document_store_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ingest a declared file, directory, or configured remote/document source.

    ``url`` is the source-registry metadata URL fallback. A URL or @id explicitly
    present in a JSON-LD document, or a URL returned by the converter, takes precedence.
    Structured JSON-LD is kept on the authoritative schema path. Other declared
    file types are normalized by Haystack into its common Document representation,
    then projected into the Widget's ContentDocument boundary and chunked before
    indexing. This avoids the ML-heavy Docling PDF layout pipeline in examples.
    """
    # A local path (including a mounted volume) is the zero-extra default. Object-storage
    # prefixes are materialized with optional fsspec so the same discovery/manifest rules
    # apply to S3/GCS/Azure-compatible filesystems. Credentials remain the consumer's concern.
    location = str(directory)

    def resolve_location(match: re.Match[str]) -> str:
        variable = match.group(1)
        value = os.getenv(variable, "").strip()
        if not value:
            raise ValueError(
                f"Remote source location requires environment variable {variable}; configure it or disable the source"
            )
        return value

    location = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", resolve_location, location)
    if re.search(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}", location):
        raise ValueError("Remote source location contains unresolved environment placeholders")
    # NLWEB_COUCHDB_URL is the consumer-owned endpoint. Normalize a trailing slash
    # so a base URL such as http://localhost:5984/ cannot produce a double slash.
    location = re.sub(r"^(couchdb\+https?://[^/]+)/+", r"\1/", location, flags=re.IGNORECASE)
    parts = urlsplit(location)
    if parts.scheme.lower() in {"couchdb+http", "couchdb+https"}:
        return await ingest_couchdb_documents_async(
            location, store, site=site, url=url, document_store_options=document_store_options
        )
    if parts.scheme.lower() in {"s3", "gs", "gcs", "az", "abfs", "https", "http", "memory"}:
        try:
            import fsspec
        except ImportError as exc:
            raise RuntimeError(
                f"Remote content location {location!r} requires the optional fsspec dependency; "
                "install the examples remote-storage extra and configure the provider credentials."
            ) from exc
        options: dict[str, Any] = dict(remote_storage_options or {})

        # Connection options come from this source's registry entry; secrets remain
        # environment-backed and are never logged or persisted.
        def resolve_option(value: Any) -> Any:
            if isinstance(value, str):
                match = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", value)
                if match:
                    return os.getenv(match.group(1), "")
                return value
            if isinstance(value, dict):
                return {key: resolve_option(child) for key, child in value.items()}
            if isinstance(value, list):
                return [resolve_option(child) for child in value]
            return value

        options = resolve_option(options)

        # Empty optional placeholders are omitted so the filesystem backend can use
        # its native credential chain instead of receiving empty secret values.
        def prune_empty(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    key: prune_empty(child)
                    for key, child in value.items()
                    if child not in (None, "")
                }
            if isinstance(value, list):
                return [prune_empty(child) for child in value if child not in (None, "")]
            return value

        options = prune_empty(options)
        # `prefix` is an example-level bucket subdirectory, not an fsspec client
        # option. Pop it before constructing the filesystem, then scope listing to it.
        prefix = str(options.pop("prefix", "") or "").strip("/")
        client_kwargs = options.get("client_kwargs")
        if isinstance(client_kwargs, dict):
            endpoint = client_kwargs.get("endpoint_url")
            if isinstance(endpoint, str) and endpoint and "://" not in endpoint:
                client_kwargs["endpoint_url"] = "https://" + endpoint
        endpoint = options.get("endpoint_url")
        if isinstance(endpoint, str) and endpoint and "://" not in endpoint:
            options["endpoint_url"] = "https://" + endpoint
        filesystem, remote_path = fsspec.core.url_to_fs(location, **options)
        remote_path = remote_path.rstrip("/")
        if prefix:
            remote_path = f"{remote_path}/{prefix}" if remote_path else prefix
        with tempfile.TemporaryDirectory(prefix="nlweb-inbox-") as temp_root:
            root = Path(temp_root)
            try:
                if filesystem.isfile(remote_path):
                    names = [remote_path]
                    relative_root = remote_path.rsplit("/", 1)[0] if "/" in remote_path else ""
                else:
                    names = sorted(filesystem.find(remote_path))
                    relative_root = remote_path
            except (FileNotFoundError, OSError) as exc:
                raise FileNotFoundError(
                    f"Remote content source does not exist: {location}"
                ) from exc
            copied = 0
            for remote_name in names:
                if filesystem.isdir(remote_name):
                    continue
                relative = (
                    remote_name[len(relative_root) :].lstrip("/")
                    if relative_root
                    else remote_name.rsplit("/", 1)[-1]
                )
                if not relative:
                    relative = remote_name.rsplit("/", 1)[-1]
                target = (root / PurePosixPath(relative)).resolve()
                if root.resolve() not in target.parents and target != root.resolve():
                    raise ValueError(f"Remote artifact has an unsafe relative path: {relative!r}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with filesystem.open(remote_name, "rb") as source, target.open("wb") as destination:
                    destination.write(source.read())
                copied += 1
            # An existing/accessible object-store prefix with no supported objects is a
            # valid empty snapshot. Returning an empty successful result lets the source
            # loader remove stale IDs for this source; lookup/auth failures still raise above.
            if copied == 0:
                return {
                    "processed": 0,
                    "indexed": 0,
                    "total_loaded": 0,
                    "item_keys": [],
                    "message": "Remote source enumerated successfully and contains no files.",
                }
            return await ingest_directory_async(
                root,
                store,
                site=site,
                url=url,
                embedding_provider=embedding_provider,
                exclude_filenames=exclude_filenames,
                remote_storage_options=remote_storage_options,
            )
    # Structured JSON-LD ingestion is dependency-light; only unstructured documents
    # require Haystack. Delay those imports so exact-file JSON-LD sources remain usable
    # even when the optional document-normalization dependency is absent.
    fallback_url = url.strip() if url and url.strip() else None
    source_path = Path(unquote(parts.path)) if parts.scheme.lower() == "file" else Path(directory)
    source_root = source_path if source_path.is_dir() else source_path.parent
    incidents: list[dict[str, str]] = []
    manifest_present = source_path.is_dir() and (source_root / EVIDENCE_MANIFEST_NAME).is_file()
    try:
        manifest_entries = _load_evidence_manifest(source_root) if source_path.is_dir() else {}
    except (OSError, ValueError) as exc:
        # A damaged manifest must not prevent healthy, independently parseable artifacts
        # from being ingested. Continue without manifest-derived evidence and report it.
        manifest_entries = {}
        incidents.append(
            {
                "artifact": EVIDENCE_MANIFEST_NAME,
                "code": "invalid_evidence_manifest",
                "message": str(exc),
            }
        )
        manifest_present = False
    discovered = iter_source_files(directory, exclude_filenames=exclude_filenames)
    discovered_keys = {item.relative_to(source_root).as_posix() for item in discovered}
    intentionally_excluded = {
        PurePosixPath(str(name).replace("\\", "/")).name for name in exclude_filenames
    }
    if manifest_present and manifest_entries:
        # A manifest-backed directory is an explicit inventory. Process only matching
        # supported artifacts; keep all other files out of this sync and report the mismatch.
        for key in sorted(set(manifest_entries) - discovered_keys):
            if PurePosixPath(key).name in intentionally_excluded:
                continue
            candidate = source_root.joinpath(*PurePosixPath(key).parts)
            if candidate.is_file() and candidate.suffix.lower() not in SUPPORTED_SUFFIXES:
                code = "unsupported_artifact_format"
                message = f"Manifest declares {key}, but its format {candidate.suffix or '(no extension)'} is not supported; skipped."
            else:
                code = "manifest_artifact_missing"
                message = f"Manifest declares {key}, but no supported artifact was discovered at that path; skipped."
            incidents.append({"artifact": key, "code": code, "message": message})
        for key in sorted(discovered_keys - set(manifest_entries)):
            incidents.append(
                {
                    "artifact": key,
                    "code": "artifact_not_in_manifest",
                    "message": f"Artifact {key} is not declared by the evidence manifest; skipped.",
                }
            )
        discovered = [
            item
            for item in discovered
            if item.relative_to(source_root).as_posix() in manifest_entries
        ]
    elif manifest_present and not manifest_entries:
        # An empty but valid manifest explicitly declares no content; don't ingest files
        # silently as though they were inventoried.
        discovered = []
        for item in iter_source_files(directory, exclude_filenames=exclude_filenames):
            incidents.append(
                {
                    "artifact": item.relative_to(source_root).as_posix(),
                    "code": "artifact_not_in_manifest",
                    "message": "Artifact is not declared by the empty evidence manifest; skipped.",
                }
            )
    if source_path.is_dir():
        excluded_names = {
            EVIDENCE_MANIFEST_NAME.casefold(),
            *(str(name).casefold() for name in exclude_filenames),
        }
        already_reported_unsupported = {
            item["artifact"] for item in incidents if item["code"] == "unsupported_artifact_format"
        }
        # Report unsupported files even if they were not declared by the manifest.
        # They are never passed to a converter or silently treated as missing content.
        for item in source_root.iterdir():
            if not item.is_file() or item.name.casefold() in excluded_names:
                continue
            if (
                item.suffix.lower() not in SUPPORTED_SUFFIXES
                and item.name not in already_reported_unsupported
            ):
                incidents.append(
                    {
                        "artifact": item.name,
                        "code": "unsupported_artifact_format",
                        "message": f"Skipped {item.name}: unsupported artifact format {item.suffix or '(no extension)'}.",
                    }
                )
    converter = None
    splitter = None
    document_type = None
    processed = indexed = 0
    item_keys: list[str] = []
    for path in discovered:
        artifact_key = path.relative_to(source_root).as_posix()
        try:
            artifact_key = path.relative_to(source_root).as_posix()
            manifest_entry = manifest_entries.get(artifact_key)
            if path.suffix.lower() in {".json", ".jsonld"}:
                text = path.read_text(encoding="utf-8")
                payload = _load_structured_payload(text, path)
                if "@context" in payload:
                    graph = payload.get("@graph")
                    records = (
                        [item for item in graph if isinstance(item, dict)]
                        if isinstance(graph, list)
                        else []
                    )
                    if records:
                        # Index each graph entity as its own retrieval result instead of making
                        # secondary authoritative records unreachable behind one selected node.
                        for index, record in enumerate(records):
                            record_payload = {"@context": payload.get("@context"), **record}
                            document = schema_document(
                                path,
                                json.dumps(record_payload, ensure_ascii=False),
                                site,
                                fallback_url=fallback_url,
                                manifest_entry=manifest_entry,
                            )
                            document = document.model_copy(
                                update={"id": f"source:{path.name}:record:{index}"}
                            )
                            await store.upsert(document)
                            item_keys.append(document.id)
                            indexed += 1
                        processed += 1
                    else:
                        document = schema_document(
                            path,
                            text,
                            site,
                            fallback_url=fallback_url,
                            manifest_entry=manifest_entry,
                        )
                        await store.upsert(document)
                        item_keys.append(document.id)
                        processed += 1
                        indexed += 1
                    continue

            if converter is None:
                from haystack import Document
                from haystack.components.converters import MultiFileConverter
                from haystack.components.preprocessors import DocumentSplitter

                document_type = Document
                converter = MultiFileConverter()
                splitter = DocumentSplitter(
                    split_by="word",
                    split_length=int(__import__("os").getenv("NLWEB_DOCUMENT_SPLIT_LENGTH", "220")),
                    split_overlap=int(
                        __import__("os").getenv("NLWEB_DOCUMENT_SPLIT_OVERLAP", "30")
                    ),
                )
            source_kind = ContentSourceKind.CUSTOM
            if path.suffix.casefold() == ".docx":
                # MultiFileConverter support can vary with optional Haystack integrations.
                # Use python-docx directly so DOCX is a first-class supported artifact.
                from docx import Document as DocxDocument

                docx = DocxDocument(str(path))
                paragraphs = [
                    paragraph.text.strip()
                    for paragraph in docx.paragraphs
                    if paragraph.text.strip()
                ]
                table_rows = [
                    " | ".join(cell.text.strip() for cell in row.cells)
                    for table in docx.tables
                    for row in table.rows
                ]
                text_content = "\n".join([*paragraphs, *[row for row in table_rows if row.strip()]])
                if not text_content.strip():
                    raise ValueError("DOCX contains no extractable paragraph or table text")
                documents = [document_type(content=text_content, meta={"title": path.stem})]
            else:
                conversion = converter.run(sources=[str(path)], meta={})
                failed = conversion.get("failed") or []
                unclassified = conversion.get("unclassified") or []
                if failed or unclassified:
                    raise RuntimeError(
                        f"Haystack MultiFileConverter could not normalize {path.name}: "
                        f"failed={failed!r}, unclassified={unclassified!r}"
                    )
                documents = conversion.get("documents") or []
                if not documents:
                    raise RuntimeError(
                        f"Haystack MultiFileConverter returned no document for {path.name}"
                    )

            for converted in documents:
                if not isinstance(converted, document_type):
                    raise TypeError(
                        f"Unexpected Haystack converter output for {path.name}: {type(converted)!r}"
                    )
                content = _clean_converted_content(path, converted)
                title = str(converted.meta.get("title") or path.stem)
                document_url = str(
                    converted.meta.get("url")
                    or _artifact_fallback_url(fallback_url, path.name)
                    or ""
                )
                document = ContentDocument(
                    id=f"source:{path.name}",
                    url=document_url,
                    title=title,
                    content=content,
                    site=site,
                    schema_object=(
                        {"@type": manifest_entry["type"]}
                        if manifest_entry and manifest_entry.get("type")
                        else {}
                    ),
                    metadata={
                        "source_file": path.name,
                        "source_type": "haystack-multifile",
                        "source_kind": source_kind.value,
                        "converter": "MultiFileConverter",
                        **(
                            {"grounding": manifest_entry["grounding"]}
                            if manifest_entry and isinstance(manifest_entry.get("grounding"), dict)
                            else {}
                        ),
                    },
                )
                split_result = splitter.run(documents=[document_to_haystack(document)])
                chunks = split_result["documents"]
                for index, chunk in enumerate(chunks):
                    item = document.model_copy(
                        update={
                            "id": f"source:{path.name}:chunk:{index}",
                            "url": document.url,
                            "title": f"{document.title} — chunk {index + 1}",
                            "content": chunk.content or "",
                            "metadata": {**document.metadata, "chunk": index},
                        }
                    )
                    await store.upsert(item)
                    item_keys.append(item.id)
                    indexed += 1
            processed += 1
        except Exception as exc:
            incidents.append(
                {
                    "artifact": artifact_key,
                    "code": "artifact_processing_failed",
                    "message": f"Skipped {artifact_key}: {type(exc).__name__}: {exc}",
                }
            )
            continue
    incident_summary = "; ".join(item["message"] for item in incidents)
    return {
        "processed": processed,
        "indexed": indexed,
        "total_loaded": indexed,
        "item_keys": item_keys,
        "incidents": incidents,
        "partial": bool(incidents),
        "message": (
            "Processed healthy artifacts; structured sources use the schema path and unstructured files use the document normalization path."
            + (
                f" Skipped/reported {len(incidents)} incident(s): {incident_summary}"
                if incidents
                else ""
            )
        ),
    }


def _clean_converted_content(path: Path, converted: Any) -> str:
    """Clean non-Markdown converted text; preserve Markdown bytes/spacing exactly."""
    content = converted.content or ""
    if path.suffix.casefold() == ".md":
        return content
    from haystack.components.preprocessors import DocumentCleaner

    cleaner = DocumentCleaner(
        remove_empty_lines=True,
        remove_extra_whitespaces=True,
        remove_repeated_substrings=False,
    )
    cleaned = cleaner.run(documents=[converted])["documents"]
    return (cleaned[0].content or "") if cleaned else content


def document_to_haystack(document: ContentDocument) -> Any:
    """Convert a Widget document into Haystack's splitter input shape."""
    from haystack import Document

    return Document(
        content=document.content, meta={"source_file": document.metadata.get("source_file")}
    )
