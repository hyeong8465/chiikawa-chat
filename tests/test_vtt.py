from scripts.fetch_subs import select_episodes
from scripts.vtt import parse

SAMPLE = """WEBVTT

00:00:01.000 --> 00:00:02.000
<c>있잖아</c>

00:00:02.000 --> 00:00:03.000
있잖아
그거 해볼까
"""


def test_parse_strips_timing_tags_and_dupes():
    assert parse(SAMPLE) == ["있잖아", "그거 해볼까"]


def test_parse_drops_header_metadata_and_cue_numbers():
    text = "WEBVTT\nKind: captions\nLanguage: ko\n\n1\n00:00:01.000 --> 00:00:02.000\n안녕\n"
    assert parse(text) == ["안녕"]


def test_parse_strips_timestamp_tags():
    text = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n있<00:00:01.234><c>잖아</c>\n"
    assert parse(text) == ["있잖아"]


def test_parse_keeps_nonadjacent_repeats():
    text = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n응\n아니\n응\n"
    assert parse(text) == ["응", "아니", "응"]


def test_select_episodes():
    entries = [
        ("b", "[전편공개]먼작귀(먼가 작고 귀여운 녀석) 2화_가"),
        ("a", "[전편공개]먼작귀(먼가 작고 귀여운 녀석) 1화_나"),
        ("x", "『먼작귀』 화제의 곡! 혼잣말_1시간 ver."),
        ("y", "NA"),
        ("z", "먼가 작고 귀여운 녀석(먼작귀) 성우 인터뷰 공개!!"),
        ("d", "[전편공개]먼작귀(먼가 작고 귀여운 녀석) 1화_중복"),
    ]
    assert select_episodes(entries) == [
        (1, "a", entries[1][1]),
        (2, "b", entries[0][1]),
    ]
