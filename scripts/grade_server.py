"""골든셋 채점 로컬 서버. 실행: uv run python scripts/grade_server.py → http://127.0.0.1:8766"""
import csv
import io
import json
import os
import re
import shutil
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RESPONSES = ROOT / "eval/golden/responses.yaml"
LABELS = ROOT / "eval/golden/labels.csv"
CHECKLIST = ROOT / "eval/prompts/judge_checklist.md"
HTML = Path(__file__).with_name("grade.html")
MAX_BODY = 1024 * 1024


def item_defs(path: Path) -> dict[str, str]:
    # "## 항목 정의"의 "- 이름: 설명" 줄
    return dict(re.findall(r"^- ([a-z_]+): (.+)$", path.read_text(encoding="utf-8"), re.M))


def load_labels(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def save_labels(path: Path, rows: list[dict]) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["id", "item", "pass"])  # csv 기본 줄끝(CRLF) = 기존 파일과 같음
    w.writeheader()
    w.writerows(rows)
    shutil.copy2(path, path.with_name(path.name + ".bak"))
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(buf.getvalue(), encoding="utf-8")
    os.replace(tmp, path)


def merge(rows: list[dict], marks: dict) -> list[dict]:
    # marks: {"g01|hachiware_like": "1" | "0" | ""}. 있는 칸만 바꾸고 순서 유지
    out = []
    for r in rows:
        v = marks.get(f"{r['id']}|{r['item']}", r["pass"])
        if v not in ("1", "0", ""):
            raise ValueError(v)
        out.append({**r, "pass": v})
    return out


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
        elif self.path == "/api/data":
            self._json({
                "responses": yaml.safe_load(RESPONSES.read_text(encoding="utf-8")),
                "labels": load_labels(LABELS),
                "defs": item_defs(CHECKLIST),
            })
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path != "/api/labels":
            return self._json({"error": "not found"}, 404)
        try:
            n = int(self.headers.get("Content-Length") or "")
            if not 0 <= n <= MAX_BODY:
                raise ValueError
            marks = json.loads(self.rfile.read(n))
            if not isinstance(marks, dict):
                raise ValueError
            rows = merge(load_labels(LABELS), marks)
        except ValueError:
            return self._json({"error": "bad request"}, 400)
        save_labels(LABELS, rows)
        self._json({"ok": True, "done": sum(r["pass"] != "" for r in rows), "total": len(rows)})


if __name__ == "__main__":
    print("http://127.0.0.1:8766")
    HTTPServer(("127.0.0.1", 8766), Handler).serve_forever()
