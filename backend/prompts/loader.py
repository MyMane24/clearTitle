"""Prompt file loader — reads .txt/.json files from this directory."""
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent


def load_prompt(name: str) -> str:
    """Load a prompt file by name (without extension). Returns the file content as a string."""
    path = _PROMPTS_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def load_schema(name: str) -> dict:
    """Load a JSON schema file by name (without extension). Returns parsed dict."""
    import json
    path = _PROMPTS_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Schema file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
