"""Append-only JSON-lines logger. One file per session."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from lifeos.config import LOGS_DIR


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


class RunLogger:
    def __init__(self, run_id: str):
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.path: Path = LOGS_DIR / f"run_{run_id}.jsonl"
        self._entries: list[dict[str, Any]] = []

    def log(self, stage: str, payload: dict[str, Any]) -> None:
        entry = {"ts": _now_iso(), "run_id": self.run_id, "stage": stage, **payload}
        self._entries.append(entry)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    def entries(self) -> list[dict[str, Any]]:
        return list(self._entries)
