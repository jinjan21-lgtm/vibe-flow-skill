---
name: vibe-claim
description: Use when starting a session or picking up work in a repo with docs/handoff/, NORTHSTAR.md, or .vibe-flow.json — before reading code for a task, when the user says "이거 집어", "이 일 시작", "다음 일 뭐야", or when vibe-flow reaches pre-check, goal check, or claim.
---

# vibe-claim — 사전체크 · 골 확인 · 선점

vibe-flow의 첫 단계. 규칙 원본은 vibe-flow 폴더(팀 `.claude/skills/vibe-flow/`, 개인 `~/.claude/skills/vibe-flow/`)의 `docs/structure.md`. 스크립트 `S=<그 폴더>/scripts`.

**원격 모드에서는 선점 push가 확인되기 전에 코드를 읽지 않는다.** 중복 탐색을 막는 유일한 지점이다. 로컬 모드(원격 없음)는 골 경계를 잡는 읽기만 먼저 해도 된다.

## 순서

1. `python $S/handoff.py precheck` — 첫 줄에 원격 여부가 나온다. 원격 모드면 `git pull` 뒤 다시, 로컬 모드면 pull 없이. 출력의 **읽을 순서만** 읽는다(INDEX들). 결정·작업 기록 본문은 열지 않는다.
   `착수 불가`(codex·`test_cmd` 없음, 커밋 안 된 변경)면 멈추고 사용자에게 보인다. 기준 테스트는 `--run-tests`로만.
2. 이어 갈 착수·보류·결정 대기·후보가 있으면 먼저 보인다.
3. 골: `python $S/goal_gate.py list`. 맞는 활성 골이 없으면 `candidate "<제목>"` → 네 칸 채우기 → `judge <후보> --apply`. 판정(CREATE/REJECT/MERGE)을 따른다. 노스스타가 draft면 판정이 거부된다 — 사용자 확정을 요청하고 멈춘다.
4. 선점: `python $S/handoff.py claim G-### "<할 일>" <접두사>/G-###-<주제>`. 중복이면 멈추고 합류·골 나누기를 사용자에게 묻는다.
   - 원격 모드: push 확인 메시지가 나와야 선점이다. push 실패를 로컬 커밋으로 대신하지 않는다 — `--no-push`는 사용자 지시일 때만.
   - 로컬 모드(origin 없음·`"remote": false`): 로컬 커밋만 하고 `선점(로컬 모드 — 원격 없음): <브랜치>@<sha>`. 모드는 스크립트가 정한다.
5. 선점 뒤 MR 본문 `.vibe/mr-G-###.md`(`templates/mr-body.md`)의 「골」만 채우고 `python $S/mr_check.py <mr> --stage claim`.

통과하면 다음은 **vibe-design**(탐색·설계). 단독 호출이면 여기서 끝내고 다음 단계를 한 줄로 알린다.

## 이 스킬이 하지 않는 것

- 골이 "노스스타에 맞는지" 스스로 판단 — judge가 한다.
- 노스스타·골 파일 status 수정(작업 브랜치에서 금지).
- 판정 전 코드·브랜치·MR 만들기.

## Red Flags

| 생각 | 실제 |
|---|---|
| "먼저 코드 좀 보고 선점하자" | 원격 모드면 선점 push가 먼저다 |
| "push가 안 되니 로컬 커밋으로 선점" | 원격이 있으면 실패를 보고한다. 로컬 모드는 스크립트가 정한다 |
| "DECISIONS 전체를 한 번 읽어 두면 편하다" | 시작은 INDEX만. 결정은 vibe-design에서 태그로 |
| "작은 일이라 골 없이" | 동작이 안 바뀌면 G-000, 아니면 후보 → judge |
| "같은 골을 다른 사람이 잡았지만 내 쪽이 다르다" | 합류·나누기는 사용자가 정한다 |
