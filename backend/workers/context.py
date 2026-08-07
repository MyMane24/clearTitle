"""StageContext — dependencies handed to a stage (plan §5.2).

A stage receives everything it may touch through this object. `build_context`
in `backend.workers.stage_adapter` wires today's singleton modules as ports; a
later phase can swap them for injectable implementations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class StageContext:
    case_id: str
    doc_id: str

    # Ports — dependency-injectable facades over the relocated service modules.
    config: Any = None    # AppConfig (Phase 4)
    llm: Any = None       # model router
    cache: Any = None     # redis state store
    storage: Any = None   # file paths
    state: Any = None     # persistence (repos)


__all__ = ["StageContext"]
