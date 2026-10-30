import pytest

from app.prompt import build_messages, fill, load_character, speech_rules

CARDS = """
- arc: 제초 검정
  episodes: "57~63"
  summary: 통과 요약
  hachiware: 담담함
  emotion: 긴장
  relatable_worries: [시험 낙방]
  unknown: [남은 질문]
  sources: [자막 61화]
  reviewed: true
- arc: 미검수 주제
  episodes: "1~2"
  summary: 제외될 요약
  hachiware: x
  emotion: y
  relatable_worries: []
  sources: [나무위키]
  reviewed: false
"""


@pytest.fixture
def cdir(tmp_path):
    files = {
        "platform.md": "PLATFORM",
        "character.md": "CHARACTER\n\n## 말투\n어미 규칙\n\n## 관계\n관계 내용\n",
        "chat_guide.md": "GUIDE",
        "examples.md": "EXAMPLES",
        "intro.md": "INTRO",
        "episodes.yaml": CARDS,
    }
    for k, v in files.items():
        (tmp_path / k).write_text(v, encoding="utf-8")
    return tmp_path


HIST = [{"role": "user", "content": "안녕"}]


def sys_text(msgs):
    return "\n".join(p["text"] for p in msgs[0]["content"])


def marked(msgs):
    return [
        (i, j)
        for i, m in enumerate(msgs)
        for j, p in enumerate(m["content"])
        if "cache_control" in p
    ]


def test_order(cdir):
    t = sys_text(build_messages(HIST, load_character(cdir)))
    order = ["PLATFORM", "CHARACTER", "GUIDE", "EXAMPLES", "INTRO", "제초 검정"]
    pos = [t.index(x) for x in order]
    assert pos == sorted(pos)


def test_cache_full(cdir):
    m = build_messages(HIST, load_character(cdir), cache="full")
    last = len(m[0]["content"]) - 1
    assert marked(m) == [(0, last), (len(m) - 1, len(m[-1]["content"]) - 1)]
    assert m[0]["content"][last]["cache_control"] == {"type": "ephemeral"}


def test_cache_none(cdir):
    assert marked(build_messages(HIST, load_character(cdir), cache="none")) == []


def test_cache_system(cdir):
    m = build_messages(HIST, load_character(cdir), cache="system")
    assert marked(m) == [(0, len(m[0]["content"]) - 1)]


def test_leading_intro_dropped(cdir):
    h = [{"role": "assistant", "content": "화면 인사"}] + HIST
    m = build_messages(h, load_character(cdir))
    assert m[1]["role"] == "user"
    assert len(m) == 2
    assert "INTRO" in sys_text(m)
    assert "화면 인사" not in sys_text(m)


def test_deterministic(cdir):
    c = load_character(cdir)
    assert build_messages(HIST, c)[0] == build_messages(HIST + HIST, c)[0]


def test_reviewed_filter(cdir):
    c = load_character(cdir)
    assert "제초 검정" in c.episodes and "통과 요약" in c.episodes
    assert "미검수" not in c.episodes and "제외될 요약" not in c.episodes
    assert "reviewed" not in c.episodes and "sources" not in c.episodes
    assert "남은 질문" not in c.episodes


def test_no_knowledge(cdir):
    (cdir / "episodes.yaml").write_text(CARDS.replace("reviewed: true", "reviewed: false"))
    c = load_character(cdir)
    assert c.episodes == ""
    n = len(build_messages(HIST, c)[0]["content"])
    (cdir / "episodes.yaml").unlink()
    c2 = load_character(cdir)
    assert c2.episodes == ""
    assert len(build_messages(HIST, c2)[0]["content"]) == n
    assert "제초" not in sys_text(build_messages(HIST, c2))


def test_speech_rules(cdir):
    assert speech_rules(load_character(cdir)).strip().endswith("어미 규칙")
    assert "관계 내용" not in speech_rules(load_character(cdir))


def test_speech_rules_drops_chat_only():
    rules = speech_rules(load_character())
    assert "짧게 말한다" in rules and "위로는" not in rules and "원작 대사는" not in rules and "머뭇거리거나" not in rules
    assert "말을 꺼낸다" not in rules


def test_speech_rules_missing(cdir):
    (cdir / "character.md").write_text("CHARACTER")
    assert speech_rules(load_character(cdir)) == ""


def test_fill_does_not_refill_values():
    # 응답에 자리표시 글자가 있어도 다시 안 바뀜
    assert fill("{response}\n{items}", response="글자 {items} 포함", items="A") == "글자 {items} 포함\nA"
