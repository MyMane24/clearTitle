"""The title verification agent (Phase B)."""

import os

# Pydantic AI prints a promotional banner on a process's first agent run; keep
# it out of the worker log.
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")
