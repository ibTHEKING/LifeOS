"""Orchestrator — runs the agent chain with Judge gating between steps."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from lifeos.agents import CareerAgent, ProductivityAgent, ScheduleAgent
from lifeos.judge import Judge, Verdict
from lifeos.jobs import search_jobs
from lifeos.llm import LLMClient
from lifeos.logger import RunLogger


@dataclass
class StageResult:
    agent_name: str
    output: dict[str, Any]
    verdict: Verdict
    latency_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "output": self.output,
            "verdict": self.verdict.to_dict(),
            "latency_ms": self.latency_ms,
        }


@dataclass
class RunResult:
    run_id: str
    stages: list[StageResult] = field(default_factory=list)
    final_plan: dict[str, Any] | None = None
    accepted: bool = False
    halted_reason: str | None = None
    all_jobs: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "accepted": self.accepted,
            "halted_reason": self.halted_reason,
            "final_plan": self.final_plan,
            "stages": [s.to_dict() for s in self.stages],
            "all_jobs": self.all_jobs,
        }


class Orchestrator:
    """Runs Career -> Judge -> Schedule -> Judge.

    If the Judge rejects an agent output, the run halts and reports why.
    If the Judge says 'revise', we accept it but flag it (one-shot, no retry loop —
    keeps runtime predictable and cheap on free tier).
    """

    def __init__(self, llm: LLMClient | None = None):
        self.llm = llm or LLMClient()
        self.judge = Judge(self.llm)
        self.career = CareerAgent(self.llm)
        self.schedule = ScheduleAgent(self.llm)
        self.productivity = ProductivityAgent(self.llm)

    def run(self, cv: str, goal: str, events: str, mood: str) -> RunResult:
        run_id = uuid.uuid4().hex[:8]
        logger = RunLogger(run_id)
        result = RunResult(run_id=run_id)

        logger.log(
            "run_start",
            {"inputs": {"cv_len": len(cv), "goal": goal, "events": events, "mood": mood}},
        )

        # Pull real job listings before invoking the Career Agent.
        try:
            jobs = search_jobs(cv_text=cv, goal_text=goal, max_results=8)
        except Exception as e:
            jobs = []
            logger.log("jobs_search_error", {"error": f"{type(e).__name__}: {e}"})
        logger.log("jobs_search", {"count": len(jobs), "top": jobs[:3]})
        result.all_jobs = jobs

        career_stage = self._run_stage(
            agent=self.career,
            agent_input={"cv": cv, "goal": goal, "jobs": jobs},
            logger=logger,
        )

        # Resolve selected_job_index -> full job (or null) before downstream uses it.
        idx = career_stage.output.get("selected_job_index")
        if isinstance(idx, int) and 1 <= idx <= len(jobs):
            career_stage.output["selected_job"] = jobs[idx - 1]
        else:
            career_stage.output["selected_job"] = None

        result.stages.append(career_stage)
        # We DO NOT halt on Career reject. The Career output is still useful as
        # advisory input to Schedule; the user simply sees the rejection flag and
        # the Judge's reasoning. This avoids the "blank screen" demo experience
        # when the Judge catches a minor contract violation.
        if career_stage.verdict.label == "reject":
            logger.log("career_rejected_but_continuing", {})

        schedule_stage = self._run_stage(
            agent=self.schedule,
            agent_input={
                "events": events,
                "mood": mood,
                "career_task": career_stage.output,
            },
            logger=logger,
        )
        result.stages.append(schedule_stage)
        if schedule_stage.verdict.label == "reject":
            result.halted_reason = "Schedule Agent output was rejected by Judge."
            logger.log("run_halted", {"reason": result.halted_reason})
            return result

        # Productivity Agent — runs last because it analyses the accepted plan.
        productivity_stage = self._run_stage(
            agent=self.productivity,
            agent_input={
                "schedule": schedule_stage.output,
                "mood": mood,
                "career_task": career_stage.output,
            },
            logger=logger,
        )
        result.stages.append(productivity_stage)
        # We do NOT halt on a Productivity reject — it is advisory, not load-bearing.
        # We just flag it in the final output.

        result.accepted = True
        result.final_plan = {
            "career_task": career_stage.output,
            "schedule": schedule_stage.output,
            "productivity": productivity_stage.output,
            "productivity_verdict": productivity_stage.verdict.label,
        }
        logger.log("run_complete", {"accepted": True})
        return result

    def _run_stage(
        self,
        agent,
        agent_input: dict[str, Any],
        logger: RunLogger,
    ) -> StageResult:
        t0 = time.monotonic()
        agent_run = agent.run(agent_input)
        output = agent_run["output"]
        logger.log(
            f"{agent.name}.output",
            {"prompt_len": len(agent_run["prompt"]), "output": output},
        )

        verdict = self.judge.judge(
            agent_name=agent.name,
            agent_input=agent_input,
            agent_output=output,
            contract=agent.contract,
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.log(
            f"{agent.name}.verdict",
            {"verdict": verdict.to_dict(), "latency_ms": latency_ms},
        )

        return StageResult(
            agent_name=agent.name,
            output=output,
            verdict=verdict,
            latency_ms=latency_ms,
        )
