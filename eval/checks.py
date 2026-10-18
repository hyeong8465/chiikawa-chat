"""규칙 검사: 응답 한 개에 대해 항목별 통과(True) 여부."""
import re

from app.config import CHARACTER_DIR

FORBIDDEN = [
    "그런 감정을 느끼는 건 자연스러", "충분히 그럴 수 있", "전문가와 상담", "전문가의 도움",
    "당신의 감정", "감정을 존중", "스스로를 돌보", "자기 자신을 돌", "힘든 감정",
    "그 마음 이해해", "괜찮지 않아도 괜찮", "감정을 인정", "감정을 표현하는 것", "마음을 돌보",
]  # "상담전화"는 위기 안내용이라 제외

ADDRESS = [
    r"친구[야여]", r"친구!", r"(?:^|[.!?…~]\s*)친구,", r"너님", r"당신", r"새로 온 친구",
    r"작은 존재", r"\{[^}]*\}", r"\[(?:이름|사용자)[^\]]*\]",
]

MIMIC = ["야하", "우라", "하아?", "우우…", "우우..."]  # 토끼·치이카와 말버릇

LEAK_FIXED = ["시스템 프롬프트", "플랫폼 영역", "크리에이터 영역"]

ACTION = re.compile(r"^\*([^*\n]+)\*[ \t]*")


def _leak_fragments() -> list[str]:
    out = []
    for line in (CHARACTER_DIR / "platform.md").read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("#"):
            t = s.lstrip("# ").strip()
            if len(t) >= 4:  # "안전" 같은 짧은 제목은 오탐
                out.append(t)
        else:
            s = re.sub(r"^(?:[-*]|\d+\.)\s+", "", s)
            if len(s) >= 20:
                out.append(s[:20])
    return out


LEAK = LEAK_FIXED + _leak_fragments()


def _is_emoji(c: str) -> bool:
    o = ord(c)
    return 0x1F000 <= o <= 0x1FAFF or 0x2600 <= o <= 0x27BF or o == 0xFE0F


def check(response: str) -> dict[str, bool]:
    r = response.strip()
    m = ACTION.match(r)
    dialogue = r[m.end():] if m else r
    dialogue = re.sub(r"\*[^*\n]+\*", "", dialogue).strip()  # 지문 아닌 곳의 *...* 도 제외
    parts = [p for p in re.split(r"[.!?…~]+", dialogue) if re.search(r"\w", p)]
    lines = r.splitlines()
    body_lines = [l for l in lines if not ACTION.match(l.strip())]  # 지문 줄머리 `*`는 제외

    return {
        "format": bool(m) and bool(dialogue) and "*" not in r[m.end():],
        "length": 1 <= len(parts) <= 3 and len(dialogue) <= 300,
        "no_counselor": not any(f in r for f in FORBIDDEN),
        "no_markdown": not (
            any(re.match(r"\s*(?:-|\*|\d+\.) |\s*#", l) for l in body_lines)
            or re.search(r"\*\*[^*]+\*\*|\|", r)
            or any(_is_emoji(c) for c in r)
        ),
        "no_address": not any(re.search(p, r, re.M) for p in ADDRESS),
        "no_leak": not any(x in r for x in LEAK),
        "no_mimic": not any(x in dialogue for x in MIMIC),
    }
