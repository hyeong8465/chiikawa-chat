# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

하치와레(치이카와) 비공식 팬메이드 캐릭터 챗. AI 캐릭터 챗 프롬프트 엔지니어링 포트폴리오용. 구현 중(진행 상황: `docs/private/task.md`).

## 문서

| 문서 | 읽는 시점 |
|---|---|
| `docs/prd.md` | 목표, 기능 우선순위, MVP 범위 |
| `docs/architecture.md` | 앱 흐름, 캐싱, 자료 파이프라인, 폴더 구조 |
| `docs/prompt.md` | `character/`, `app/prompt.py` 작업 시 |
| `docs/eval.md` | `eval/` 작업 시 |
| `docs/prompt-map.md` | 기능·평가별로 들어가는 프롬프트. 프롬프트 파일이나 읽는 코드를 바꾸면 같이 고침 |
| `docs/rules.md` | 코드 작성 전 항상 |
| `docs/design.md` | 화면 작업 시 |
| `docs/private/task.md` | 다음 할 일(원본은 여기 하나, 7절). 완료 시 체크 |
| `docs/private/memory.md` | 과거 결정과 이유 |
| `docs/private/` | 비공개(gitignore). 있으면 읽되 내용을 공개 문서·코드·README로 옮기지 않음 |

## 원칙

- 목표(`docs/prd.md` "목표")는 고정. 나머지는 초안, 더 나은 안 있으면 비판적으로 제안
- 중요한 결정·버그·변경은 `docs/private/memory.md`에 기록
- 포트폴리오 본문은 공개 `README.md`. 결정 요약은 README에 따로 작성
- 애매하면 사용자에게 결정 요청
- 문서 문체: 간략한 개조식, 반말, 표·목록 위주, 영어 서술 금지

## 명령어

| 목적 | 명령 |
|---|---|
| 테스트 전체 | `uv run pytest -v` |
| 테스트 하나 | `uv run pytest tests/test_vtt.py::test_이름 -v` |
| 자막 수집(이어받기) | `uv run python scripts/fetch_subs.py` (한 화: `--only N`) |
| 자막 전처리 | `uv run python scripts/preclean.py` → `data/raw/pre/` |
| 화자 라벨링 도구 | `uv run python scripts/label_server.py` → http://127.0.0.1:8765, 결과 `data/raw/label/labels.json`. 근거 대사만: `--targets` |
| 골든셋 채점 도구 | `uv run python scripts/grade_server.py` → http://127.0.0.1:8766, 결과 `eval/golden/labels.csv`(누를 때마다 저장) |
| 말뭉치 통합 | `uv run python scripts/build_corpus.py` → `data/raw/corpus.jsonl` |
| 로컬 서버 | `uv run --env-file .env uvicorn app.main:app --reload` → http://127.0.0.1:8000 (실제 모델 호출. 앱은 `.env`를 직접 안 읽음. `--reload`는 `.py`만 감시 → `character/`·`app/prompts/`의 `.md` 고치면 서버 재시작) |
| 평가 실행 | `uv run --env-file .env python -m eval.run --label v1 --model haiku` (부분: `--only id1,id2`, 범주 빼기: `--exclude-category long`, 이어서: `--resume`) → `eval/results/<라벨>-<모델>.jsonl`. 같은 라벨 있으면 멈춤. 크레딧 사용 |
| 다시 채점 | `uv run --env-file .env python -m eval.run --rejudge eval/results/v1-haiku.jsonl` → 원본 두고 `.rejudge-<월일>.jsonl` 새 파일. 크레딧 사용 |
| 채점자 일치율 | `uv run --env-file .env python -m eval.agree --model judge` → 골든셋 사람 채점과 항목별 일치율. 크레딧 사용 |
| 평가 리포트 | `uv run python -m eval.report eval/results/v1-*.jsonl` (`--exclude-category long`, 단계별 캐시·절감: `--cache`, 두 결과 비교: `--compare 기준선 결과`) |
| CI 평가 | PR·main 머지 때 자동(`.github/workflows/eval-*.yml`). 기준선은 `eval-baseline` 브랜치. Secrets 4개 필요(`docs/eval.md`) |
| 캐싱 비용 검증 | `uv run --env-file .env python -m eval.cost_check --turns 10` → `eval/results/cost.json`. 크레딧 사용 |
| 미리보기 배포 | `vercel deploy` (운영은 작업 12부터 GitHub 연동) |
| 배포 확인 | `vercel curl /api/health --deployment <주소>` |

- Python 3.12(uv 고정), `yt-dlp`는 시스템 프로그램(의존성 아님)
- 브랜치 `<유형>/<작업번호>-<설명>`, `main` 병합은 스쿼시
