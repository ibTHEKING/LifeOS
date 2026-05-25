"""Thin wrapper around google-genai. Two tiers: agents (flash) vs judge (pro).

Includes a small custom retry on top of the SDK's built-in retry for the
free-tier 503 / RESOURCE_EXHAUSTED bursts that happen during peak hours.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

from google import genai
from google.genai import types
from google.genai import errors as genai_errors

from lifeos.config import AGENT_MODEL, JUDGE_MODEL


class LLMError(RuntimeError):
    pass


# Models we fall back to (in order) if the primary 503s.
_FALLBACK = {
    "gemini-3.5-flash": ["gemini-2.5-flash", "gemini-3.1-flash-lite"],
    "gemini-3.1-flash-lite": ["gemini-2.5-flash-lite", "gemini-2.5-flash"],
}


class LLMClient:
    def __init__(self, api_key: str | None = None):
        key = api_key or os.getenv("GEMINI_API_KEY")
        if not key:
            raise LLMError(
                "GEMINI_API_KEY is not set. Put it in .env or Streamlit secrets."
            )
        self.client = genai.Client(api_key=key)

    def _model_name(self, tier: str) -> str:
        if tier == "pro":
            return JUDGE_MODEL
        return AGENT_MODEL

    def _call_with_fallback(
        self,
        primary_model: str,
        prompt: str,
        *,
        json_mode: bool,
    ) -> str:
        cfg = (
            types.GenerateContentConfig(response_mime_type="application/json")
            if json_mode
            else None
        )
        models_to_try = [primary_model] + _FALLBACK.get(primary_model, [])
        last_err: Exception | None = None
        for model_name in models_to_try:
            for attempt in range(2):
                try:
                    resp = self.client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=cfg,
                    )
                    return (resp.text or "").strip()
                except genai_errors.ServerError as e:
                    last_err = e
                    if attempt == 0:
                        time.sleep(1.5)
                        continue
                    break  # next model
                except genai_errors.ClientError as e:
                    last_err = e
                    # quota / 429 — try next model immediately
                    break
                except Exception as e:
                    last_err = e
                    break
        raise LLMError(f"All Gemini fallbacks failed. Last error: {last_err}")

    def generate_json(self, prompt: str, tier: str = "flash") -> dict[str, Any]:
        text = self._call_with_fallback(self._model_name(tier), prompt, json_mode=True)
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            return {"_parse_error": str(e), "_raw_text": text}

    def generate_text(self, prompt: str, tier: str = "flash") -> str:
        return self._call_with_fallback(self._model_name(tier), prompt, json_mode=False)
