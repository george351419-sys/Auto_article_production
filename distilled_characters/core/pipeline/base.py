"""Abstract base class for distillation pipeline steps.

Each step is an independent module with a standard contract:
    input_schema → build_prompt() → llm.send_prompt() → parse_response() → output_schema

This design makes every step reusable outside the full pipeline.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Type

from pydantic import BaseModel

from core.llm.base import AbstractLLMBackend


class BaseDistillationStep(ABC):
    """Standard contract for a single distillation step."""

    name: str
    label: str
    description: str = ""

    @abstractmethod
    def build_prompt(self, context: dict[str, Any]) -> tuple[str, str]:
        """Build (system_message, user_prompt) from context.

        Args:
            context: Accumulated data from character, materials, and prior steps.

        Returns:
            Tuple of (system_message, user_prompt).
        """
        ...

    @abstractmethod
    def parse_response(self, llm_output: str) -> dict[str, Any]:
        """Parse LLM output into a structured dict.

        Default implementation tries JSON extraction.
        Override for custom parsing.
        """
        ...

    async def execute(
        self, llm: AbstractLLMBackend, context: dict[str, Any]
    ) -> dict[str, Any]:
        """Standard execution flow: build prompt → send → parse.

        Args:
            llm: The LLM backend to use.
            context: All available data (character, materials, prior step results).

        Returns:
            Parsed output dict conforming to this step's output schema.
        """
        system_msg, user_msg = self.build_prompt(context)
        raw = await llm.send_prompt(user_msg, system_message=system_msg)
        return self.parse_response(raw)

    @staticmethod
    def _extract_json(text: str) -> str:
        """Extract JSON from LLM output that may have markdown fences."""
        text = text.strip()
        if "```json" in text:
            text = text.split("```json", 1)[1]
            text = text.split("```", 1)[0]
        elif "```" in text:
            parts = text.split("```")
            # Try to find the JSON block between first pair of ```
            if len(parts) >= 3:
                text = parts[1]
        return text.strip()

    @staticmethod
    def _safe_json_parse(text: str) -> dict[str, Any]:
        """Parse JSON safely, returning empty dict on failure."""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to repair truncated JSON by finding last complete object/array end
            text = BaseDistillationStep._extract_json(text)
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {}
