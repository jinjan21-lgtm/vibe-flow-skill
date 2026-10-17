---
name: vibe-record
description: Use when a task's work is done and handoff records must be written — after QA of a goal MR, when recording a decision (D-nnn) or lesson (L-nnn), when the user says "기록해", "결정 남겨", "인덱스 정리", or when vibe-flow reaches merge/record.
---

# vibe-record — 기록 · 인덱스 · 보관

규칙 원본: vibe-flow 폴더의 `docs/structure.md` 「인덱스 계층」. 핸드오프 스킬(team-handoff·session-handoff)의 형식을 그대로 쓴다. 스크립트 `S=<vibe-flow>/scripts`.

**기록은 작업과 같은 커밋이다.** 본문에 새 항목을 쓰면 그 INDEX 한 줄도 같은 커밋이다.

## 진입 조건

골 작업이면 「QA 결과」가 채워져 있다(`--stage merge`가 기록 말고 막는 것이 없다). 골 밖 기록(결정 정리 등)은 바로.

## 쓰는 것

| 무엇 | 본문 | 같은 커밋의 INDEX |
|---|---|---|
| 작업 기록 | `WORKLOG/<topic>.md` 항목(`@작성자`, 앵커 `-작성자`) | `WORKLOG/INDEX.md` 한 줄 |
| 남은 일 | REMAINING `[~]` → `[x] (@나 날짜)` | (REMAINING이 INDEX) |
| 결정 | `python $S/handoff.py next-id D` → 안내된 본문 파일 끝에 `## D-nnn` 블록 | `DECISIONS.md` 끝에 한 줄(`#화면 태그`, 뒤집으면 `대체 D-kkk`) |
| 교훈 | `next-id L` → `LESSONS-body.md` 끝 | `LESSONS.md` 한 줄 |

번호는 손으로 정하지 않는다 — `next-id`가 전 브랜치와 원격 예약을 본다. 원격 예약이 실패하면 번호를 받지 않고 사용자에게 알린다(`--scan-only`는 사용자가 직접).

## 순서

1. 위 표대로 쓴다. INDEX 줄은 고치지 않고 추가만.
2. 골 작업: 마지막 작업 커밋에 합친다 — `git commit --amend`(이미 push했으면 자기 브랜치에 `--force-with-lease`).
3. `python $S/handoff.py check-record` → `python $S/handoff.py lint`. lint가 빠진 INDEX 줄을 출력하면 그대로 붙인다.
4. 골 작업: `python $S/mr_check.py <mr> --stage merge` 통과 뒤 머지는 작성자가(사용자 요청 시). 머지 후 골 `done`은 base에서, main 직접 커밋이 금지면 `chore/G-###-done` PR로(골 파일 + goals/INDEX.md).
5. 크기는 직접 재지 않는다(`wc -c`는 바이트 — 임계값은 문자 수). lint·precheck·`archive --dry`가 임계값·완료 잔존을 알리면 **다음 작업 커밋에서 기록을 쓰기 전에** `handoff.py archive`(기록만 담은 커밋은 만들지 않는다. 기록 뒤에 돌리면 방금 쓴 `[x]`까지 옮겨진다).

## Red Flags

| 생각 | 실제 |
|---|---|
| "기록은 다음 커밋에" | `check-record`가 거부한다 |
| "마지막 번호가 D-106이니 D-107" | 다른 브랜치가 이미 썼을 수 있다. `next-id` |
| "INDEX는 나중에 한꺼번에" | 같은 커밋. lint가 잡는다 |
| "옛 결정 문구를 다듬자" | 본문은 이동만. 정리는 INDEX 상태로 |
