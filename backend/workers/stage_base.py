"""Extraction stage contract."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.workers.context import StageContext


class ExtractionStage:
    """Contract for extraction pipeline stages (preprocess → persist)."""

    name: str = "extraction"

    def invoke(self, ctx: StageContext) -> dict:
        raise NotImplementedError


__all__ = ["ExtractionStage", "StageContext"]
