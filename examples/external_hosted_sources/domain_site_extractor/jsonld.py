"""Transform stored extraction results into additive Schema.org/JSON-LD records."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def extraction_to_jsonld(result: Mapping[str, Any], *, site: str) -> list[dict[str, Any]]:
    """Convert common structured extraction shapes into additive JSON-LD records.

    The function intentionally creates a new extension corpus; it never mutates
    the authoritative source file. Consumers can review/merge the generated
    records according to their own domain governance policy.
    """
    payload = result.get("payload", result)
    records = payload.get("records") if isinstance(payload, Mapping) else None
    if records is None:
        records = payload.get("items") if isinstance(payload, Mapping) else None
    if records is None:
        records = [payload]
    if not isinstance(records, list):
        records = [records]

    output: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            record = {"description": str(record)}
        schema_type = str(record.get("@type") or record.get("type") or "Thing")
        item_id = str(
            record.get("@id")
            or record.get("url")
            or f"urn:nlweb:external:{result.get('scenario', 'source')}:{index}"
        )
        normalized = {
            "@context": "https://schema.org",
            "@type": schema_type,
            "@id": item_id,
            "isPartOf": site,
            **{
                str(key): value
                for key, value in record.items()
                if key not in {"@context", "@type", "@id"}
            },
        }
        output.append(normalized)
    return output
