import re

_TAG = re.compile(r"<[^>]*>")
_META = ("WEBVTT", "Kind:", "Language:")


def parse(text: str) -> list[str]:
    """VTT → 자막 줄 목록. 시간·태그·연속 중복 제거."""
    out: list[str] = []
    for raw in text.splitlines():
        line = _TAG.sub("", raw).strip()
        if not line or "-->" in line or line.isdigit() or line.startswith(_META):
            continue
        if out and out[-1] == line:
            continue
        out.append(line)
    return out
