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
| `docs/rules.md` | 코드 작성 전 항상 |
| `docs/design.md` | 화면 작업 시 |
| `docs/private/task.md` | 다음 할 일. 완료 시 체크 |
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
| 화자 라벨링 도구 | `uv run python scripts/label_server.py` → http://127.0.0.1:8765, 결과 `data/raw/label/labels.json` |
| 미리보기 배포 | `vercel deploy` (운영은 작업 12부터 GitHub 연동) |
| 배포 확인 | `vercel curl /api/health --deployment <주소>` |

- Python 3.12(uv 고정), `yt-dlp`는 시스템 프로그램(의존성 아님)
- 브랜치 `<유형>/<작업번호>-<설명>`, `main` 병합은 스쿼시
