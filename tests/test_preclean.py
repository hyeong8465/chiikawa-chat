from scripts.preclean import preclean

ENDING = ["잡기 다", "됐어 그렇게 서두를 거", "있잖아 오늘 저녁도 우리 같이",
          "뭐야 벌써", "아침이네 혼잣", "말해 구워진 빵에 버터", "발라발라 땅이 우를 잔뜩", "축축"]


def test_unescape_and_speaker_split():
    assert preclean(["&gt;&gt; 안녕", "&gt;&gt;", "뭐야"]) == [">>", "안녕", ">>", "뭐야"]


def test_tags():
    assert preclean(["[음악]", "안녕 [박수] 하치", "[울음]", "[웃음] 하하"]) == [
        "안녕 하치", "[울음]", "[웃음]", "하하"]


def test_non_hangul_dropped():
    assert preclean(["He.", "Eh", "개 m", "  "]) == ["개 m"]


def test_ending_removed():
    out = preclean(["안녕 하치", *ENDING])
    assert out == ["안녕 하치", *ENDING[:3]]


def test_ending_with_marker_and_long_prev():
    out = preclean(["안녕", "&gt;&gt; 뭐야", "아침이네 혼잣", "버터"])
    assert out == ["안녕"]
    out = preclean(["안녕", ">>", "뭐야 벌써", "아침이네 버터"])
    assert out == ["안녕"]


def test_midline_morning_kept():
    lines = ["오늘은 아침이 밝았네", "다음 이야기"]
    assert preclean(lines) == lines


def test_no_ending_unchanged():
    assert preclean(["[음악]", "안녕", "Eh", "잘 가"]) == ["안녕", "잘 가"]
