"""Runtime source-registry validation for the hosted-domain example."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse, urlsplit

PLACEHOLDER_HOST = "external-source.example"


def site_identifier(site_url: str) -> str:
    """Return the hostname of a canonical domain URL (not a retrieval corpus ID)."""
    candidate = site_url.strip()
    if not candidate:
        raise ValueError("NLWEB_EXTERNAL_SOURCE_SITE must not be empty")
    parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname:
        raise ValueError("NLWEB_EXTERNAL_SOURCE_SITE must be a URL or hostname with a valid host")
    return hostname


def uses_example_owned_registry(
    example_dir: str | Path, configured_path: str | None = None
) -> bool:
    """Whether the configured registry is the example's own registry.

    Explicitly supplied consumer registries remain consumer-owned. Relative paths are
    interpreted the same way as the example's Widget builder: from the example directory.
    """
    root = Path(example_dir).resolve()
    raw = (
        configured_path
        if configured_path is not None
        else os.getenv("NLWEB_CONTENT_SOURCES_FILE", "")
    ).strip()
    if not raw:
        return True
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = (root / candidate).resolve()
    return candidate.resolve() == (root / "nlweb-sources.json").resolve()


def backend_corpus_id(base_site: str, backend: str) -> str:
    """Give parallel backend outputs distinct retrieval filters without merging them."""
    if backend == "custom":
        return base_site
    return f"{base_site}--{backend}"


def _load_toml(path: Path) -> dict:
    import tomllib

    return tomllib.loads(path.read_text(encoding="utf-8"))


def validate_scenario_registry(example_dir: str | Path) -> dict[str, dict[str, str]]:
    """Validate the one-to-one scenario → registry name → artifact contract."""
    root = Path(example_dir).resolve()
    sources_config = _load_toml(root / "sources.toml").get("sources", {})
    prompts = _load_toml(root / "prompts" / "extraction_scenarios.toml").get("scenarios", {})
    payload = json.loads((root / "nlweb-sources.json").read_text(encoding="utf-8"))
    entries = payload.get("sources") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        raise ValueError("nlweb-sources.json must contain a sources list")
    by_name = {str(item.get("name")): item for item in entries if isinstance(item, dict)}
    if len(by_name) != len(entries):
        raise ValueError("nlweb-sources.json contains duplicate or invalid source names")
    for item in entries:
        name = str(item.get("name", ""))
        site = str(item.get("site", "")).strip()
        if not site or site == "default":
            raise ValueError(f"Source {name!r} must declare an explicit non-default corpus site ID")
    if set(sources_config) != set(prompts):
        raise ValueError(
            "sources.toml and extraction_scenarios.toml must define the same scenario names; "
            f"sources-only={sorted(set(sources_config) - set(prompts))}, "
            f"prompts-only={sorted(set(prompts) - set(sources_config))}"
        )
    mapping: dict[str, dict[str, str]] = {}
    artifacts: set[str] = set()
    for scenario, config in sources_config.items():
        entry = by_name.get(scenario)
        if entry is None:
            raise ValueError(
                f"Scenario {scenario!r} has no nlweb-sources.json entry named {scenario!r}"
            )
        if entry.get("kind") != "custom":
            raise ValueError(
                f"Scenario source {scenario!r} must use kind='custom' for the provider loader"
            )
        site = str(config.get("site", "")).strip()
        artifact = str(config.get("artifact", "")).strip().replace("\\", "/")
        if not site:
            raise ValueError(f"Scenario {scenario!r} must declare a non-empty corpus site ID")
        artifact_path = Path(artifact)
        if (
            artifact_path.is_absolute()
            or ".." in artifact_path.parts
            or not artifact.startswith("generated/")
        ):
            raise ValueError(f"Scenario {scenario!r} artifact must be a safe path under generated/")
        if artifact in artifacts:
            raise ValueError(f"Multiple scenarios map to the same generated artifact: {artifact}")
        artifacts.add(artifact)
        if entry.get("site") != site:
            raise ValueError(f"Scenario {scenario!r} site does not match its registry entry")
        if entry.get("location", "").replace("\\", "/") != artifact:
            raise ValueError(f"Scenario {scenario!r} artifact does not match its registry location")
        metadata = entry.get("metadata", {})
        if not isinstance(metadata, dict) or metadata.get("scenario") != scenario:
            raise ValueError(
                f"Scenario {scenario!r} registry metadata must identify the same scenario"
            )
        mapping[scenario] = {"site": site, "artifact": artifact}
    # No extra generated-directory entry may bypass the exact-file scenario mapping.
    for item in entries:
        location = str(item.get("location", "")).replace("\\", "/")
        if location == "generated" or location.startswith("generated/"):
            name = str(item.get("name", ""))
            if name not in mapping or location != mapping[name]["artifact"]:
                raise ValueError(
                    f"Generated source {name!r} must map to exactly one declared scenario artifact"
                )
    return mapping


def _prompt_fingerprint(example_dir: Path, scenario: str) -> str:
    prompts = _load_toml(example_dir / "prompts" / "extraction_scenarios.toml").get("scenarios", {})
    if scenario not in prompts:
        raise ValueError(f"Missing prompt definition for scenario {scenario!r}")
    prompt_payload = {
        "prompt": prompts[scenario].get("prompt", ""),
        "schema_hint": prompts[scenario].get("schema_hint", {}),
    }
    normalized = json.dumps(
        prompt_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _configured_urls(config: dict) -> list[str]:
    env_name = config.get("url_env")
    configured = os.getenv(str(env_name), "").strip() if env_name else ""
    urls = [configured] if configured else list(config.get("urls", []))
    return [str(url).strip() for url in urls if str(url).strip()]


def _artifact_status(
    root: Path, scenario: str, config: dict, mapping: dict[str, str], canonical_url: str
) -> tuple[bool, str | None]:
    artifact = (root / mapping["artifact"]).resolve()
    generated_root = (root / "generated").resolve()
    if artifact.parent != generated_root:
        return False, "artifact path is outside generated/"
    if not artifact.is_file():
        return False, "artifact is missing"
    manifest_path = artifact.with_name(artifact.name + ".manifest.json")
    if not manifest_path.is_file():
        return False, "artifact provenance manifest is missing; rerun the scenario extraction"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, "artifact provenance manifest is unreadable"
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    if manifest.get("scenario") != scenario:
        return False, "artifact provenance scenario does not match registry entry"
    scenario_site = mapping.get("scenario_site", mapping["site"])
    if manifest.get("site") != scenario_site:
        return False, "artifact provenance scenario corpus ID does not match registry entry"
    manifest_retrieval_site = manifest.get("retrieval_site", manifest.get("site"))
    if manifest_retrieval_site != mapping["site"]:
        return False, "artifact provenance retrieval corpus ID does not match registry entry"
    if manifest.get("artifact_sha256") != digest:
        return False, "artifact changed after extraction; rerun the scenario extraction"
    if manifest.get("prompt_sha256") != _prompt_fingerprint(root, scenario):
        return False, "extraction prompt/schema changed; rerun the scenario extraction"
    active_urls = _configured_urls(config)
    if not active_urls or manifest.get("sources") != active_urls:
        return False, "configured source URLs changed or are unset; rerun the scenario extraction"
    if manifest.get("canonical_site_url") != canonical_url:
        return False, "canonical site URL changed; rerun the scenario extraction"
    return True, None


def prepare_runtime_source_registry(example_dir: str | Path, site_url: str) -> Path:
    """Write a runtime registry with absolute paths and explicit corpus IDs.

    The authoritative source deliberately points to the inbox directory so every supported
    structured or unstructured file can be discovered. For a real canonical domain, only the
    untouched placeholder JSON-LD fixture is excluded; the directory source and its other files
    remain enabled. This never overwrites source `site` IDs. Generated scenario entries are
    enabled only when their exact artifact exists, so they cannot scan across corpora.
    """
    root = Path(example_dir).resolve()
    registry_path = root / "nlweb-sources.json"
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    scenario_map = validate_scenario_registry(root)
    sources_config = _load_toml(root / "sources.toml").get("sources", {})
    canonical_url = site_url.strip()
    canonical_host = site_identifier(canonical_url)
    is_real_domain = canonical_host != PLACEHOLDER_HOST

    for source in payload["sources"]:
        if source.get("remote_storage_options"):
            metadata = source.setdefault("metadata", {})
            if isinstance(metadata, dict):
                metadata["remote_storage_options"] = source["remote_storage_options"]
        raw_location = str(source["location"])
        location_parts = urlsplit(raw_location)
        is_remote_location = location_parts.scheme.lower() in {
            "s3",
            "gs",
            "gcs",
            "az",
            "abfs",
            "https",
            "http",
            "memory",
            "couchdb+http",
            "couchdb+https",
        }
        if is_remote_location:
            # Keep object-store URIs intact; the registered loader resolves them through
            # the configured optional filesystem adapter (e.g. fsspec).
            location = None
            source["location"] = raw_location
        else:
            location = (
                Path(location_parts.path) if location_parts.scheme == "file" else Path(raw_location)
            )
            if not location.is_absolute():
                location = (root / location).resolve()
            source["location"] = str(location)

        if source.get("name") == "authoritative_domain" and is_real_domain and location is not None:
            # Keep the directory source enabled so consumer-provided unstructured files are
            # still ingested. Exclude only the untouched placeholder JSON-LD fixture.
            fixture = location / "domain.jsonld" if location.is_dir() else location
            if fixture.is_file():
                try:
                    fixture_data = json.loads(fixture.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    fixture_data = {}
                fixture_url = str(fixture_data.get("url", ""))
                fixture_id = str(fixture_data.get("@id", ""))
                if PLACEHOLDER_HOST in fixture_url or PLACEHOLDER_HOST in fixture_id:
                    metadata = source.setdefault("metadata", {})
                    excluded = set(metadata.get("excluded_filenames", []))
                    excluded.add(fixture.name)
                    metadata["excluded_filenames"] = sorted(excluded)
                else:
                    source.setdefault("metadata", {}).pop("excluded_filenames", None)

        scenario = source.get("name")
        if scenario in scenario_map:
            expected = scenario_map[scenario]
            artifact = Path(expected["artifact"])
            artifact_path = (root / artifact).resolve()
            if artifact_path.parent != (root / "generated").resolve():
                raise ValueError(f"Generated artifact path escapes generated/: {artifact}")
            source["location"] = str(artifact_path)
            source["site"] = expected["site"]
            is_fresh, reason = _artifact_status(
                root, scenario, sources_config[scenario], expected, canonical_url
            )
            source["enabled"] = is_fresh
            source.setdefault("metadata", {})["runtime_artifact_status"] = (
                "fresh" if is_fresh else "disabled"
            )
            if reason:
                source["metadata"]["runtime_disabled_reason"] = reason
            else:
                source["metadata"].pop("runtime_disabled_reason", None)

    # If backend-specific artifacts exist, register each as its own source. Never combine
    # their graphs: source identity and provenance remain independent through ingestion.
    existing_names = {str(item.get("name", "")) for item in payload["sources"]}
    backend_suffixes = ("custom", "scrapegraphai", "scrapy_ollama", "scrapy_transformers")
    for scenario_name, expected in scenario_map.items():
        base_entry = next(item for item in payload["sources"] if item.get("name") == scenario_name)
        base_artifact = (root / expected["artifact"]).resolve()
        stem = base_artifact.stem
        backend_artifacts = [
            (backend, root / "generated" / f"{stem}.{backend}.jsonld")
            for backend in backend_suffixes
        ]
        found_backend_artifact = any(path.is_file() for _, path in backend_artifacts)
        if found_backend_artifact:
            # A prior single-path artifact must not be ingested alongside the newer,
            # independently registered backend outputs.
            base_entry["enabled"] = False
            base_entry.setdefault("metadata", {})["runtime_artifact_status"] = (
                "superseded-by-independent-backend-artifacts"
            )
        for backend, artifact_file in backend_artifacts:
            if not artifact_file.is_file():
                continue
            artifact_name = f"{scenario_name}__{backend}"
            if artifact_name in existing_names:
                raise ValueError(f"Duplicate runtime extraction source name: {artifact_name}")
            retrieval_site = backend_corpus_id(expected["site"], backend)
            mapping = {
                "artifact": artifact_file.relative_to(root).as_posix(),
                "site": retrieval_site,
                "scenario_site": expected["site"],
            }
            is_fresh, reason = _artifact_status(
                root, scenario_name, sources_config[scenario_name], mapping, canonical_url
            )
            entry = json.loads(json.dumps(base_entry))
            entry["name"] = artifact_name
            entry["location"] = str(artifact_file.resolve())
            entry["site"] = retrieval_site
            entry["enabled"] = is_fresh
            metadata = entry.setdefault("metadata", {})
            metadata.update(
                {
                    "scenario": scenario_name,
                    "backend": backend,
                    "scenario_site": expected["site"],
                    "artifact": mapping["artifact"],
                    "purpose": "independent-backend-extraction-jsonld-projection",
                    "runtime_artifact_status": "fresh" if is_fresh else "disabled",
                }
            )
            if reason:
                metadata["runtime_disabled_reason"] = reason
            else:
                metadata.pop("runtime_disabled_reason", None)
            payload["sources"].append(entry)
            existing_names.add(artifact_name)

    # Absolute paths are deliberate here: the runtime registry lives below runtime/config,
    # so relative paths would resolve against that directory rather than this example root.
    # The checked-in nlweb-sources.json remains portable and uses example-relative paths.
    runtime_path = root / "runtime" / "config" / "nlweb-sources.json"
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return runtime_path


def runtime_scenario_status(registry_path: str | Path) -> list[dict[str, str | bool]]:
    """Return concise generated-artifact status for the example's health endpoint."""
    payload = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    statuses: list[dict[str, str | bool]] = []
    for source in payload.get("sources", []):
        metadata = source.get("metadata", {})
        if metadata.get("scenario"):
            statuses.append(
                {
                    "scenario": str(metadata["scenario"]),
                    "site": str(source.get("site", "")),
                    "enabled": bool(source.get("enabled", False)),
                    "artifact": str(source.get("location", "")),
                    "status": str(metadata.get("runtime_artifact_status", "disabled")),
                    "reason": str(metadata.get("runtime_disabled_reason", "")),
                }
            )
    return statuses
