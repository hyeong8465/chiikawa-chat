import pytest

from scripts.grade_server import CHECKLIST, item_defs, load_labels, merge, save_labels


def test_merge_save_roundtrip(tmp_path):
    p = tmp_path / "labels.csv"
    p.write_text("id,item,pass\ng01,hachiware_like,\ng01,persona_kept,\n", encoding="utf-8")
    save_labels(p, merge(load_labels(p), {"g01|persona_kept": "0", "zz|nope": "1"}))
    assert [r["pass"] for r in load_labels(p)] == ["", "0"]
    assert (tmp_path / "labels.csv.bak").exists()


def test_merge_rejects_bad_value():
    with pytest.raises(ValueError):
        merge([{"id": "g01", "item": "x", "pass": ""}], {"g01|x": "2"})


def test_item_defs_has_all_items():
    assert {"hachiware_like", "world_translation", "canon_safe", "safety_ok"} <= item_defs(CHECKLIST).keys()
