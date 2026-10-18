"""화자 라벨링 로컬 서버. 실행: uv run python scripts/label_server.py"""
import json
import os
import shutil
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLEAN_DIR = ROOT / "data/raw/clean"
TITLES = ROOT / "data/raw/titles.json"
LABELS = ROOT / "data/raw/label/labels.json"
HTML = Path(__file__).with_name("label.html")
MAX_BODY = 5 * 1024 * 1024
DEFAULT_PERSONS = ["치이카와", "우사기", "하치와레"]


def build_items(clean_dir: Path, titles: dict[int, str]) -> list[dict]:
    items = []
    for f in sorted(clean_dir.glob("*.txt")):
        ep = int(f.stem)
        rows = []  # (파일 줄 번호, 화자, 텍스트) — 노래 줄 제외
        for idx, line in enumerate(f.read_text(encoding="utf-8").splitlines()):
            speaker, _, text = line.partition("\t")
            if "노래" not in speaker and text.strip():
                rows.append((idx, speaker, text.strip()))
        texts = [r[2] for r in rows]
        for pos, (idx, _, text) in enumerate(rows):
            if len(text) <= 3:
                continue
            items.append({
                "id": f"{f.stem}-{idx}", "episode": ep, "title": titles.get(ep, ""),
                "text": text, "before": texts[max(0, pos - 3):pos], "after": texts[pos + 1:pos + 3],
            })
    return items


def save_labels(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def load_labels(path: Path) -> dict:
    if not path.exists():
        return {"persons": list(DEFAULT_PERSONS), "items": {}}
    return json.loads(path.read_text(encoding="utf-8"))


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode())

    def do_GET(self):
        if self.path == "/":
            self._send(200, HTML.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/items":
            titles = {t["episode"]: t["subtitle"] for t in json.loads(TITLES.read_text(encoding="utf-8"))}
            self._json(build_items(CLEAN_DIR, titles))
        elif self.path == "/api/labels":
            self._json(load_labels(LABELS))
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path != "/api/labels":
            return self._json({"error": "not found"}, 404)
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            return self._json({"error": "content-type"}, 415)
        try:
            n = int(self.headers.get("Content-Length") or "")
            if n < 0:
                raise ValueError
        except ValueError:
            return self._json({"error": "bad length"}, 400)
        if n > MAX_BODY:
            return self._json({"error": "too large"}, 413)
        try:
            data = json.loads(self.rfile.read(n))
        except ValueError:
            return self._json({"error": "bad json"}, 400)
        if not (isinstance(data, dict) and isinstance(data.get("persons"), list)
                and isinstance(data.get("items"), dict)):
            return self._json({"error": "bad shape"}, 400)
        try:
            save_labels(LABELS, data)
        except Exception as e:
            return self._json({"error": f"save failed: {e}"}, 500)
        self._json({"ok": True})


if __name__ == "__main__":
    print("http://127.0.0.1:8765")
    HTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
