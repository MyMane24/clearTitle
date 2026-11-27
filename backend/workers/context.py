"""StageContext — the identity and state a stage receives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class StageContext:
    case_id: str
    doc_id: str
    state: Any = None  # persistence (repos)


__all__ = ["StageContext"]
