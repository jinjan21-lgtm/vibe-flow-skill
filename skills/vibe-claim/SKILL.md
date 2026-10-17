---
name: vibe-claim
description: Use when starting a session or picking up work in a repo with docs/handoff/, NORTHSTAR.md, or .vibe-flow.json — before reading code for a task, when the user says "이거 집어", "이 일 시작", "다음 일 뭐야", or when vibe-flow reaches pre-check, goal check, or claim.
---

# vibe-claim — 사전체크 · 골 확인 · 선점

vibe-flow의 첫 단계. 규칙 원본은 vibe-flow 폴더(팀 `.claude/skills/vibe-flow/`, 개인 `~/.claude/skills/vibe-flow/`)의 `docs/structure.md`. 스크립트 `S=<그 폴더>/scripts`.

**선점 push가 확인되기 전에는 코드를 읽지 않는다.** 탐색은 다른 세션에 보이지 않는다 — 같은 일을 둘이 탐색하는 것을 막는 유일한 지점이다.

## 순서

1. `git pull` → `python $S/handoff.py precheck`. 출력의 **읽을 순서만** 읽는다. 인덱스 구조면 INDEX들만이고 총량이 함께 나온다(목표 12,000자). 결정·작업 기록 본문은 지금 열지 않는다.
2. 이어 갈 착수·보류·결정 대기·후보가 있으면 그것을 사용자에게 먼저 보인다.
3. 골: `python $S/goal_gate.py list`. 맞는 활성 골이 없으면 `candidate "<제목>"` → 네 칸 채우기 → `judge <후보> --apply`. 판정(CREATE/REJECT/MERGE)을 그대로 따른다. 노스스타가 draft면 판정이 거부된다 — 사용자 확정을 요청하고 멈춘다.
4. 선점: `python $S/handoff.py claim G-### "<할 일>" <접두사>/G-###-<주제>`. 중복이면 여기서 멈추고 합류·골 나누기를 사용자에게 묻는다.
5. push 확인 메시지를 본 뒤 MR 본문(`templates/mr-body.md`)의 「골」만 채우고 `python $S/mr_check.py <mr> --stage claim`.

통과하면 다음은 **vibe-design**(탐색·설계). 단독으로 불렸으면 여기서 끝내고 다음 단계를 한 줄로 알린다.

## 이 스킬이 하지 않는 것

- 골이 "노스스타에 맞는지" 스스로 판단 — judge가 한다.
- 노스스타·골 파일 status 수정(작업 브랜치에서 금지).
- 판정 전 코드·브랜치·MR 만들기.

## Red Flags

| 생각 | 실제 |
|---|---|
| "먼저 코드 좀 보고 선점하자" | 선점 push가 먼저다 |
| "DECISIONS 전체를 한 번 읽어 두면 편하다" | 시작은 INDEX만. 결정은 vibe-design에서 태그로 |
| "작은 일이라 골 없이" | 동작이 안 바뀌면 G-000, 아니면 후보 → judge |
| "같은 골을 다른 사람이 잡았지만 내 쪽이 다르다" | 합류·나누기는 사용자가 정한다 |
