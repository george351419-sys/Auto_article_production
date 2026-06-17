"""Base DistillationPlugin class — the plugin contract."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PluginCapability:
    name: str
    description: str
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)


class DistillationPlugin(ABC):
    """Base class for all plugins that consume distillation output.

    Plugin authors: subclass this, set `name` and `description`,
    implement `get_capabilities()` and `execute()`.
    """

    name: str
    description: str = ""

    @abstractmethod
    def get_capabilities(self) -> list[PluginCapability]:
        """Return the list of capabilities this plugin provides."""
        ...

    @abstractmethod
    async def execute(
        self,
        capability: str,
        input_data: dict[str, Any],
        llm: Any,  # AbstractLLMBackend
    ) -> dict[str, Any]:
        """Execute a capability with the given data and LLM backend.

        Args:
            capability: The capability name to invoke.
            input_data: Arbitrary input data (e.g., distillation result).
            llm: An LLM backend instance for plugins that need AI.

        Returns:
            Arbitrary output dict.
        """
        ...
