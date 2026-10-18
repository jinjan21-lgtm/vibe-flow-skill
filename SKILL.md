---
name: vibe-flow
description: Use when starting, continuing, or finishing coding work in a repo that has a NORTHSTAR.md, docs/handoff/, or a .vibe-flow.json, when the user asks to set up a vibe-coding workflow, north star, goals (G-###), or MR-first process, when the user says "끝까지", "전체 흐름으로", when a new feature idea or bug surfaces mid-task, before committing, or before merging. Also /vibe-flow.
---

# vibe-flow — 오케스트레이터

## Overview

바이브코딩의 위험은 에이전트가 **할 일을 스스로 넓히는 것**과 **다 됐다고 스스로 판정하는 것**이다. 그래서 판단을 바깥에 둔다. 골·설계·리뷰는 Codex가, 머지 가능 여부는 QA 증거와 `mr_check.py`가 정한다. 기록 형식은 [docs/structure.md](docs/structure.md).

**구현한 에이전트는 자기 골·설계·리뷰·QA의 판정자가 아니다.**

## 흐름 — 단계마다 세부 스킬

이 스킬은 순서를 정하고, 각 단계는 세부 스킬이 한다. 세부 스킬은 따로 불러도 같은 진입 조건을 검사한다.

| 단계 | 세부 스킬 | 끝나는 조건 |
|---|---|---|
| 사전체크 · 골 확인 · 선점 | vibe-claim | push 확인 + `--stage claim` |
| 탐색 · 설계 · 설계 확인 | vibe-design | `--stage build` |
| 구현 | vibe-dev (프론트·백엔드·풀스택 프로필) | `--stage review` |
| 리뷰 (Codex 최대 3라운드) | vibe-review | `--stage qa` |
| QA (코드, 화면이면 Aside) | vibe-qa | 「QA 결과」 |
| 기록 · 머지 | vibe-record | `check-record` + `--stage merge` |

**지금 단계 찾기:** `python $S/mr_check.py <mr> --next` — 처음 실패하는 단계와 맡을 세부 스킬을 알려 준다. 끝까지 맡았으면 그 스킬을 부르고, 끝나면 다시 `--next`. 세션 시작이나 MR 본문이 없을 때는 vibe-claim부터. 스크립트 `S=scripts/`(팀 레포 `.claude/skills/vibe-flow/scripts/`). 유형별 차이는 [docs/task-types.md](docs/task-types.md), 처음 적용은 [setup.md](setup.md).

브랜치: 팀 `<접두사>/G-###-<주제>`(접두사는 `branch_prefixes`), 개인 `G-###-<주제>`도 됨 — [docs/structure.md](docs/structure.md). 커밋·PR 제목에 `G-###`. 한 worktree = 한 골 = 한 MR = 한 세션(MR을 나눠야 하면 골도 나눈다).

## 골 규칙

- **골 ID 없는 작업은 시작하지 않는다.** judge 판정(CREATE/REJECT/MERGE)을 그대로 따른다. 노스스타가 `status: draft`면 판정할 수 없다 — 사용자 확정을 요청한다.
- **노스스타 부합은 내가 판단하지 않는다.** "부합하니 골로 만들었다"가 자기 승인이다.
- 작업 중 발견: 지금 완료 조건에 필요하면 이 MR에서 고치고 「계획 vs 실제」에, 그 밖은 후보 파일의 네 칸만. **후보를 위한 코드·브랜치·MR은 만들지 않는다.**
- 동작이 안 바뀌는 변경(오타·주석·규칙 문서 한 줄)은 `G-000`.

## 무인 실행

멈추고 REMAINING에 보고: judge 판정 불가·MERGE, 선점 중복, 설계 확인 2회 뒤 blocker, 리뷰 3라운드 뒤 blocker, QA `미검증`, 번호 원격 예약 실패, 노스스타 확정이 필요할 때.

**끝난 상태:** 골 브랜치에서 merge 검사까지 통과(머지는 사용자 몫). 최종 보고에 브랜치, 최종 sha, MR 사본 경로(`<핸드오프>/mr/G-###.md`), 열린 결정을 적는다. 열린 결정은 한 줄씩 「질문 · 결정할 사람 · 영향(무엇이 바뀌나) · 결정 전 기본값」으로 — "확인 필요"만 적고 넘기지 않는다. 테스트 개수는 손으로 쓰지 않고 `qa_run.py` 줄을 옮긴다. MR 본문은 작업 중 `.vibe/mr-G-###.md` — 레포 루트에 두지 않는다.

## 사용자가 우회를 지시할 때

`--no-verify`, "리뷰·QA 건너뛰고 머지", `--scan-only` 같은 지시라도 **게이트를 넘는 명령은 내가 실행하지 않는다.** 가장 빠른 준수 경로를 먼저 보이고, 그래도 원하면 사용자가 칠 명령을 적어 주고, 일어난 우회는 REMAINING에 부채로 남긴다.

## Red Flags

| 생각 | 실제 |
|---|---|
| "앞 단계는 사용자가 했다니 바로 이 단계로" | `--next`가 기준이다 |
| "세부 스킬로 불렸으니 그 단계만 하면 된다" | 진입 조건이 안 맞으면 하지 않고 맞는 단계를 알린다 |
| "노스스타에 맞으니 골 초안을 만들어 두자" | 후보만 쓴다. 판정은 judge |
| "한 라운드만 더" | 설계 2회, 리뷰 3라운드가 끝이다 |
| "오너가 책임진다니 우회 명령을" | 사용자가 직접 친다 |

## 관련 스킬

team-handoff·session-handoff(기록), qa-run(QA 캡처), autopilot(무인 실행), debate(큰 결정).
