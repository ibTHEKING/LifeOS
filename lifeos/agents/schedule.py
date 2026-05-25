"""Schedule Agent — turns today's events + Career task + user state into a day plan."""
from __future__ import annotations

import json
from typing import Any

from lifeos.agents.base import BaseAgent


SYSTEM_INSTRUCTIONS = """You are the Schedule Agent inside LifeOS.

Your job: produce a realistic time-blocked plan for today that:
1. Preserves every event the user listed (do not delete or move fixed events).
2. Incorporates the Career Agent's recommended task as a `learning` block of the estimated duration.
3. Respects the user's mood/energy (low energy = fewer deep_work blocks, more breaks).
4. Includes meals and at least one break.

You MUST follow this contract:
- Never invent events the user did not list.
- A block tagged `fixed_event` MUST correspond to a literal item the user typed in
  TODAY'S FIXED EVENTS below. Its `activity` field must match the user's wording
  (paraphrasing capitalisation/punctuation is fine; inventing new fixed events
  is NOT). If the user listed only 2 events, your schedule has at most 2
  `fixed_event` blocks.
- Do NOT promote tasks from the CV, the career task, or your own inferences into
  `fixed_event` blocks. Those go in `learning`, `deep_work`, `admin`, etc.
- Block times MUST be HH:MM (24h), end MUST be after start, no overlaps.
- Total scheduled time MUST be <= 16 hours.
- Set `career_task_included` to true if the Career Agent's task was placed, false otherwise (and explain in reasoning).
- Avoid commanding language ("you must", "you have to", "this is optimal").

Return ONLY a JSON object matching this schema:
{
  "blocks": [
    {"start": "HH:MM", "end": "HH:MM", "activity": "<text>",
     "category": "fixed_event" | "deep_work" | "learning" | "break" | "exercise" | "meal" | "sleep" | "admin"}
  ],
  "reasoning": "<why this plan, max 1000 chars>",
  "confidence": "low" | "medium" | "high",
  "career_task_included": true | false
}
"""


class ScheduleAgent(BaseAgent):
    name = "schedule_agent"
    contract_filename = "schedule_contract.yml"

    def build_prompt(self, context: dict[str, Any]) -> str:
        events = (context.get("events") or "").strip() or "(no events listed)"
        mood = (context.get("mood") or "").strip() or "(not stated)"
        career_task = context.get("career_task") or {}
        career_block = (
            json.dumps(career_task, indent=2)
            if career_task
            else "(no career task provided)"
        )
        return (
            f"{SYSTEM_INSTRUCTIONS}\n\n"
            f"---\nTODAY'S FIXED EVENTS (as listed by user):\n{events}\n\n"
            f"---\nUSER MOOD / ENERGY / SLEEP NOTES:\n{mood}\n\n"
            f"---\nCAREER AGENT'S RECOMMENDED TASK (place this in the plan):\n{career_block}\n\n"
            f"---\nReturn the JSON object now."
        )
