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
    data = {"persons": ["하치와레"], "items": {"002-0": {"segments": [{"text": "안녕", "speaker": "하치와레"}]}}, "edits": {}}
    save_labels(p, data)
    assert json.loads(p.read_text(encoding="utf-8")) == data
    assert "안녕" in p.read_text(encoding="utf-8")
    assert load_labels(p) == data
    assert list(p.parent.iterdir()) == [p]


def test_load_default(tmp_path):
    assert load_labels(tmp_path / "x.json") == {"persons": ["치이카와", "우사기", "하치와레"], "items": {}, "edits": {}}


# --- HTTP / 백업 ---
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer

import pytest

from scripts import label_server


@pytest.fixture
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(label_server, "LABELS", tmp_path / "label" / "labels.json")
    srv = HTTPServer(("127.0.0.1", 0), label_server.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", tmp_path / "label" / "labels.json"
    srv.shutdown()
    srv.server_close()


def _post(base, body, ctype="application/json"):
    headers = {"Content-Type": ctype} if ctype else {}
    req = urllib.request.Request(base + "/api/labels", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


GOOD = b'{"persons": ["a"], "items": {}}'


def test_post_ok(server):
    base, path = server
    assert _post(base, GOOD) == 200
    assert json.loads(path.read_text(encoding="utf-8"))["persons"] == ["a"]


def test_post_rejects_content_type(server):
    base, path = server
    assert _post(base, GOOD, "text/plain") == 415
    assert _post(base, GOOD, None) == 415
    assert not path.exists()


@pytest.mark.parametrize("body", [b"[]", b"not json", b'{"persons": "x", "items": {}}',
                                  b'{"persons": [], "items": []}', b'{"persons": []}'])
def test_post_rejects_bad_body(server, body):
    base, path = server
    assert _post(base, body) == 400
    assert not path.exists()


def test_post_bad_content_length(server):
    import socket
    base, _ = server
    port = int(base.rsplit(":", 1)[1])
    for cl in ("-5", "abc"):
        s = socket.create_connection(("127.0.0.1", port))
        s.sendall(f"POST /api/labels HTTP/1.0\r\nContent-Type: application/json\r\nContent-Length: {cl}\r\n\r\n".encode())
        assert s.recv(100).startswith(b"HTTP/1.0 400")
        s.close()


def test_save_keeps_bak(tmp_path):
    p = tmp_path / "labels.json"
    save_labels(p, {"persons": [], "items": {"a": 1}})
    assert not (tmp_path / "labels.json.bak").exists()
    save_labels(p, {"persons": [], "items": {"a": 2}})
    assert json.loads((tmp_path / "labels.json.bak").read_text(encoding="utf-8"))["items"] == {"a": 1}
    assert json.loads(p.read_text(encoding="utf-8"))["items"] == {"a": 2}


def test_post_edits(server):
    base, path = server
    body = '{"persons": [], "items": {}, "edits": {"002-0": "고친 대사"}}'.encode()
    assert _post(base, body) == 200
    assert json.loads(path.read_text(encoding="utf-8"))["edits"] == {"002-0": "고친 대사"}


@pytest.mark.parametrize("edits", ['[]', '{"a": 1}', '"x"'])
def test_post_bad_edits(server, edits):
    base, path = server
    assert _post(base, f'{{"persons": [], "items": {{}}, "edits": {edits}}}'.encode()) == 400
    assert not path.exists()


def test_load_old_file_without_edits(tmp_path):
    p = tmp_path / "l.json"
    p.write_text('{"persons": ["a"], "items": {}}', encoding="utf-8")
    assert load_labels(p)["edits"] == {}


def test_targets_filter(tmp_path, monkeypatch):
    import scripts.label_server as ls
    monkeypatch.setattr(ls, "ONLY", {"001-0"})
    (tmp_path / "001.txt").write_text("하치와레\t첫 번째 대사\n하치와레\t두 번째 대사\n", encoding="utf-8")
    items = ls.build_items(tmp_path, {})
    assert [i["id"] for i in items if i["id"] in ls.ONLY] == ["001-0"]
