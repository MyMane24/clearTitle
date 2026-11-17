"""Lawyer playbooks the verification agent loads on demand.

Each skill is ``backend/skills/verification/<name>/skill.md``. Its first
paragraph after the title is the one-line description shown in the skill index.
Adding a skill is adding a folder; no code changes.
"""

from __future__ import annotations

import re
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills" / "verification"
LEAD_PLAYBOOK = SKILLS_DIR / "skill.md"
_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def list_skills(skills_dir: Path = SKILLS_DIR) -> list[tuple[str, str]]:
    """``(name, description)`` for every skill, sorted by name."""
    skills = []
    for path in sorted(skills_dir.glob("*/skill.md")):
        skills.append((path.parent.name, _description(path.read_text(encoding="utf-8"))))
    return skills


def skill_index(skills_dir: Path = SKILLS_DIR) -> str:
    lines = [f"- {name}: {description}" for name, description in list_skills(skills_dir)]
    return "\n".join(lines) or "(no skills available)"


def load_skill(name: str, skills_dir: Path = SKILLS_DIR) -> str:
    """The playbook text for ``name``.

    Raises:
        KeyError: No such skill. The message lists the available ones.
    """
    path = skills_dir / name / "skill.md"
    if not _NAME.match(name) or not path.is_file():
        available = ", ".join(skill for skill, _ in list_skills(skills_dir)) or "none"
        raise KeyError(f"No skill named {name!r}. Available: {available}.")
    return path.read_text(encoding="utf-8")


def _description(text: str) -> str:
    for block in text.split("\n\n"):
        line = " ".join(block.split())
        if line and not line.startswith("#"):
            return line
    return "(no description)"
