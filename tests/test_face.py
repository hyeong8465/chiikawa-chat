"""화면 표정 규칙(app.js face) 확인. node 없으면 건너뜀"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

CASES = {
    "고개를 갸웃한다": "hesitate",  # '갸웃'의 '웃'이 기쁨에 걸리던 버그
    "고개를 갸웃거리며 웃는다": "joy",
    "눈을 반짝인다": "joy",
    "귀가 축 처진다": "sad",
    "옆에 살짝 앉는다": "base",
    "귀를 쫑긋 세운다": "excite",
    "": "sad",
}


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_face_rules():
    src = (Path(__file__).parent.parent / "app/static/app.js").read_text(encoding="utf-8")
    block = src[src.index("const FACES"):src.index("function el(")]
    js = f"{block}\nconsole.log(JSON.stringify({json.dumps(list(CASES), ensure_ascii=False)}.map(face)))"
    out = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout
    assert dict(zip(CASES, json.loads(out))) == CASES
