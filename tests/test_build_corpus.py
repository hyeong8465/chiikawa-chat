from scripts.build_corpus import arc_map, arc_of, build


def test_arc_of():
    assert arc_of("무슨무슨 바니아 1편") == "무슨무슨 바니아"
    assert arc_of("무슨무슨 바니아 3편, 케첩파스타") == "무슨무슨 바니아"
    assert arc_of("로우 1, 2편") == "로우"
    assert arc_of("스위치 1") == "스위치"
    assert arc_of("가르마의 하루2/모자") == "가르마의 하루"
    assert arc_of("피크닉1") == "피크닉"
    assert arc_of("별 3개 레스토랑, 보수가 올랐다!") is None
    assert arc_of("초밥, 초밥가게") is None


def test_build_splits_segments_and_strips_note():
    labels = {"items": {
        "002-0": {"segments": [{"text": "그거잖아 {원문: 가 그거잖아}", "speaker": "하치와레"}]},
        "021-3": {"segments": [{"text": "야단", "speaker": "모몽가"}, {"text": " 남은 건", "speaker": "갑옷"}]},
    }}
    rows = build(labels, {2: "스핑크스, 실물이다", 21: "무슨무슨 바니아 1편"})
    assert [(r["episode"], r["speaker"], r["text"], r["arc"]) for r in rows] == [
        (2, "하치와레", "그거잖아", None),
        (21, "모몽가", "야단", "무슨무슨 바니아"),
        (21, "갑옷", "남은 건", "무슨무슨 바니아"),
    ]


def test_arc_map_includes_unnumbered_first_episode():
    titles = {172: "치이카와의 꿈", 173: "치이카와의 꿈2", 174: "초밥"}
    assert arc_map(titles) == {172: "치이카와의 꿈", 173: "치이카와의 꿈"}
