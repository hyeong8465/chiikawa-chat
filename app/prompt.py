import re
from dataclasses import dataclass
from functools import cache as _memo
from pathlib import Path
from typing import Literal

import yaml

from app.config import CHARACTER_DIR

CACHE = {"type": "ephemeral"}
INTRO_LINE = "너는 이미 대화 시작 때 이렇게 첫 인사를 했다(화면에 보인 상태): "


@dataclass(frozen=True)
class Character:
    platform: str
    character: str
    chat_guide: str
    examples: str
    intro: str
    episodes: str


def _read(d: Path, name: str) -> str:
    return (d / name).read_text(encoding="utf-8").strip()


def _episodes(d: Path) -> str:
    f = d / "episodes.yaml"
    if not f.exists():
        return ""
    cards = yaml.safe_load(f.read_text(encoding="utf-8")) or []
    ok = [
        {k: v for k, v in c.items() if k not in ("reviewed", "sources")}
        for c in cards
        if c.get("reviewed") is True
    ]
    if not ok:
        return ""
    return yaml.safe_dump(ok, allow_unicode=True, sort_keys=False).strip()


def load_character(dir: Path = CHARACTER_DIR) -> Character:
    return Character(
        platform=_read(dir, "platform.md"),
        character=_read(dir, "character.md"),
        chat_guide=_read(dir, "chat_guide.md"),
        examples=_read(dir, "examples.md"),
        intro=_read(dir, "intro.md"),
        episodes=_episodes(dir),
    )


_default = _memo(load_character)


def _parts(content) -> list[dict]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [dict(p) for p in content]


def build_messages(
    history: list[dict],
    c: Character | None = None,
    cache: Literal["none", "system", "full"] = "full",
) -> list[dict]:
    c = c or _default()
    texts = [c.platform, c.character, c.chat_guide, c.examples, INTRO_LINE + c.intro]
    if c.episodes:
        texts.append(c.episodes)
    system = [{"type": "text", "text": t} for t in texts]

    i = 0
    while i < len(history) and history[i]["role"] == "assistant":
        i += 1
    msgs = [{**m, "content": _parts(m["content"])} for m in history[i:]]

    if cache != "none":
        system[-1]["cache_control"] = CACHE
    if cache == "full" and msgs:
        msgs[-1]["content"][-1]["cache_control"] = CACHE
    return [{"role": "system", "content": system}, *msgs]


def speech_rules(c: Character) -> str:
    m = re.search(r"^## 말투[^\n]*\n(.*?)(?=^## |\Z)", c.character, re.M | re.S)
    return m.group(1).strip() if m else ""
