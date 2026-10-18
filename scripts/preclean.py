"""자막 기계적 전처리: data/raw/NNN.txt -> data/raw/pre/NNN.txt."""
import html
import re
from pathlib import Path

KEEP_TAGS = {"[울음]", "[웃음]"}
KEYWORDS = ("버터", "발라", "혼잣", "땅이")
TAG = re.compile(r"\[[^\]]*\]")
KEEP = re.compile(r"(\[울음\]|\[웃음\])")
HANGUL = re.compile("[가-힣]")


def _basic(lines: list[str]) -> list[str]:
    out = []
    for raw in lines:
        line = html.unescape(raw).strip()
        if line.startswith(">>"):
            out.append(">>")
            line = line[2:].strip()
        line = TAG.sub(lambda m: m[0] if m[0] in KEEP_TAGS else " ", line)
        for part in KEEP.split(line):
            part = " ".join(part.split())
            if part in KEEP_TAGS or HANGUL.search(part):
                out.append(part)
    return out


def _cut_ending(lines: list[str]) -> list[str]:
    for i in range(len(lines) - 1, -1, -1):
        if "아침이" in lines[i] and any(k in l for l in lines[i:] for k in KEYWORDS):
            start = i
            if i > 0:
                prev = lines[i - 1].removeprefix(">>").strip()
                if "뭐야" in prev and len(prev) <= 8:
                    start = i - 1
            if start > 0 and lines[start - 1] == ">>":
                start -= 1
            return lines[:start]
    return lines


def preclean(lines: list[str]) -> list[str]:
    return _cut_ending(_basic(lines))


def main() -> None:
    raw = Path("data/raw")
    out = raw / "pre"
    out.mkdir(exist_ok=True)
    files = sorted(raw.glob("[0-9][0-9][0-9].txt"))
    before = after = 0
    cut = []
    for f in files:
        src = f.read_text(encoding="utf-8").splitlines()
        res = preclean(src)
        before += len(src)
        after += len(res)
        if len(res) < len(_basic(src)):
            cut.append(f.stem)
        (out / f.name).write_text("\n".join(res) + "\n", encoding="utf-8")
    print(f"파일 {len(files)}개 / 전체 줄 {before} -> {after}")
    print(f"엔딩곡 제거 {len(cut)}개, 미제거 {len(files) - len(cut)}개")
    print("미제거:", " ".join(sorted(set(f.stem for f in files) - set(cut))))


if __name__ == "__main__":
    main()
