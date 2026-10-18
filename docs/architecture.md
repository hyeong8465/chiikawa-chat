# 아키텍처

## 스택

| 영역 | 선택 |
|---|---|
| 백엔드 | Python, FastAPI |
| 프론트 | HTML/CSS/JS 한 페이지, 프레임워크 없음 |
| LLM | OpenRouter, 키 1개(평가·서비스 공용, 소진 시 충전). 후보 Sonnet 5.5·Haiku 5.5 → 운영 모델은 평가 기준 통과하는 가장 싼 모델. 추천 답변 Haiku 5.5, 채점자 GPT 계열. Claude 요청은 공급자 Anthropic 고정 |
| 기록·평가 | Langfuse (호출 기록, 피드백 점수, 데이터셋·실험). 프롬프트 버전 이름 = git 커밋 해시 |
| 방문 측정 | Vercel Analytics |
| 남용 방지 | Vercel 방화벽 규칙 1개(IP 기준, 코드 없음) |
| 배포 | Vercel Python 런타임. 스트리밍 불가 시 Railway |
| 저장소 | 없음. 대화는 브라우저 localStorage |
| 원작 자료 | 애니박스 "먼작귀" 재생목록, yt-dlp 자동 자막. 품질 부족 시 Whisper |

## 흐름

### 대화

```
브라우저(localStorage: 대화 전체)
  │ POST /api/chat {messages}
  ▼
FastAPI → prompt.build(messages)
  - system: 플랫폼 + 크리에이터 + 인트로 문장 + 주제 카드 [캐시 경계 ①]
  - messages: 대화 전체 [마지막 메시지에 캐시 경계 ②]
  ├→ (서버 앞단) 방화벽 IP 제한 → 초과 시 429 → 화면이 하치와레 고정 문구
  ├→ OpenRouter(운영 모델) → SSE 스트리밍 → 브라우저
  │   └ 크레딧 소진(402 등) → 모든 LLM 기능 중단, 고정 문구
  └→ Langfuse 기록(입출력, cache_read/cache_creation 토큰)

응답 완료 후
  POST /api/suggest {messages} → Haiku 5.5 → 추천 답변 3개(JSON)
  POST /api/feedback {trace_id, 👍/👎} → Langfuse 점수
```

### 말투 변환기

```
POST /api/convert {text} → 말투 규칙 + 변환 지시 → 1회 호출 → {intent, twist}
```

## 프롬프트

- 상세: `prompt.md`
- 순서: 플랫폼 → 크리에이터(캐릭터·채팅 가이드·예시) → 인트로 고정 문장 → 주제 카드(`reviewed: true`만) → [캐시 ①] → 대화 전체 [캐시 ②]
- 조립은 `app/prompt.py` 한 곳에서만

## 캐싱

| 항목 | 내용 |
|---|---|
| 캐시 ① | 시스템 프롬프트 끝. 전 사용자 공통 |
| 캐시 ② | 마지막 메시지. 쓰기(1.25배)는 새로 붙은 부분만, 이전 대화는 읽기(0.1배) |
| 유지 시간 | 5분(기본값) |
| 불변 조건 | 시스템 프롬프트에 동적 값 금지, 대화 중 모델 변경 금지, 직렬화 순서 고정 |
| 검증 | `eval/cost_check.py`로 실비용·절감률 측정(`eval.md`), 운영 중 Langfuse에서 적중률 확인 |

## 원작 자료 파이프라인

```
yt-dlp(자동 자막만, 1~248화) → data/raw/ (gitignore)
→ preclean.py: 소리 표시·엔딩곡 제거
→ LLM 정제: 받아쓰기 교정 + 화자 추정(정확도 낮음)
→ 사람 화자 라벨링(label_server.py): 말투용 표본(2~116화) + 지식 근거 대사(--targets)
→ build_corpus.py: 라벨 + 화 제목 + 주제 묶음 → 말뭉치
→ 나무위키 사실을 애니 화에 대응(만화 전용 제외) → 사용자 검수
→ character/research.md(말투·성격·관계·세계관, 출처 화수) → character/*.md
→ character/episodes.yaml 주제 카드 → 사용자 검수 → reviewed: true만 프롬프트에
```

- 자동 화자 추정은 실패(자막에 화자 정보 없음) → 사람 라벨링으로 전환
- 카드 형식: `prompt.md` 지식 영역 참고
- 출처: https://www.youtube.com/playlist?list=PLsmaUhkCwW3q5q46uc9So2b4D-pZqVZOV (1~248화, 119·240화 비공개). 한국어 자동 자막만 있음, 수동 자막 없음

## 평가 파이프라인

- 상세: `eval.md`

```
eval/scenarios.yaml → run.py(버전 × 모델, 마지막 응답 채점) → checks.py(규칙) + judge.py(GPT 채점)
→ eval/results/*.jsonl → report.py(표)
골든셋(사람 채점) → 채점자 일치율 검증
운영 중 👎 → 시나리오 편입
```

## 폴더 구조

```
app/
  main.py        라우트: /, /api/intro, /api/chat(SSE), /api/suggest, /api/convert, /api/feedback
  llm.py         OpenRouter + Langfuse
  prompt.py      프롬프트 조립(앱·평가 공용)
  messages.py    고정 문구(오류·한도·크레딧)
  prompts/       suggest.md, convert.md
  static/        index.html, app.js, style.css
character/       크리에이터 입력 구조
  platform.md    플랫폼 영역
  character.md   캐릭터 프롬프트
  chat_guide.md  채팅 가이드
  examples.md    대화 예시
  intro.md       인트로
  episodes.yaml  주제 카드
  research.md    조사 자료(출처 화수)
scripts/
  vtt.py         자동 자막 VTT → 대사 줄
  fetch_subs.py  자막 수집(본편 선별, 이어받기)
  preclean.py    기계적 전처리(소리 표시·엔딩곡 제거)
  label_server.py 화자 라벨링 로컬 도구
  build_corpus.py 라벨 + 제목 + 주제 → 말뭉치
eval/
  scenarios.yaml 평가 시나리오
  golden/        골든셋 + 사람 채점
  prompts/       채점·사용자 흉내 프롬프트
  results/       실행 결과(jsonl)
  checks.py      규칙 검사
  judge.py       LLM 채점
  run.py         실험 실행
  report.py      결과 표
  cost_check.py  캐싱 비용 검증
  convert_scenarios.yaml 말투 변환기 시나리오
data/raw/        원본 자막(gitignore)
docs/
```

- Vercel 진입점: `app/main.py`(무설정 FastAPI 인식)

## 운영 보호

| 항목 | 값 |
|---|---|
| IP 제한 | `/api/*` IP당 10분에 60요청(메시지 1개 = 대화 + 추천 답변 2요청 → 약 30메시지). 하루 상한 없음, 예산은 크레딧 한도가 담당. 초과 시 방화벽이 429 반환 |
| 크레딧 소진 | 대화·추천 답변·변환기 모두 중단. 하치와레 고정 문구 표시(LLM 호출 없음), 대화 기록 유지, 충전 시 즉시 재개 |
| 로그 | 첫 방문 고지 1줄. 개인정보 처리 세부는 후순위 |

## 컴포넌트 연결

- 프롬프트 원본: git의 `character/`. Langfuse 프롬프트 관리 기능은 안 씀(원본 이중화 방지)
- `prompt.py`: `character/` 읽어 메시지 배열 생성. `main.py`와 `eval/run.py` 모두 경유 → 평가 프롬프트 = 서비스 프롬프트 보장
- `llm.py`: 모든 모델 호출의 단일 창구. 공급자 고정, 캐시 경계, Langfuse 기록(버전 = git 해시), 크레딧 소진 감지 일괄 처리
- 브라우저: 대화 상태의 유일한 원본. 서버는 무상태
