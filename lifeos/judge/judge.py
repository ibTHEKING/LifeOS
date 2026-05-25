"""The Judge — orchestrates the two-layer governance check (deterministic + LLM)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from lifeos.judge.consistency_checker import ConsistencyChecker
from lifeos.judge.contract_validator import ContractValidator
from lifeos.llm import LLMClient


VerdictLabel = Literal["accept", "revise", "reject"]


@dataclass
class Verdict:
    label: VerdictLabel
    contract_passed: bool
    contract_issues: list[str]
    consistency_score: float
    consistency_issues: list[str]
    consistency_reasoning: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "contract_passed": self.contract_passed,
            "contract_issues": self.contract_issues,
            "consistency_score": self.consistency_score,
            "consistency_issues": self.consistency_issues,
            "consistency_reasoning": self.consistency_reasoning,
        }


class Judge:
    """Two-layer governance: deterministic contract check, then LLM consistency check.

    Decision rule:
      - contract fails              -> reject (no LLM call)
      - contract passes, score>=0.7 -> accept
      - contract passes, 0.4<=s<0.7 -> revise
      - contract passes, score<0.4  -> reject
    """

    ACCEPT_THRESHOLD = 0.7
    REVISE_THRESHOLD = 0.4

    def __init__(self, llm: LLMClient):
        self.validator = ContractValidator()
        self.consistency = ConsistencyChecker(llm)

    def judge(
        self,
        agent_name: str,
        agent_input: dict[str, Any],
        agent_output: dict[str, Any],
        contract: dict[str, Any],
    ) -> Verdict:
        contract_result = self.validator.validate(agent_output, contract)

        if not contract_result["passed"]:
            return Verdict(
                label="reject",
                contract_passed=False,
                contract_issues=contract_result["issues"],
                consistency_score=0.0,
                consistency_issues=["skipped (contract failed)"],
                consistency_reasoning="Skipped LLM consistency check because the deterministic contract validator already rejected the output.",
            )

        consistency_result = self.consistency.check(
            agent_name=agent_name,
            agent_input=agent_input,
            agent_output=agent_output,
            contract=contract,
        )
        score = consistency_result["consistency_score"]

        if score >= self.ACCEPT_THRESHOLD:
            label: VerdictLabel = "accept"
        elif score >= self.REVISE_THRESHOLD:
            label = "revise"
        else:
            label = "reject"

        return Verdict(
            label=label,
            contract_passed=True,
            contract_issues=[],
            consistency_score=score,
            consistency_issues=consistency_result["issues"],
            consistency_reasoning=consistency_result["reasoning"],
        )
