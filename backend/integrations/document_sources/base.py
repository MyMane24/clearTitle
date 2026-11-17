"""The document source interface.

A requisition says *what* document is needed. A source obtains it. Every
obtained file then goes through the normal document pipeline, so adding a
source (e.g. a government portal) changes nothing in the verification agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ObtainedFile:
    """A file a source saved into the case's raw upload folder."""

    original_name: str
    path: Path


class DocumentSource(Protocol):
    name: str

    def can_fulfil(self, requisition: dict) -> bool:
        """True when this source can obtain the requisitioned document."""
        ...

    async def obtain(self, case_id: str, requisition: dict, dest_dir: Path) -> list[ObtainedFile]:
        """Save the document's file(s) into ``dest_dir`` and describe them."""
        ...
