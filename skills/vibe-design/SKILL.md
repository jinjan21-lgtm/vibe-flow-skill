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
   - 결정: `grep "#<화면 ID 또는 코드 이름>" docs/handoff/DECISIONS.md`(예: `#HOME-01`, `#core.js`) → 유효한 줄(대체됨 아님)의 본문만 연다. `대체 D-kkk`가 있는 줄이 있으면 D-kkk는 쓰지 않는다. 태그가 없는 주제는 INDEX 제목을 `grep -n "<키워드>"`, 그래도 없으면 본문 파일을 `grep -n`해 걸린 블록만.
   - 작업 기록: WORKLOG INDEX에서 같은 골·토픽 줄의 앵커만.
   - UI가 닿으면 `docs/design-system.md`.
2. 선점 브랜치에서 코드를 읽는다. 탐색 결과물(임시 코드)은 버린다.
3. MR 본문 「설계」 다섯 칸: 접근 방식 · 바꿀 모듈·파일 · 데이터·API 변경 · 대안과 선택 이유 · 테스트 계획. 개발 유형과 영향 표식(UI·API·데이터·의존성)은 vibe-flow `docs/task-types.md`로 정한다. `--stage draft`.
4. 설계 확인: `python $S/review.py --design 1 --mr <mr>` → 「설계 확인」에 `- 확인 1: …`, `- 판정: 확정`. blocker가 남으면 `--design 2`. 2회 뒤에도 blocker면 `판정: 보류`, 사용자에게.
5. 작은 변경(기본 50줄·3파일 이하)은 `- 생략: 작은 변경`. 커지면 리뷰 단계에서 다시 막힌다.
6. `python $S/mr_check.py <mr> --stage build` 통과 → 다음은 **vibe-dev**.

## Red Flags

| 생각 | 실제 |
|---|---|
| "설계는 구현하면서 정리하자" | `--stage build`를 넘지 못한다 |
| "결정 본문을 다 읽어야 안전하다" | 태그로 고른 유효 결정만. 전체 로드는 맥락만 잡아먹는다 |
| "설계 확인 한 번 더" | 2회가 끝이다. 그 뒤는 사람 |
| "생략하고 나중에 커지면 그때" | diff가 기준을 넘으면 그때 막힌다 — 처음부터 받는 게 싸다 |
