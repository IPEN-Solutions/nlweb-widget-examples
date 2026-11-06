"""Explicit hosted-source extraction and additive JSON-LD artifact generation.

This command deliberately does not construct or start a Widget. The generated artifact is
registered as a normal custom source in ``nlweb-sources.json`` and is projected by the
Widget's standard startup synchronization when the FastAPI app is started afterward.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .adapter import (
    ExtractionRequest,
    ScrapeGraphAIExtractor,
    configured_extractor_from_environment,
)
from .jsonld import extraction_to_jsonld
from .registry import backend_corpus_id, validate_scenario_registry
from .storage import ExtractionStore

ROOT = Path(__file__).resolve().parent
# The standalone CLI and the FastAPI app must resolve scenario URLs from the same
# example-owned .env file, independent of the shell's current working directory.
_ENV_FILE = ROOT / ".env"


def _load_example_env() -> None:
    if _ENV_FILE.is_file():
        from dotenv import load_dotenv

        load_dotenv(_ENV_FILE, override=True)


_load_example_env()

PROMPTS = ROOT / "prompts" / "extraction_scenarios.toml"
SOURCES = ROOT / "sources.toml"
EXTRACTION_DB = ROOT / "runtime" / "extracted-content.sqlite3"


def _load_toml(path: Path) -> dict[str, Any]:
    import tomllib

    return tomllib.loads(path.read_text(encoding="utf-8"))


def _artifact_path(environment_name: str, default: Path) -> Path:
    """Resolve relative artifact paths against this example, not the caller's CWD."""
    configured = os.getenv(environment_name)
    path = Path(configured) if configured else default
    return path if path.is_absolute() else (ROOT / path).resolve()


def _scenario(name: str) -> dict[str, Any]:
    prompts = _load_toml(PROMPTS)["scenarios"]
    sources = _load_toml(SOURCES)["sources"]
    mapping = validate_scenario_registry(ROOT)
    if name not in prompts or name not in sources or name not in mapping:
        raise KeyError(f"Unknown or unmapped extraction scenario: {name}")
    scenario = {**prompts[name], **sources[name], **mapping[name]}
    url_env = scenario.get("url_env")
    configured_url = os.getenv(url_env, "") if url_env else ""
    scenario["urls"] = [configured_url] if configured_url else list(scenario.get("urls", []))
    return scenario


async def _extract_single_to_artifact(
    scenario_name: str | None = None,
    *,
    artifact_override: Path | None = None,
    retrieval_site: str | None = None,
) -> dict[str, Any]:
    """Extract one configured scenario and write evidence plus a JSON-LD source artifact.

    This helper does not mutate a Widget store. Normal source synchronization owns ingestion.
    """
    scenario_name = scenario_name or os.getenv("NLWEB_EXTERNAL_SOURCE_SCENARIO", "company_website")
    scenario = _scenario(scenario_name)
    configured_sources = [item for item in scenario["urls"] if item]
    if not configured_sources:
        raise RuntimeError(
            f"Scenario {scenario_name!r} has no configured URL. Set the corresponding "
            "NLWEB_EXTERNAL_SOURCE_*_URL environment variable first."
        )

    backend_value = os.getenv("NLWEB_EXTERNAL_SOURCE_EXTRACTOR_BACKEND", "").strip()
    if not backend_value:
        raise RuntimeError(
            "NLWEB_EXTERNAL_SOURCE_EXTRACTOR_BACKEND is required when extraction is enabled; "
            "choose scrapegraphai, scrapy_ollama, scrapy_transformers, or custom explicitly."
        )
    backend = backend_value.casefold()
    if backend not in {"scrapegraphai", "scrapy_ollama", "scrapy_transformers", "custom"}:
        raise ValueError(
            "NLWEB_EXTERNAL_SOURCE_EXTRACTOR_BACKEND must be scrapegraphai, scrapy_ollama, scrapy_transformers, or custom"
        )
    llm_enabled = os.getenv("NLWEB_EXTERNAL_SOURCE_LLM_ENABLED", "false").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }
    source_enabled = os.getenv("NLWEB_EXTERNAL_SOURCE_ENABLED", "false").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if backend in {"scrapegraphai", "scrapy_ollama", "scrapy_transformers"} and not llm_enabled:
        raise RuntimeError(
            f"The {backend} backend uses an LLM and requires NLWEB_EXTERNAL_SOURCE_LLM_ENABLED=true."
        )
    if backend == "custom" and not source_enabled:
        raise RuntimeError("The custom extractor requires NLWEB_EXTERNAL_SOURCE_ENABLED=true.")
    if backend == "custom" and not os.getenv("NLWEB_EXTERNAL_SOURCE_EXTRACTOR_FACTORY", "").strip():
        raise RuntimeError(
            "The custom backend requires NLWEB_EXTERNAL_SOURCE_EXTRACTOR_FACTORY=module:callable."
        )
    if backend in {"scrapy_ollama", "scrapy_transformers"}:
        if len(configured_sources) != 1:
            raise RuntimeError(f"{backend} currently accepts one configured URL per extraction run")
        generated_root = (ROOT / "generated").resolve()
        jsonld_output = (artifact_override or (ROOT / scenario["artifact"])).resolve()
        if jsonld_output.parent != generated_root or jsonld_output.suffix.lower() not in {
            ".jsonld",
            ".json",
        }:
            raise ValueError("Scenario artifact must be a JSON-LD file directly under generated/")
        allowed_hosts = os.getenv("NLWEB_EXTERNAL_SOURCE_ALLOWED_HOSTS", "")
        transformer_summary: dict[str, Any] = {}
        extraction_db: Path | None = None
        if backend == "scrapy_transformers":
            project_root = ROOT.parents[2]
            extraction_db = _artifact_path("NLWEB_EXTERNAL_SOURCE_EXTRACTION_DB", EXTRACTION_DB)
            command = [
                sys.executable,
                "-m",
                "examples.external_hosted_sources.domain_site_extractor.local_scrapy_transformers",
                configured_sources[0],
                "--allowed-hosts",
                allowed_hosts,
                "--output",
                str(jsonld_output),
                "--scenario",
                scenario_name,
                "--db-path",
                str(extraction_db),
            ]
            working_directory = project_root
        else:
            command = [
                sys.executable,
                str(ROOT / "local_scrapy_ollama.py"),
                configured_sources[0],
                "--allowed-hosts",
                allowed_hosts,
                "--output",
                str(jsonld_output),
            ]
            working_directory = ROOT
        completed = await asyncio.to_thread(
            subprocess.run,
            command,
            cwd=working_directory,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"{backend} extraction failed: " + (completed.stderr or completed.stdout)[-1500:]
            )
        if backend == "scrapy_transformers":
            try:
                parsed_summary = json.loads(completed.stdout)
                if isinstance(parsed_summary, dict):
                    transformer_summary = parsed_summary
            except json.JSONDecodeError:
                # Keep compatibility with test doubles or Scrapy versions that emit extra stdout.
                transformer_summary = {}
        try:
            artifact_payload = json.loads(jsonld_output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"{backend} did not produce a valid JSON-LD artifact") from exc
        graph = artifact_payload.get("@graph", []) if isinstance(artifact_payload, dict) else []
        artifact_sha256 = hashlib.sha256(jsonld_output.read_bytes()).hexdigest()
        prompt_payload = json.dumps(
            {"prompt": scenario["prompt"], "schema_hint": scenario.get("schema_hint", {})},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        prompt_sha256 = hashlib.sha256(prompt_payload.encode("utf-8")).hexdigest()
        provenance = {
            "schema_version": 1,
            "scenario": scenario_name,
            "backend": backend,
            "sources": configured_sources,
            "site": scenario["site"],
            "retrieval_site": retrieval_site or scenario["site"],
            "canonical_site_url": os.getenv(
                "NLWEB_EXTERNAL_SOURCE_SITE", "https://external-source.example/"
            ),
            "prompt_sha256": prompt_sha256,
            "artifact_sha256": artifact_sha256,
        }
        manifest_path = jsonld_output.with_name(jsonld_output.name + ".manifest.json")
        manifest_path.write_text(
            json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        result = {
            "scenario": scenario_name,
            "backend": backend,
            "site": retrieval_site or scenario["site"],
            "records": len(graph) if isinstance(graph, list) else 0,
            "jsonld": str(jsonld_output),
            "provenance": str(manifest_path),
            "sources": configured_sources,
            "message": f"{backend} generated the scenario JSON-LD artifact.",
        }
        if backend == "scrapy_transformers":
            result["db"] = str(transformer_summary.get("extraction_db") or extraction_db)
            if isinstance(transformer_summary.get("persisted_items"), int):
                result["persisted_items"] = transformer_summary["persisted_items"]
        return result
    extractor = (
        ScrapeGraphAIExtractor()
        if backend == "scrapegraphai"
        else configured_extractor_from_environment()
    )
    request = ExtractionRequest(
        scenario=scenario_name,
        sources=tuple(configured_sources),
        prompt=scenario["prompt"],
        schema_hint=scenario.get("schema_hint", {}),
    )
    result = await extractor.extract(request)

    extraction_db = _artifact_path("NLWEB_EXTERNAL_SOURCE_EXTRACTION_DB", EXTRACTION_DB)
    jsonld_output = (artifact_override or (ROOT / scenario["artifact"])).resolve()
    generated_root = (ROOT / "generated").resolve()
    if jsonld_output.parent != generated_root or jsonld_output.suffix.lower() not in {
        ".jsonld",
        ".json",
    }:
        raise ValueError("Scenario artifact must be a JSON-LD file directly under generated/")
    extraction_db.parent.mkdir(parents=True, exist_ok=True)
    store = ExtractionStore(extraction_db)
    store.save(request.prompt, result)

    site = os.getenv("NLWEB_EXTERNAL_SOURCE_SITE", "https://external-source.example/")
    records = extraction_to_jsonld(
        {"scenario": result.scenario, "payload": result.payload},
        site=site,
    )
    # The normal structured-source loader accepts one JSON-LD object per file. An @graph
    # object lets the generated corpus retain multiple records in one configured source.
    artifact = {"@context": "https://schema.org", "@graph": records}
    jsonld_output.parent.mkdir(parents=True, exist_ok=True)
    serialized_artifact = json.dumps(artifact, ensure_ascii=False, indent=2) + "\n"
    jsonld_output.write_text(serialized_artifact, encoding="utf-8")
    prompt_payload = json.dumps(
        {"prompt": scenario["prompt"], "schema_hint": scenario.get("schema_hint", {})},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    prompt_sha256 = hashlib.sha256(prompt_payload.encode("utf-8")).hexdigest()
    artifact_sha256 = hashlib.sha256(jsonld_output.read_bytes()).hexdigest()
    provenance = {
        "schema_version": 1,
        "scenario": scenario_name,
        "backend": backend,
        "sources": configured_sources,
        "site": scenario["site"],
        "retrieval_site": retrieval_site or scenario["site"],
        "canonical_site_url": site,
        "prompt_sha256": prompt_sha256,
        "artifact_sha256": artifact_sha256,
    }
    manifest_path = jsonld_output.with_name(jsonld_output.name + ".manifest.json")
    manifest_path.write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "scenario": scenario_name,
        "backend": backend,
        "site": retrieval_site or scenario["site"],
        "records": len(records),
        "jsonld": str(jsonld_output),
        "provenance": str(manifest_path),
        "db": str(extraction_db),
        "sources": configured_sources,
        "next_step": "Start the FastAPI app so its normal content-source synchronization ingests only this artifact under its declared corpus ID.",
    }


async def extract_to_artifact(scenario_name: str | None = None) -> dict[str, Any]:
    """Run enabled extraction paths and preserve each path as a separate artifact.

    The custom non-LLM path and the selected LLM path have independent outputs,
    provenance manifests, and runtime source registrations. Their records are never
    automatically combined; reconciliation is a separate consumer-controlled step.
    """
    _load_example_env()
    source_enabled = os.getenv("NLWEB_EXTERNAL_SOURCE_ENABLED", "false").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }
    llm_enabled = os.getenv("NLWEB_EXTERNAL_SOURCE_LLM_ENABLED", "false").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }
    backend = os.getenv("NLWEB_EXTERNAL_SOURCE_EXTRACTOR_BACKEND", "").strip().casefold()
    if not source_enabled and not llm_enabled:
        raise RuntimeError(
            "Extraction is disabled. Explicitly enable NLWEB_EXTERNAL_SOURCE_ENABLED and/or NLWEB_EXTERNAL_SOURCE_LLM_ENABLED."
        )
    if not backend:
        raise RuntimeError(
            "NLWEB_EXTERNAL_SOURCE_EXTRACTOR_BACKEND must be explicitly configured before extraction."
        )
    if source_enabled and not os.getenv("NLWEB_EXTERNAL_SOURCE_EXTRACTOR_FACTORY", "").strip():
        raise RuntimeError(
            "NLWEB_EXTERNAL_SOURCE_ENABLED=true requires NLWEB_EXTERNAL_SOURCE_EXTRACTOR_FACTORY=module:callable."
        )
    if llm_enabled and backend not in {"scrapegraphai", "scrapy_ollama", "scrapy_transformers"}:
        raise RuntimeError(
            "NLWEB_EXTERNAL_SOURCE_LLM_ENABLED=true requires backend scrapegraphai, scrapy_ollama, or scrapy_transformers."
        )
    if source_enabled and not llm_enabled and backend != "custom":
        raise RuntimeError(
            "The non-LLM extraction path requires NLWEB_EXTERNAL_SOURCE_EXTRACTOR_BACKEND=custom."
        )

    if source_enabled and llm_enabled:
        scenario_name = scenario_name or os.getenv(
            "NLWEB_EXTERNAL_SOURCE_SCENARIO", "company_website"
        )
        scenario = _scenario(scenario_name)
        final_path = (ROOT / scenario["artifact"]).resolve()
        generated_root = (ROOT / "generated").resolve()
        if final_path.parent != generated_root:
            raise ValueError("Scenario artifact must be directly under generated/")
        custom_path = generated_root / f"{final_path.stem}.custom.jsonld"
        llm_path = generated_root / f"{final_path.stem}.{backend}.jsonld"
        original = {
            key: os.environ.get(key)
            for key in (
                "NLWEB_EXTERNAL_SOURCE_EXTRACTOR_BACKEND",
                "NLWEB_EXTERNAL_SOURCE_ENABLED",
                "NLWEB_EXTERNAL_SOURCE_LLM_ENABLED",
            )
        }
        try:
            os.environ["NLWEB_EXTERNAL_SOURCE_EXTRACTOR_BACKEND"] = "custom"
            os.environ["NLWEB_EXTERNAL_SOURCE_ENABLED"] = "true"
            os.environ["NLWEB_EXTERNAL_SOURCE_LLM_ENABLED"] = "false"
            custom_result = await _extract_single_to_artifact(
                scenario_name, artifact_override=custom_path, retrieval_site=scenario["site"]
            )

            os.environ["NLWEB_EXTERNAL_SOURCE_EXTRACTOR_BACKEND"] = backend
            os.environ["NLWEB_EXTERNAL_SOURCE_ENABLED"] = "false"
            os.environ["NLWEB_EXTERNAL_SOURCE_LLM_ENABLED"] = "true"
            llm_result = await _extract_single_to_artifact(
                scenario_name,
                artifact_override=llm_path,
                retrieval_site=backend_corpus_id(scenario["site"], backend),
            )
            return {
                "scenario": scenario_name,
                "results": {"custom": custom_result, backend: llm_result},
                "artifacts": {"custom": str(custom_path), backend: str(llm_path)},
                "message": "Extraction paths ran independently. Each output and provenance manifest remains separate and is registered independently for runtime source synchronization; no automatic merge was performed.",
            }
        finally:
            for key, value in original.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
    return await _extract_single_to_artifact(scenario_name)


async def main(scenario_name: str | None = None) -> None:
    result = await extract_to_artifact(scenario_name)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
