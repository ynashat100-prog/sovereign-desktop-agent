"""Provider contracts keep routing independent from model vendors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.models.schemas import ProviderStatus


@dataclass(frozen=True)
class Generation:
    text: str
    model: str
    provider: str
    local: bool


class ModelProvider(ABC):
    id: str
    name: str

    @abstractmethod
    async def status(self) -> ProviderStatus:
        raise NotImplementedError

    @abstractmethod
    async def generate(self, prompt: str, *, system: str = "") -> Generation:
        raise NotImplementedError
