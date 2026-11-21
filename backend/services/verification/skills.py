"""Lawyer playbooks for the verification agent.

The lead playbook is ``backend/skills/verification/skill.md``; each topic
playbook is ``backend/skills/verification/<name>/skill.md``. All of them go into
the Lead's fixed instructions, which stay identical across calls so the
provider's prompt cache keeps them cheap. Adding or editing a playbook is a file
change; no code changes.
"""

from __future__ import annotations

from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills" / "verification"


def all_playbooks(skills_dir: Path = SKILLS_DIR) -> str:
    """The lead playbook followed by every topic playbook, in name order."""
    parts = []
    lead = skills_dir / "skill.md"
    if lead.is_file():
        parts.append(lead.read_text(encoding="utf-8").strip())
    for path in sorted(skills_dir.glob("*/skill.md")):
        parts.append(path.read_text(encoding="utf-8").strip())
    return "\n\n---\n\n".join(parts)
