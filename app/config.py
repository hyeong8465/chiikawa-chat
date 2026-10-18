import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHARACTER_DIR = ROOT / "character"

# 값은 작업 1에서 채움
MODELS = {"sonnet": "", "haiku": "", "judge": "", "judge_strong": ""}
CHAT_MODEL = os.getenv("CHAT_MODEL", MODELS["haiku"])
SUGGEST_MODEL = os.getenv("SUGGEST_MODEL", MODELS["haiku"])
JUDGE_MODEL = os.getenv("JUDGE_MODEL", MODELS["judge"])
PROVIDER = {"order": ["anthropic"], "allow_fallbacks": False}

MAX_MESSAGES = 200
MAX_INPUT_CHARS = 1000
RATE_PER_MIN = 10
RATE_PER_DAY = 40


def _prompt_version() -> str:
    sha = os.getenv("VERCEL_GIT_COMMIT_SHA", "")[:7]
    if sha:
        return sha
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
        return out or "local"
    except Exception:
        return "local"


PROMPT_VERSION = _prompt_version()
