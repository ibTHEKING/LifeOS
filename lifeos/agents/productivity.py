"""Productivity Agent — small briefing on top of the day plan.

Inputs:
- schedule (the Schedule Agent's accepted plan)
- mood     (sleep / energy / stress description)
- career_task (so it can comment on it if relevant)

Outputs (per contract):
- focus_rule_today, procrastination_risk, top_priority_block,
  productivity_score, rationale, confidence
"""
from __future__ import annotations

import json
from typing import Any

from lifeos.agents.base import BaseAgent


SYSTEM_INSTRUCTIONS = """You are the Productivity Agent inside LifeOS.

You are given the user's accepted day plan (already produced by another agent),
the user's mood/energy/sleep state, and the learning task that the Career
Agent proposed.

You do NOT redesign the schedule. You do NOT add tasks. You write a SHORT
productivity briefing.

ABSOLUTE RULES — read carefully:
- DO NOT include any time references (no "10:30-12:30", no "11:00", no hours).
  Times are easy to hallucinate. Refer to blocks by their activity name only.
- top_priority_block MUST be copied VERBATIM from the 'activity' field of one
  of the schedule blocks listed below. Not the career task. Not a paraphrase.
- focus_rule_today is a generic but concrete rule for today (e.g. "Phone in
  another room during any deep_work or learning block."). Do NOT mention
  specific clock times.

Specifically, output:
- focus_rule_today: ONE rule. No time references. Max 200 chars.
- procrastination_risk: low / medium / high based on mood + plan structure.
- top_priority_block: activity name copied verbatim from a schedule block.
- productivity_score: integer 1-10 reflecting how well today's plan is set up
  given the user's mood/energy. Do not default to 7 or 8.
- rationale: 2-3 sentences explaining the score. No time references.

Contract rules:
- Never invent schedule blocks that aren't in the input.
- Never invent clock times in any field.
- If mood shows burnout (low sleep, high stress, low energy), score must be
  lower and procrastination_risk should be medium or high.
- Avoid commanding language like "you must" or "this is the optimal".

Return ONLY a JSON object with EXACTLY these keys:
{{
  "focus_rule_today": "<one concrete rule, max 200 chars>",
  "procrastination_risk": "low"|"medium"|"high",
  "top_priority_block": "<activity name copied from the schedule, max 200 chars>",
  "productivity_score": <integer 1-10>,
  "rationale": "<2-3 sentences, max 600 chars>",
  "confidence": "low"|"medium"|"high"
}}
"""


class ProductivityAgent(BaseAgent):
    name = "productivity_agent"
    contract_filename = "productivity_contract.yml"

    def build_prompt(self, context: dict[str, Any]) -> str:
        schedule = context.get("schedule") or {}
        mood = (context.get("mood") or "").strip() or "(not stated)"
        career_task = context.get("career_task") or {}

        blocks = schedule.get("blocks", [])
        if blocks:
            # Intentionally do NOT show clock times — only activity + category.
            # This makes time-hallucination impossible.
            sched_str = "\n".join(
                f"- [{b.get('category','')}] {b.get('activity','')}"
                for b in blocks
            )
        else:
            sched_str = "(no schedule blocks provided)"

        ct_str = (
            json.dumps(career_task, indent=2, ensure_ascii=False)
            if career_task
            else "(no career task)"
        )

        return (
            f"{SYSTEM_INSTRUCTIONS}\n\n"
            f"---\nTODAY'S SCHEDULE (already produced and accepted):\n{sched_str}\n\n"
            f"---\nUSER MOOD / SLEEP / ENERGY:\n{mood}\n\n"
            f"---\nCAREER AGENT'S RECOMMENDED LEARNING TASK:\n{ct_str}\n\n"
            f"---\nReturn the JSON object now."
        )
