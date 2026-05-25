"""Deterministic contract validation. No LLM calls. Cheap, fast, runs first."""
from __future__ import annotations

import re
from typing import Any


class ContractValidator:
    """Validates agent outputs against the rules declared in their YAML contract.

    This runs BEFORE the LLM consistency check, on purpose:
    - it is free and instant
    - if it fails, we save a stronger-tier API call
    - it catches the structural errors (missing keys, bad enums, time overlaps)
      that LLMs are bad at noticing in their own output.
    """

    def validate(
        self,
        output: dict[str, Any],
        contract: dict[str, Any],
    ) -> dict[str, Any]:
        issues: list[str] = []

        if "_parse_error" in output:
            issues.append(f"output is not valid JSON: {output.get('_parse_error')}")
            return self._verdict(issues)

        schema: dict[str, Any] = contract.get("output_schema", {})
        for field, spec in schema.items():
            issues.extend(self._check_field(field, spec, output, field))

        for phrase in contract.get("forbidden_phrases", []):
            blob = self._stringify(output).lower()
            if phrase.lower() in blob:
                issues.append(f"forbidden phrase used: '{phrase}'")

        issues.extend(self._domain_checks(output))

        return self._verdict(issues)

    def _verdict(self, issues: list[str]) -> dict[str, Any]:
        return {"passed": len(issues) == 0, "issues": issues}

    def _check_field(
        self,
        field: str,
        spec: dict[str, Any],
        container: dict[str, Any],
        display_name: str,
    ) -> list[str]:
        """Validate `container[field]` against `spec`.

        `field` is the dict key used for lookup; `display_name` is what appears
        in error messages. They differ when we recurse into array items
        (lookup is the sub-field name, display is e.g. 'blocks[3].start').
        """
        issues: list[str] = []
        required = spec.get("required", False)
        if field not in container:
            if required:
                issues.append(f"missing required field: '{display_name}'")
            return issues

        value = container[field]
        expected = spec.get("type")

        if expected == "string":
            if not isinstance(value, str):
                issues.append(f"'{display_name}' must be string, got {type(value).__name__}")
            else:
                max_len = spec.get("max_length")
                if max_len and len(value) > max_len:
                    issues.append(f"'{display_name}' exceeds max_length {max_len}")
                pattern = spec.get("pattern")
                if pattern and not re.match(pattern, value):
                    issues.append(f"'{display_name}' does not match pattern {pattern}")
        elif expected == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                issues.append(f"'{display_name}' must be integer")
            else:
                if "min" in spec and value < spec["min"]:
                    issues.append(f"'{display_name}' below min {spec['min']}")
                if "max" in spec and value > spec["max"]:
                    issues.append(f"'{display_name}' above max {spec['max']}")
        elif expected == "boolean":
            if not isinstance(value, bool):
                issues.append(f"'{display_name}' must be boolean")
        elif expected == "enum":
            allowed = spec.get("values", [])
            if value not in allowed:
                issues.append(f"'{display_name}' must be one of {allowed}, got {value!r}")
        elif expected == "array":
            if not isinstance(value, list):
                issues.append(f"'{display_name}' must be array")
            else:
                min_items = spec.get("min_items")
                if min_items is not None and len(value) < min_items:
                    issues.append(f"'{display_name}' needs at least {min_items} items")
                item_schema = spec.get("item_schema")
                if item_schema:
                    for i, item in enumerate(value):
                        if not isinstance(item, dict):
                            issues.append(f"'{display_name}[{i}]' must be object")
                            continue
                        for sub_field, sub_spec in item_schema.items():
                            sub_display = f"{display_name}[{i}].{sub_field}"
                            issues.extend(
                                self._check_field(sub_field, sub_spec, item, sub_display)
                            )
        return issues

    def _domain_checks(self, output: dict[str, Any]) -> list[str]:
        """Schedule-specific sanity: overlaps, end>start, total minutes <= 24h.

        Allows a single midnight-crossing block (e.g. sleep 22:30 -> 07:00)
        by interpreting end < start as "next day".
        """
        issues: list[str] = []
        blocks = output.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            return issues

        def to_min(t: str) -> int | None:
            try:
                h, m = t.split(":")
                return int(h) * 60 + int(m)
            except Exception:
                return None

        intervals: list[tuple[int, int, int]] = []
        crossed_midnight = 0
        total = 0
        for i, b in enumerate(blocks):
            s, e = to_min(b.get("start", "")), to_min(b.get("end", ""))
            if s is None or e is None:
                issues.append(f"blocks[{i}] has unparseable time")
                continue
            if e == s:
                issues.append(f"blocks[{i}] has zero duration ({b['start']} = {b['end']})")
                continue
            if e < s:
                # Only treat as midnight crossing if start is evening (>=18:00)
                # AND end is morning (<=12:00). Anything else is a real bug.
                evening_start = s >= 18 * 60
                morning_end = e <= 12 * 60
                if evening_start and morning_end:
                    crossed_midnight += 1
                    if crossed_midnight > 1:
                        issues.append(f"blocks[{i}] is an additional midnight-crossing block; only one is allowed")
                        continue
                    e += 24 * 60
                else:
                    issues.append(f"blocks[{i}] end ({b['end']}) <= start ({b['start']})")
                    continue
            intervals.append((s, e, i))
            total += e - s

        intervals.sort()
        for a, b in zip(intervals, intervals[1:]):
            if a[1] > b[0]:
                issues.append(f"blocks[{a[2]}] overlaps blocks[{b[2]}]")

        if total > 24 * 60:
            issues.append(f"total scheduled time {total} min exceeds 24h limit")

        return issues

    @staticmethod
    def _stringify(obj: Any) -> str:
        import json as _json

        try:
            return _json.dumps(obj, ensure_ascii=False)
        except Exception:
            return str(obj)
