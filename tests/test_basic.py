"""Minimal sanity tests for the deterministic pieces (no LLM calls).

Run:  python -m pytest tests/  (after pip install pytest)
Or:   python tests/test_basic.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lifeos.judge.contract_validator import ContractValidator


def test_contract_validator_catches_missing_required_field():
    contract = {
        "output_schema": {
            "task": {"type": "string", "required": True, "max_length": 100},
            "confidence": {"type": "enum", "required": True, "values": ["low", "medium", "high"]},
        }
    }
    output = {"task": "Practice SQL joins"}
    result = ContractValidator().validate(output, contract)
    assert not result["passed"]
    assert any("confidence" in i for i in result["issues"])


def test_contract_validator_catches_bad_enum():
    contract = {
        "output_schema": {
            "confidence": {"type": "enum", "required": True, "values": ["low", "medium", "high"]},
        }
    }
    output = {"confidence": "very_high"}
    result = ContractValidator().validate(output, contract)
    assert not result["passed"]


def test_contract_validator_catches_overlapping_blocks():
    contract = {"output_schema": {}}
    output = {
        "blocks": [
            {"start": "09:00", "end": "10:00", "activity": "x", "category": "deep_work"},
            {"start": "09:30", "end": "11:00", "activity": "y", "category": "deep_work"},
        ]
    }
    result = ContractValidator().validate(output, contract)
    assert not result["passed"]
    assert any("overlap" in i for i in result["issues"])


def test_contract_validator_catches_end_before_start():
    contract = {"output_schema": {}}
    output = {
        "blocks": [
            {"start": "10:00", "end": "09:00", "activity": "x", "category": "deep_work"},
        ]
    }
    result = ContractValidator().validate(output, contract)
    assert not result["passed"]


def test_contract_validator_catches_forbidden_phrase():
    contract = {
        "output_schema": {"task": {"type": "string", "required": True}},
        "forbidden_phrases": ["guaranteed to"],
    }
    output = {"task": "This is guaranteed to work."}
    result = ContractValidator().validate(output, contract)
    assert not result["passed"]


def test_contract_validator_passes_clean_output():
    contract = {
        "output_schema": {
            "task": {"type": "string", "required": True, "max_length": 100},
            "confidence": {"type": "enum", "required": True, "values": ["low", "medium", "high"]},
            "estimated_minutes": {"type": "integer", "required": True, "min": 15, "max": 240},
        }
    }
    output = {"task": "Practice SQL joins on a real dataset", "confidence": "medium", "estimated_minutes": 60}
    result = ContractValidator().validate(output, contract)
    assert result["passed"], result["issues"]


if __name__ == "__main__":
    test_contract_validator_catches_missing_required_field()
    test_contract_validator_catches_bad_enum()
    test_contract_validator_catches_overlapping_blocks()
    test_contract_validator_catches_end_before_start()
    test_contract_validator_catches_forbidden_phrase()
    test_contract_validator_passes_clean_output()
    print("All basic tests passed.")
