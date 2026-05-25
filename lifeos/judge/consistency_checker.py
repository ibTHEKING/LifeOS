"""LLM-based consistency check. Runs AFTER the deterministic validator passes."""
from __future__ import annotations

import json
from typing import Any

from lifeos.llm import LLMClient


PROMPT_TEMPLATE = """You are the LifeOS Judge — Consistency Layer.

You evaluate the output of another AI agent and decide whether it is consistent
with the input it was given and with the system's truthfulness rules.

You are NOT the agent. You do NOT do the agent's job. You judge.

Score consistency on a 0.0 - 1.0 scale where:
- 1.0 = fully grounded in input, no fabrication, contract rules honored
- 0.7 = mostly grounded, minor issues that do not break the output
- 0.4 = partially fabricated, missing grounding, or violates a soft rule
- 0.0 = mostly fabricated, contradicts input, or violates a hard rule

Hard rules (any violation -> score <= 0.3):
- Output cites facts not present in input (made-up companies, certifications, events, sources).
- Output contradicts input.
- Output is overconfident given the evidence available.

Return ONLY this JSON:
{{
  "consistency_score": <float 0.0-1.0>,
  "issues": ["<short concrete issue>", ...],
  "reasoning": "<2-4 sentences explaining the score>"
}}

---
AGENT BEING JUDGED: {agent_name}
AGENT'S CONTRACT (rules it must obey):
{contract_summary}

---
INPUT THE AGENT RECEIVED:
{agent_input}

---
OUTPUT THE AGENT PRODUCED:
{agent_output}

---
Return the JSON now.
"""


class ConsistencyChecker:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def check(
        self,
        agent_name: str,
        agent_input: dict[str, Any],
        agent_output: dict[str, Any],
        contract: dict[str, Any],
    ) -> dict[str, Any]:
        prompt = PROMPT_TEMPLATE.format(
            agent_name=agent_name,
            contract_summary=self._summarize_contract(contract),
            agent_input=self._compact_input(agent_input),
            agent_output=json.dumps(agent_output, indent=2, ensure_ascii=False)[:8000],
        )
        result = self.llm.generate_json(prompt, tier="pro")

        if "_parse_error" in result:
            return {
                "consistency_score": 0.0,
                "issues": ["judge_returned_non_json"],
                "reasoning": result.get("_raw_text", "")[:500],
            }

        score = result.get("consistency_score", 0.0)
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = 0.0
        score = max(0.0, min(1.0, score))

        return {
            "consistency_score": score,
            "issues": result.get("issues", []),
            "reasoning": result.get("reasoning", ""),
        }

    @staticmethod
    def _compact_input(agent_input: dict[str, Any]) -> str:
        """Reduce agent_input to a compact view that fits comfortably in the
        Judge prompt while preserving the facts the Judge needs to verify
        groundedness — including the FULL job list as index+title+company so
        the Judge cannot miscount jobs.
        """
        compact: dict[str, Any] = {}
        if "cv" in agent_input:
            compact["cv_excerpt"] = (agent_input["cv"] or "")[:2500]
        if "goal" in agent_input:
            compact["goal"] = agent_input["goal"]
        if "events" in agent_input:
            compact["events"] = (agent_input["events"] or "")[:800]
        if "mood" in agent_input:
            compact["mood"] = agent_input["mood"]
        if "jobs" in agent_input:
            jobs = agent_input.get("jobs") or []
            compact["jobs_total_count"] = len(jobs)
            compact["jobs"] = [
                {
                    "index": i + 1,
                    "title": j.get("title", ""),
                    "company": j.get("company", ""),
                    "location": j.get("location", ""),
                    "source": j.get("source", ""),
                }
                for i, j in enumerate(jobs)
            ]
        if "career_task" in agent_input:
            compact["career_task"] = agent_input["career_task"]
        if "schedule" in agent_input:
            sched = agent_input.get("schedule") or {}
            # Pass through the full block list — the Productivity Agent needs the Judge
            # to see exactly what blocks existed, otherwise the Judge wrongly flags
            # legitimate references as fabricated.
            compact["schedule"] = {
                "blocks": sched.get("blocks", []),
                "reasoning": (sched.get("reasoning", "") or "")[:400],
                "confidence": sched.get("confidence"),
                "career_task_included": sched.get("career_task_included"),
            }
        return json.dumps(compact, indent=2, ensure_ascii=False)

    @staticmethod
    def _summarize_contract(contract: dict[str, Any]) -> str:
        parts: list[str] = []
        if "description" in contract:
            parts.append(f"Purpose: {contract['description']}")
        if "truthfulness_rules" in contract:
            parts.append("Truthfulness rules:")
            for r in contract["truthfulness_rules"]:
                parts.append(f"  - {r}")
        if "forbidden_phrases" in contract:
            parts.append(f"Forbidden phrases: {contract['forbidden_phrases']}")
        return "\n".join(parts)
