"""Base class shared by every agent. Loads its YAML contract and exposes a run() API."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import yaml

from lifeos.config import CONTRACTS_DIR
from lifeos.llm import LLMClient


class BaseAgent(ABC):
    name: str = "base"
    contract_filename: str = ""

    def __init__(self, llm: LLMClient):
        self.llm = llm
        self.contract: dict[str, Any] = self._load_contract()

    def _load_contract(self) -> dict[str, Any]:
        path: Path = CONTRACTS_DIR / self.contract_filename
        if not path.exists():
            raise FileNotFoundError(f"Contract not found: {path}")
        with path.open(encoding="utf-8") as f:
            return yaml.safe_load(f)

    @abstractmethod
    def build_prompt(self, context: dict[str, Any]) -> str:
        """Return the prompt string sent to the LLM."""

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        prompt = self.build_prompt(context)
        output = self.llm.generate_json(prompt, tier="flash")
        return {"agent": self.name, "output": output, "prompt": prompt}
