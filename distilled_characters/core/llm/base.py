"""Abstract LLM backend — the pluggable interface for model providers."""
from __future__ import annotations

from abc import ABC, abstractmethod


class AbstractLLMBackend(ABC):
    """Every LLM backend must implement this interface.

    The system generates standardized prompts; the backend sends them.
    Users configure their own endpoints — we don't hardcode any provider.
    """

    @abstractmethod
    async def send_prompt(
        self,
        user_prompt: str,
        system_message: str = "",
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> str:
        """Send a prompt and return the raw text response."""
        ...

    @abstractmethod
    async def test_connection(self) -> bool:
        """Verify the backend is reachable and authenticated."""
        ...

    @property
    @abstractmethod
    def backend_type(self) -> str:
        """Return 'openai_compatible' | 'anthropic' | 'mock'."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier string."""
        ...
