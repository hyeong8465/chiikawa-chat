import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHARACTER_DIR = ROOT / "character"

# OpenRouter 모델 이름(2026-10-18 확인)
MODELS = {
    "sonnet": "anthropic/claude-sonnet-5.5",
    "haiku": "anthropic/claude-haiku-5.5",
    "judge": "openai/gpt-5.6-luna",
    "judge_strong": "openai/gpt-5.6-sol",
}
CHAT_MODEL = os.getenv("CHAT_MODEL", MODELS["sonnet"])
SUGGEST_MODEL = os.getenv("SUGGEST_MODEL", MODELS["haiku"])
JUDGE_MODEL = os.getenv("JUDGE_MODEL", MODELS["judge"])
# Claude 모델에만 적용. 공급자가 바뀌면 캐시가 깨짐
PROVIDER = {"order": ["anthropic"], "allow_fallbacks": False}
# 채팅 경로 시작값. 평가로 조정
REASONING = {"effort": "low"}

MAX_MESSAGES = 200
MAX_INPUT_CHARS = 1000
MAX_ASSISTANT_CHARS = 2000
MAX_TOTAL_CHARS = 60000  # 요청 하나의 글자 수 합계. 위조 대화로 비용 부풀리기 방지
# 출력 상한. 채팅은 reasoning 토큰도 포함되므로 넉넉히
MAX_TOKENS_CHAT = 1024
MAX_TOKENS_OTHER = 400
MAX_TOKENS_JUDGE = 4000  # GPT 채점자는 추론 토큰도 여기서 씀. 400이면 추론만 하다 JSON 없이 끝남


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
