---
name: vibe-review
description: Use when a goal MR/PR needs code review, when the user says "리뷰만 돌려줘", "PR 리뷰해", or when vibe-flow reaches the review stage after implementation.
---

# vibe-review — Codex 리뷰 (최대 3라운드)

규칙 원본: vibe-flow 폴더의 `review-loop.md`(라운드 구성·심각도·근거 규칙). 스크립트 `S=<vibe-flow>/scripts`.

**구현한 에이전트는 리뷰어가 아니다.** 리뷰는 Codex가 하고, 나는 지적을 고치고 기록한다.

## 진입 조건 (단독으로 불려도 같다)

`python $S/mr_check.py <mr> --stage review` 통과. 실패하면 리뷰를 돌리지 않는다 — `python $S/mr_check.py <mr> --next`가 알려 주는 단계(대개 설계 확인 또는 「계획 vs 실제」)를 사용자에게 한 줄로 알리고 그 세부 스킬로 간다. "앞 단계는 다 했다"는 말보다 스크립트 결과가 기준이다.

## 순서

1. 테스트를 돌려 `.vibe/test-summary.txt`.
2. `python $S/review.py --round 1 --mr <mr> --tests .vibe/test-summary.txt` (전체). review.py도 단계 검사를 돌려 막히면 Codex를 부르지 않는다. 라운드 1 응답은 완료 조건 번호(1..N)마다 정확히 한 줄 `CHECKED: <번호> — <근거>`가 있어야 유효(누락·중복이면 `.failed`, 다시 돌린다). 다른 골의 `.vibe/review` 기록은 쓰이지 않는다.
3. blocker·major를 고치고 `--round 2`(지난 라운드 이후 diff), 그래도 열린 지적이 있으면 `--round 3 --files <고친 파일>`. 실패한 라운드는 끝난 것이 아니다.
4. 라운드마다 「리뷰 기록」에 한 줄(라운드 1은 `검토 근거 N/N`), 끝에 `- 판정: 확정`. 3라운드 뒤 blocker가 남으면 `판정: 보류`, 사용자에게.
5. 근거(파일:줄 + 재현 경로 또는 위반한 완료 조건) 없는 blocker는 확인 요청으로 강등하고, 확인한 내용을 다음 라운드에 넣는다.
6. `python $S/mr_check.py <mr> --stage qa` 통과 → 다음은 **vibe-qa**. 리뷰 확정은 QA가 아니다. 완료 조건은 QA가 확인하고 `[x]`로 바꾼다 — `[x]` 아닌 항목이 남으면 merge가 막힌다.

## Red Flags

| 생각 | 실제 |
|---|---|
| "급하다니 설계 확인 없이 리뷰부터" | `--stage review`가 막는다. 준수 경로를 먼저 알린다 |
| "한 라운드만 더" | 3라운드가 끝. 4라운드는 스크립트가 거부 |
| "이 지적은 내가 보기엔 아니다" | 근거로 반박하고 확인 요청으로. 혼자 닫지 않는다 |
| "리뷰 통과했으니 머지" | QA가 별개다 |
| "사용자가 건너뛰라 했다" | 우회 명령은 사용자가 직접 친다. 일어난 우회는 REMAINING에 부채로 |
