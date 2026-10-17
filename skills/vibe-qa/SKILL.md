---
name: vibe-qa
description: Use when a reviewed goal MR needs QA before merge or deploy, when the user says "QA만", "테스트 돌리고 화면 확인", "머지 전에 확인", or when vibe-flow reaches the QA stage.
---

# vibe-qa — QA (코드 · 화면)

규칙 원본: vibe-flow 폴더의 `qa-gate.md`(Aside 캡처·재시도·보류). 스크립트 `S=<vibe-flow>/scripts`.

리뷰는 코드를 읽는 일이고 QA는 실제로 돌려 보는 일이다. **QA는 지금 작업물에서 한다** — 리뷰 전에 돌린 테스트는 QA가 아니다.

## 진입 조건 (단독으로 불려도 같다)

`python $S/mr_check.py <mr> --stage qa` 통과(「리뷰 기록」에 `판정: 확정`). 실패하면 QA를 하지 않고 **vibe-review**로 간다고 알린다.

## 순서

1. 코드: `python $S/qa_run.py --mr .vibe/mr-G-###.md` — `test_cmd` 전체를 돌려 `.vibe/qa/<tree>.json`(exit·시간·출력 끝 200줄)을 남기고 「QA 결과」 `대상 tree`·`코드` 줄을 채운다. 손으로 돌리거나 줄을 손으로 쓰지 않는다 — merge 검사가 `코드: 통과`를 이 기록과 대조한다. 실패는 2회까지 다시, 그래도 실패면 `코드: 실패`. `test_cmd`가 없으면 exit 2 = `미검증`.
2. 화면 판단: `ui_globs`에 걸린 파일이 있으면 브라우저 필수. 안 걸려도 화면에 닿는 코드면 브라우저. 닿지 않으면 **이유를 적는다** — `브라우저: 해당 없음 — <이유>`. 이유 없는 「해당 없음」은 `--stage merge`가 막는다.
3. 브라우저: Aside로 완료 조건 시나리오 + 공유 화면, 역할별. 캡처는 qa-run의 `QA.shot` + `crop.py`, **실제 파일**을 레포 기준 경로로 `![A1](.vibe/qa/G-###/A1.png)`. 파일이 없거나 링크가 없으면 merge가 막는다. 로그인 만료·환경 장애는 `미검증` = 머지 금지.
4. 「QA 결과」(`.vibe/mr-G-###.md` — 레포 루트에 두면 QA 대상 비교가 깨진다): 대상 commit 또는 tree(`vf_git.snapshot`), 환경·역할, 코드, 브라우저, 증거, 미검증 항목. 확인된 「완료 조건」은 `[x]`로(미체크가 남으면 merge 금지). 이 본문은 기록 커밋에 `<핸드오프>/mr/G-###.md`로 남는다.
5. 다음은 **vibe-record**(기록을 마지막 작업 커밋에 합침). 기록만 바뀐 것은 QA를 깨지 않는다. 코드가 바뀌면 QA를 다시 한다.

## Red Flags

| 생각 | 실제 |
|---|---|
| "아까 테스트 돌렸다" | 지금 작업물에서 다시 |
| "글롭에 안 걸리니 화면 확인은 빼자" | 판단하고 이유를 적는다. 닿으면 Aside |
| "로그인이 만료됐으니 브라우저는 생략하고 통과" | `미검증`이다. 사용자에게 로그인을 부탁한다 |
| "불안정한 테스트라 통과로 적자" | 2회 재실행 뒤 실패면 실패 |
| "테스트는 따로 돌렸으니 줄만 쓰자" | 기록 없는 `통과`는 merge가 막는다. `qa_run.py` |
