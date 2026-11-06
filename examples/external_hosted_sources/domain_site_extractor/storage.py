"""Dedicated SQLite persistence for externally extracted data."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .adapter import ExtractionResult


class ExtractionStore:
    """Persist extraction evidence separately from the Widget retrieval store."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _initialize(self) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS extractions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scenario TEXT NOT NULL,
                    sources_json TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    extractor TEXT NOT NULL,
                    llm_provider TEXT,
                    model TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_extractions_scenario ON extractions(scenario)"
            )
            connection.commit()

    def save(self, request_prompt: str, result: ExtractionResult) -> int:
        with sqlite3.connect(self.path) as connection:
            cursor = connection.execute(
                """INSERT INTO extractions
                (scenario, sources_json, prompt, payload_json, extractor, llm_provider, model)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    result.scenario,
                    json.dumps(list(result.sources), ensure_ascii=False),
                    request_prompt,
                    json.dumps(dict(result.payload), ensure_ascii=False, default=str),
                    result.extractor,
                    result.llm_provider,
                    result.model,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def save_raw(
        self,
        *,
        scenario: str,
        sources: Iterable[str],
        prompt: str,
        payload: dict[str, Any],
        extractor: str,
        llm_provider: str | None = None,
        model: str | None = None,
    ) -> int:
        """Persist one raw backend item using the same audit schema as adapter results."""
        with sqlite3.connect(self.path) as connection:
            cursor = connection.execute(
                """INSERT INTO extractions
                (scenario, sources_json, prompt, payload_json, extractor, llm_provider, model)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    scenario,
                    json.dumps(list(sources), ensure_ascii=False),
                    prompt,
                    json.dumps(payload, ensure_ascii=False, default=str),
                    extractor,
                    llm_provider,
                    model,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def iter_results(self) -> Iterable[dict[str, Any]]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT id, scenario, sources_json, payload_json, extractor, "
                "llm_provider, model, created_at FROM extractions ORDER BY id"
            ).fetchall()
        for row in rows:
            yield {
                "id": row[0],
                "scenario": row[1],
                "sources": json.loads(row[2]),
                "payload": json.loads(row[3]),
                "extractor": row[4],
                "llm_provider": row[5],
                "model": row[6],
                "created_at": row[7],
            }
