"""Minimal OpenAI ping with the project's own config (proves key validity)."""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import backend.config as cfg  # noqa: E402

from openai import OpenAI  # noqa: E402

client = OpenAI(api_key=cfg.OPENAI_API_KEY, base_url=cfg.OPENAI_API_BASE or None)
print("base_url:", cfg.OPENAI_API_BASE or "(default openai)")
try:
    resp = client.chat.completions.create(
        model=cfg.CLEARTITLE_AGENT_MODEL,
        messages=[{"role": "user", "content": "Reply with the single word: ok"}],
        max_completion_tokens=5,
    )
    print("PING OK:", resp.choices[0].message.content)
except Exception as exc:
    print("PING FAILED:", str(exc)[:400])
