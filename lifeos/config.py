"""Central config: paths and model selection. No secrets here."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS_DIR = ROOT / "contracts"
DATA_DIR = ROOT / "data"
LOGS_DIR = ROOT / "logs"

# Model tiers.
# "flash" = cheap, fast — used by the agents.
# "pro"   = stronger reasoning — used by the Judge (intentionally different model).
# This separation is a deliberate design choice: same-model self-grading is a
# known weakness of LLM-as-judge setups, so the Judge runs on a different tier.
AGENT_MODEL = os.getenv("LIFEOS_AGENT_MODEL", "gemini-3.1-flash-lite")
JUDGE_MODEL = os.getenv("LIFEOS_JUDGE_MODEL", "gemini-3.5-flash")
