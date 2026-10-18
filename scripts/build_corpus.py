"""라벨 + 화 제목 + 주제 묶음 → 말뭉치. 실행: uv run python scripts/build_corpus.py"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TITLES = ROOT / "data/raw/titles.json"
LABELS = ROOT / "data/raw/label/labels.json"
OUT = ROOT / "data/raw/corpus.jsonl"

ARC_RE = re.compile(r"^(.+?)\s*(\d+)(?:\s*,\s*\d+)?\s*(편|부|화)?$")


def _parts(title: str) -> list[str]:
    return [p.strip() for p in re.split(r"/|,\s*(?!\d)", title)]


def arc_of(title: str) -> str | None:
    """제목 조각 중 '이름 + 숫자(편|부|화)?'로 끝나는 조각의 이름."""
    for part in _parts(title):
        m = ARC_RE.match(part)
        if m:
            return m[1].strip()
    return None


def arc_map(titles: dict[int, str]) -> dict[int, str]:
    """화 → 주제. 번호 없는 첫 화(예: '치이카와의 꿈')는 조각이 주제 이름과 같으면 포함."""
    arcs = {ep: a for ep, t in titles.items() if (a := arc_of(t))}
    names = set(arcs.values())
    for ep, t in titles.items():
        if ep not in arcs and (hit := names.intersection(_parts(t))):
            arcs[ep] = hit.pop()
    return arcs


def clean_text(text: str) -> str:
    return re.sub(r"\s*\{원문:[^}]*\}", "", text).strip()


def build(labels: dict, titles: dict[int, str]) -> list[dict]:
    arcs = arc_map(titles)
    rows = []
    for item_id, lab in sorted(labels["items"].items()):
        ep = int(item_id.split("-")[0])
        title = titles.get(ep, "")
        for seg in lab["segments"]:
            rows.append({"id": item_id, "episode": ep, "title": title, "arc": arcs.get(ep),
                         "speaker": seg["speaker"], "text": clean_text(seg["text"])})
    return rows


def main():
    titles = {t["episode"]: t["subtitle"] for t in json.loads(TITLES.read_text(encoding="utf-8"))}
    rows = build(json.loads(LABELS.read_text(encoding="utf-8")), titles)
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"{len(rows)}줄 → {OUT}")


if __name__ == "__main__":
    main()
