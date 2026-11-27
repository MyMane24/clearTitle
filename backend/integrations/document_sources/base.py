"""The document source interface.

A requisition says *what* document is needed. A source obtains it. Every
obtained file then goes through the normal document pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ObtainedFile:
    """A file a source saved into the case's raw upload folder."""

    original_name: str
    path: Path
