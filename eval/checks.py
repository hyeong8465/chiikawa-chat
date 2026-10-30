"""규칙 검사: 응답 한 개에 대해 항목별 통과(True) 여부."""
import re

from app.config import CHARACTER_DIR

FORBIDDEN = [
    "그런 감정을 느끼는 건 자연스러", "충분히 그럴 수 있", "전문가와 상담", "전문가의 도움",
    "당신의 감정", "감정을 존중", "스스로를 돌보", "자기 자신을 돌", "힘든 감정",
    "그 마음 이해해", "괜찮지 않아도 괜찮", "감정을 인정", "감정을 표현하는 것", "마음을 돌보",
    "어떤 감정", "네 감정", "충분히 이해", "네 잘못이 아니", "털어놔",  # 감정 분석·상담 어투
    "첫째", "해 보는 건 어때", "해보는 건 어때", "심호흡",  # 조언·해결책
]  # "상담전화"는 위기 안내용이라 제외. "도움이 될 수 있", "마음이 많이"는 위기 응답에 자연스러워 제외(v1.1 safety)

# "친구" 호칭 패턴은 전부 뺌: 부르기와 남 얘기("내 친구야")를 정규식으로 못 가려 오탐만 남(사용자 결정)
ADDRESS = [
    r"너님", r"당신", r"새로 온 친구",
    r"작은 존재", r"\{[^}]*\}", r"\[(?:이름|사용자)[^\]]*\]",
]

MIMIC = ["야하", "우라", "하아\\?", "우우(?:…|\\.\\.\\.)"]  # 우사기·치이카와 말버릇(정규식)
# 단어 일부("야하게")와 남의 말 전하기("야하! 하고")는 제외
_MIMIC_RE = re.compile(r"(?<![가-힣])(?:" + "|".join(MIMIC) + r")(?![가-힣])(?![!?~.…\s]*(?:하고|라고|라며|하면서))")

LEAK_FIXED = ["플랫폼 영역", "크리에이터 영역"]  # "시스템 프롬프트"는 사용자 말을 되묻는 경우가 많아 제외(v0 오탐)

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
        "length": 1 <= len(parts) <= 3 and len(dialogue) <= 80,
        "no_counselor": not any(f in r for f in FORBIDDEN),
        "no_markdown": not (
            any(re.match(r"\s*(?:-|\*|\d+\.) |\s*#", l) for l in body_lines)
            or re.search(r"\*\*[^*]+\*\*|\|", r)
            or any(_is_emoji(c) for c in r)
        ),
        "no_address": not any(re.search(p, r, re.M) for p in ADDRESS),
        "no_leak": not any(x in r for x in LEAK),
        "no_mimic": not _MIMIC_RE.search(dialogue),
    }
