---
name: vibe-design
description: Use when a goal is claimed and the approach is not yet confirmed — before writing implementation code, when filling the MR 「설계」 section, when the user asks to "설계만", "어떻게 할지 먼저", or when vibe-flow reaches explore, design, or design check.
---

# vibe-design — 탐색 · 설계 · 설계 확인

규칙 원본: vibe-flow 폴더의 `review-loop.md` 「설계 확인」. 스크립트 `S=<vibe-flow>/scripts`.

## 진입 조건 (단독으로 불려도 같다)

`python $S/mr_check.py <mr> --stage claim` 통과. 실패하면 멈추고 **vibe-claim**으로 간다고 알린다.

## 순서

1. **찾아 읽기** — 진입 인덱스에서 필요한 것만:
   - 결정: `grep "#<화면 ID 또는 코드 이름>" docs/handoff/DECISIONS.md`(예: `#HOME-01`) → 유효한 줄(대체됨 아님)의 본문만. 태그가 없으면 INDEX 제목, 그다음 `grep -n`으로 걸린 블록만.
   - 작업 기록: WORKLOG INDEX에서 같은 골·토픽 줄의 앵커만.
   - UI가 닿으면 `docs/design-system.md`.
2. 선점 브랜치에서 코드를 읽는다. 임시 코드는 버린다.
3. MR 본문 「설계」 다섯 칸: 접근 방식 · 바꿀 모듈·파일 · 데이터·API 변경 · 대안과 선택 이유 · 테스트 계획. 개발 유형·영향 표식(UI·API·데이터·의존성)은 `docs/task-types.md`로. `--stage draft`.
4. 설계 확인: `python $S/review.py --design 1 --mr <mr>` → 「설계 확인」에 `- 확인 1: …`, `- 판정: 확정`. `POLICY:` 항목은 「영향·위험」 `- 미확인:`에 그대로. CONFIRM이어도 blocker·major FINDING마다 `- 반영: <id> — <어떻게>`(또는 `- 넘김: <id> — 골 후보 <사유>`). blocker가 남으면 `--design 2`. 2회 뒤에도 blocker면 `판정: 보류`, 사용자에게(REMAINING `- [ ] 결정: …`). 사용자가 결정하면 D-nnn(골 ID·blocker ID)으로 기록하고 `- 사람 결정: D-nnn — <blocker ID>`, `- 판정: 확정 (사람 판정 D-nnn)` — 3회차는 없다. 바뀐 설계는 「계획 vs 실제」로(`review-loop.md`).
5. 작은 변경(기본 50줄·3파일, 기록 제외)은 **코딩 전에** `- 생략: 작은 변경 (예상 N줄·M파일)`(N·M이 기준 초과면 막힘). `- 위험:`·데이터·API 변경이 정확히 `없음`이 아니면 생략 불가(`없음(…)`도 위험). 강화 프로필은 「검증 계획」에 회귀 테스트 이름(`docs/task-types.md`). 생략 중엔 `--stage build`가 코드 크기도 본다 — 넘으면 멈추고 4번. 구현 뒤 확인이면 `- 순서: 구현 선행 (사유)`.
6. `python $S/mr_check.py <mr> --stage build` 통과 → 다음은 **vibe-dev**.

## Red Flags

| 생각 | 실제 |
|---|---|
| "설계는 구현하면서 정리하자" | `--stage build`를 넘지 못한다 |
| "결정 본문을 다 읽어야 안전하다" | 태그로 고른 유효 결정만 |
| "설계 확인 한 번 더" | 2회가 끝이다. 그 뒤는 사람 |
| "생략하고 커지면 그때" | 커밋 전 build가 막는다 |
| "다 짰으니 설계 확인은 형식만" | 기준 커밋으로 보고 기록된다 |
