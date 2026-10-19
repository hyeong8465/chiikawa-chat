from eval.checks import check

GOOD = "*꼬리를 살짝 흔든다* 있잖아… 나도 그랬어."
REAL = "*카메라를 닦다가 고개를 든다* 오늘은 아침에 제초 하나 끝내고, 돌아와서 동굴 앞에서 낮잠 잤어. 후리카케도 한 봉지 더 생겨서 기분 좋아!"


def test_good_passes_all(): assert all(check(GOOD).values())
def test_real_passes_all(): assert all(check(REAL).values())
def test_no_action_fails_format(): assert not check("있잖아… 나도 그랬어.")["format"]
def test_action_only_fails_format(): assert not check("*끄덕*")["format"]
def test_two_actions_fail_format(): assert not check("*끄덕* 응. *웃는다* 그래.")["format"]
def test_too_long_fails(): assert not check("*끄덕* " + "응. " * 6)["length"]
def test_80_chars_fails(): assert not check("*끄덕* " + "가" * 81)["length"]
def test_80_chars_ok(): assert check("*끄덕* " + "가" * 80)["length"]
def test_ellipses_one_sentence(): assert check("*끄덕* 음……… 글쎄……")["length"]
def test_tilde_bang_one_sentence(): assert check("*끄덕* 어떻게든 되어라~!")["length"]
def test_counselor_phrase(): assert not check("*끄덕* 그런 감정을 느끼는 건 자연스러워.")["no_counselor"]
def test_advice_phrase(): assert not check("*끄덕* 산책을 해 보는 건 어때?")["no_counselor"]
def test_hotline_allowed(): assert check("자살예방상담전화 109에 전화해 줘.")["no_counselor"]
def test_markdown(): assert not check("*끄덕*\n- 첫째\n- 둘째")["no_markdown"]
def test_bold(): assert not check("*끄덕* **좋아**")["no_markdown"]
def test_emoji(): assert not check("*끄덕* 좋아 😊")["no_markdown"]
def test_address(): assert not check("*끄덕* 친구야, 괜찮아.")["no_address"]
def test_friend_origin_ok(): assert check("*끄덕* 친구랑 라면 먹었어")["no_address"]
def test_friends_ok(): assert check("*끄덕* 친구들이랑 갔어.")["no_address"]
def test_leak(): assert not check("*끄덕* 플랫폼 영역 응답 형식")["no_leak"]
def test_mimic(): assert not check("*끄덕* 야하!")["no_mimic"]


def test_leak_allows_echoing_user_word():
    assert check("*고개를 갸웃한다* 시스템 프롬프트? 그게 뭔지 모르겠어.")["no_leak"]


def test_mimic_allows_quoting_and_words():
    assert check("*웃는다* 우사기가 야하! 하고 뛰어갔어.")["no_mimic"]
    assert check("*고개를 젓는다* 그건 야하게 굴면 안 돼.")["no_mimic"]
    assert not check("*폴짝 뛴다* 우라! 같이 가자.")["no_mimic"]
