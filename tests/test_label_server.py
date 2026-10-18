import json
from pathlib import Path

from scripts.label_server import build_items, load_labels, save_labels


def _write(d: Path, name: str, lines: list[str]) -> None:
    (d / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_build_items(tmp_path):
    _write(tmp_path, "002.txt", [
        "치이카와\t첫번째 대사입니다",
        "우사기\t둘째 대사입니다",
        "노래\t노래 가사입니다 라라",
        "하치와레\t네네",  # skipped (<=3) but context
        "하치와레\t넷째 대사입니다",
        "우사기\t다섯째 대사입니다",
        "우사기\t여섯째 대사입니다",
        "우사기\t일곱째 대사입니다",
    ])
    _write(tmp_path, "001.txt", ["치이카와\t한 에피소드 대사"])
    items = build_items(tmp_path, {1: "하나", 2: "둘"})
    assert [i["id"] for i in items] == ["001-0", "002-0", "002-1", "002-4", "002-5", "002-6", "002-7"]
    assert items[0]["title"] == "하나" and items[0]["episode"] == 1
    assert items[0]["before"] == [] and items[0]["after"] == []
    it = {i["id"]: i for i in items}["002-4"]
    assert it["text"] == "넷째 대사입니다"
    assert it["before"] == ["첫번째 대사입니다", "둘째 대사입니다", "네네"]
    assert it["after"] == ["다섯째 대사입니다", "여섯째 대사입니다"]
    it = {i["id"]: i for i in items}["002-5"]
    assert len(it["before"]) == 3 and it["before"][0] == "둘째 대사입니다"


def test_save_load_roundtrip(tmp_path):
    p = tmp_path / "sub" / "labels.json"
    data = {"persons": ["하치와레"], "items": {"002-0": {"segments": [{"text": "안녕", "speaker": "하치와레"}]}}}
    save_labels(p, data)
    assert json.loads(p.read_text(encoding="utf-8")) == data
    assert "안녕" in p.read_text(encoding="utf-8")
    assert load_labels(p) == data
    assert list(p.parent.iterdir()) == [p]


def test_load_default(tmp_path):
    assert load_labels(tmp_path / "x.json") == {"persons": ["치이카와", "우사기", "하치와레"], "items": {}}
