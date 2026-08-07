"""Extraction stage contract.

An `ExtractionStage` receives a `StageContext` and its input data through
`invoke` — it never reaches for globals or module-level clients.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.workers.context import StageContext


@dataclass
class StageResult:
    """Canonical result shape produced by `Stage.invoke`."""

    status: str
    payload: dict = field(default_factory=dict)


class ExtractionStage:
    """Contract for extraction pipeline stages (preprocess → persist)."""

    name: str = "extraction"

    def invoke(self, ctx: StageContext, input_data: dict) -> dict:
        raise NotImplementedError


__all__ = ["ExtractionStage", "StageContext", "StageResult"]
