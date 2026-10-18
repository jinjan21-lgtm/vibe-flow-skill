# QA 게이트 (리뷰 확정 뒤, 머지·배포 전 필수)

리뷰는 코드를 읽는 일이고 QA는 실제로 돌려 보는 일이다. 리뷰가 확정돼도 QA 없이 머지하지 않는다.

## 시작 조건

- 「리뷰 기록」에 `판정: 확정`이 있다.
- QA는 **지금 HEAD**에서 한다. 리뷰 전에 돌린 테스트는 QA가 아니다.

## 1단계 — 코드

1. 기존 자동 테스트를 전부 `python $S/qa_run.py --mr .vibe/mr-G-###.md`로 돌린다(`.vibe-flow.json`의 `test_cmd`). 손으로 따로 돌리지 않는다. 이 스크립트가 지금 작업물 tree를 잡고 exit·시간·출력 마지막 200줄을 `.vibe/qa/<tree>.json`에 남긴 뒤 「QA 결과」의 `대상 tree`·`코드` 줄을 채운다(`--mr` 없이 돌리면 출력된 두 줄을 붙인다). 종료코드는 테스트 결과를 따르고, `test_cmd`가 없으면 exit 2 `미검증`이다. QA 대상은 `qa_run.py`가 쓴 tree다 — commit sha를 손으로 쓰지 않는다(뒤에 기록을 amend하면 sha가 바뀐다). 출력이 verbose(`-v`)면 테스트별 결과가 기록 `tests`에 남는다. merge 검사는 `코드: 통과`를 이 기록과 대조한다. 기록이 없거나 exit≠0이거나 tree가 다르거나 기록의 `cmd`가 지금 `test_cmd`와 다르면(테스트 명령이 바뀜) 막는다. 통과/전체 수는 출력에서 읽는다(unittest `Ran N tests`+OK/FAILED, pytest `N passed, M failed`, jest·vitest `Tests: N passed`) — 기록에 `passed`·`total`·`skipped`, 코드 줄에 `N/M 통과(K 건너뜀)`. 건너뛴 테스트는 통과가 아니다(전체에는 센다). 코드 줄에 쓴 `N/M`이 기록과 다르면 merge가 막는다. 출력에서 못 읽으면 수를 손으로 쓰지 않는다. 자동 테스트가 없는 레포(빌드 없는 프로토타입 등)는 최소한 `python $S/syntax_check.py <폴더>`(node --check, 검사할 파일이 0개면 exit 2 미검증)를 `test_cmd`로 두고, 동작 검증은 브라우저 단계가 맡는다.
2. 완료 조건마다 만든 테스트가 그 안에 있는지 확인한다. 없는 완료 조건이 있으면 테스트를 추가하고 다시 돌린다. 확인된 완료 조건은 MR 「완료 조건」에서 `[x]`로 바꾼다(미체크가 남으면 merge 검사가 막는다). `[x]`는 자기 판정이 아니다 — merge가 리뷰 라운드 1의 CHECKED 근거 테스트가 이 실행 기록 `tests`에서 모두 ok인지 대조한다(아래 「역할」).
   QA 통과는 exit 0만이 아니다 — 출력에서 테스트 수를 읽었고 통과가 1건 이상이어야 한다(0건 실행·수를 못 읽는 출력·전부 건너뜀은 실패). RED(`qa_run.py --red --mr`)는 실패한 테스트 **이름**을 출력에서 찾았을 때만 기록된다(명령 오류·수만 있는 출력은 기록 안 함) — `test_cmd`는 테스트별 결과를 내는 상세 출력으로 둔다(unittest `-v`, pytest `-v`, jest `--verbose`, vitest `--reporter=verbose`). 테스트가 실행 중 코드(기록·산출물 제외)를 바꾸면 그 실행은 통과·RED가 아니다. merge는 이 골·브랜치·기준의 RED 중 QA(GREEN)보다 먼저 돌았고 그 실패 테스트가 QA에서 ok인 것을 고르고(`mr_check.select_red`), `export-evidence`는 그 RED를 그대로 내보낸다. 동작 불변 변경의 RED 대체는 docs/task-types.md 표준 행.
3. 실패한 테스트는 `qa_run.py`로 2회까지 다시 돌린다. 그래도 실패하면 `코드: 실패`다. 불안정한 테스트라고 판단해도 통과로 적지 않는다.

## 2단계 — 브라우저 (UI 파일이 바뀌었으면 필수)

UI 파일 여부는 `mr_check.py`와 같은 기준(`ui_globs`)으로 정한다. 구현 에이전트가 "UI 영향 없음"이라고 판단해 생략하지 않는다.

1. Aside 브라우저로 데브 서버에서 완료 조건의 시나리오와, 연관 범위에 적은 공유 화면을 확인한다.
2. 캡처는 **실제 파일**이어야 한다. 레포 루트 기준 경로로 `![A1](.vibe/qa/G-###/A1.png)`처럼 붙인다. `브라우저: 통과`면 merge 검사가 http(s)가 아닌 이미지·링크 경로마다 파일이 있는지, 이미지·영상(png·jpg·jpeg·webp·gif·mp4·webm)인지 보고, 하나도 없거나 다른 형식(.txt 등)이면 막는다. 「캡처」라는 글자나 파일 이름만 적는 것은 증거가 아니다. 캡처는 qa-run 스킬의 `QA.shot` + `crop.py`를 쓴다(`~/.claude/skills/qa-run/aside-snippets.md`). Aside의 `page.screenshot`은 가끔 시간 초과가 나므로 캡처를 2회까지 다시 시도한다(아래 재시도 표의 환경 장애). Aside REPL에는 `getByPlaceholder`가 없으니 CSS 선택자를 쓴다. 영역은 `body`가 아니라 콘텐츠를 감싼 컨테이너로 잡는다. 화면 전체 폭을 잡으면 640px로 줄면서 글씨를 읽을 수 없다.
3. 사용한 계정 역할을 적는다. 권한별로 다르게 보여야 하는 화면이면 역할마다 확인한다.
4. 로그인 세션이 만료됐으면 사용자에게 로그인을 부탁한다. 그동안 상태는 `브라우저: 미검증`이고 머지하지 않는다.
5. 다른 세션도 QA 중일 수 있다. 새 탭을 열어 쓰고 `QA.key`를 골 ID로 해서 캡처 폴더를 나눈다. 로그인·역할 전환이 필요한 QA는 한 번에 하나만 한다.
6. 상태가 바뀌거나 알림이 가는 버튼(승인·발송·삭제 등)은 qa-run의 데브 조작 안전선을 따른다.

`ui_globs`에 걸린 파일이 없어도 **글롭은 보조 신호다.** 코드가 바뀌었으면 화면에 닿는지 판단하고, 닿으면 위 순서대로 브라우저 QA를 한다. 닿지 않으면 이유를 적는다 — `브라우저: 해당 없음 — 서버 포맷 함수만, 화면 코드에서 안 씀`. 이유 없는 `해당 없음`은 `mr_check --stage merge`가 막는다(「UI 판정 불명확」). 문서만 바뀌었으면 `해당 없음 — 문서만`.

## 결과 등록

MR 본문(작업 중 `.vibe/mr-G-###.md`)의 「QA 결과」를 채우고, MR 댓글에도 같은 내용을 남긴다. 기록 전에 `python $S/handoff.py export-evidence G-###`이 MR 본문·QA 실행 기록·RED 기록·이 골·브랜치·기준의 설계 확인·리뷰 원문(회차마다 도장: schema·tree·code_tree·goal·branch·base·conds·contract)·캡처를 `<핸드오프>/mr/G-###*`로 쓴다(vibe-record). 「골」이 여럿이면 골마다 쓴다. `check-record`는 그 사본이 기록 커밋에 있는지 본다.

**제3자 재검증은 판정 규칙을 새로 만들지 않는다.** 새 clone에서 `handoff.py verify-evidence G-### [--commit <sha>] [--run-tests]`은 커밋된 증거만으로 임시 clone에 `.vibe/`를 되살려 **로컬과 같은** `mr_check.py --stage merge`를 돌린다(재연). 로컬과 다르게 보는 곳은 `handoff.REPLAY_DIFF` 표뿐이다 — 기준은 판정 회차 도장의 base를 가진 조상 커밋, 브랜치는 도장 branch, 골은 done도 허용, clone에 없는 amend 전 tree는 기록의 code_tree로 비교, 캡처 링크는 사본 폴더 기준. 기록의 tree·code_tree는 자기 신고라서, 실행 사실은 `--run-tests`로 커밋된 코드에서 `test_cmd`를 다시 돌려 통과·수·테스트별 결과·코드 tree가 기록과 같아야 확인된다. 커밋의 명령을 그대로 실행하므로 명시했을 때만, 재연 merge가 통과했을 때만 돌리고 환경변수는 허용 목록만 넘긴다(믿지 않는 코드는 격리된 환경에서). 종료 코드: 0 통과(재실행 일치), 4 UNPROVEN(재연 merge는 통과, 재실행 안 함 — 통과 아님), 1 실패, 3 LEGACY. 증거 판(`vf_git.EVIDENCE_SCHEMA`)보다 낮은 판의 증거는 FAIL도 통과도 아닌 `LEGACY`(종료 3, 재검증 대상)다 — 도장을 지어내 옮기지 않는다. 같은 코드에서 `review.py`·`qa_run.py --red --mr`·`qa_run.py --mr`를 다시 돌리고 `export-evidence`로 기록을 고친다.

```
- 대상 tree: 9c2e…(qa_run.py가 채움)
- 환경: https://dev.example.com / 계정 역할: 일반 영업
- 코드: 통과 — 412/412 통과, npm test exit 0, 190.2s (기록 .vibe/qa/9c2e….json)
- 브라우저: 통과 — 거래처 부분 검색 ✅, 0건 안내 ✅, 청구서 목록 검색(공유 부품) ✅
- 증거: ![A1](.vibe/qa/G-012/A1.png) ![A2](.vibe/qa/G-012/A2.png)
- 미검증·생략 항목과 사유: 없음
```

```bash
# GitLab
MR=.vibe/mr-G-###.md   # 레포 루트에 두지 않는다 — 추적 안 된 루트 파일은 QA 대상 비교에 코드 변경으로 잡힌다
glab mr update <번호> --description "$(cat $MR)" && glab mr note <번호> -m "$(sed -n '/^## QA 결과/,$p' $MR)"
# GitHub
gh pr edit <번호> --body-file $MR && gh pr comment <번호> --body "$(sed -n '/^## QA 결과/,$p' $MR)"
```

머지 직전에 `python ~/.claude/skills/vibe-flow/scripts/mr_check.py .vibe/mr-G-###.md --stage merge`가 통과해야 한다.

## 재시도와 보류

| 상황 | 한도 | 넘으면 |
|---|---|---|
| 테스트 실패 재실행(`qa_run.py`) | 2회 | `코드: 실패`, 고치고 리뷰 3라운드 형식으로 부분 검증 |
| 데브 서버·Aside 환경 장애 | 복구 시도 1회 | `미검증`으로 적고 보류, 사용자에게 보고 |
| QA 뒤 코드 변경 | - | QA를 HEAD에서 다시 한다 |

## 상태 셋 — 미검증·위험 인수·정책 미결

셋은 다른 상태이고 **어느 것도 merge 게이트를 열지 않는다.** 게이트를 넘는 것은 사용자가 직접 친 우회뿐이고(SKILL.md 「사용자가 우회를 지시할 때」), 일어난 우회는 REMAINING 부채다. `mr_check --stage merge`와 `verify-evidence`가 같은 이름으로 낸다.

| 상태 | 어디에 | 무엇으로 닫히나 |
|---|---|---|
| `UNVERIFIED` | 「QA 결과」 `- 미검증·생략 항목과 사유: <항목; …>` (없으면 정확히 `없음` — 빈 값·`<…>` 자리표시도 미검증) | 검증해서 `없음`으로. 결정으로는 통과가 되지 않는다 |
| `ACCEPTED-RISK` | 위 항목 + `- 위험 인수: D-nnn — <항목>` (사용자가 배포 위험을 인수한 결정 — 블록에 골 ID와 그 항목) | 닫히지 않는다 — 미검증 상태를 보존한 채 차단. 머지는 사용자가 직접 우회 |
| `POLICY-PENDING` | 「영향·위험」 `- 미확인: <항목; …>` (빈 값·자리표시도 미결) | `- 정책 결정: D-nnn — <항목>`(사람 결정 — 블록에 골 ID와 그 항목) 또는 `- 해소: <항목> — <QA 기록에서 ok인 테스트 이름 · 실재하는 파일:줄>`. 항목은 전체 일치(부분 문자열 아님). 위험 인수로는 닫히지 않는다 |

## 역할 — 누가 판정하나

| 일 | 하는 쪽 |
|---|---|
| 테스트 작성·실행, 증거 수집(`qa_run`), MR 칸 채우기 | 구현 에이전트 |
| 완료 조건마다 확인 근거(실재하는 테스트 이름·`파일:줄`, 표준·강화는 테스트 이름 필수) | 리뷰어(Codex, CHECKED) — 근거가 실재하지 않으면 응답 무효 |
| 근거 테스트가 실제로 돌았고 ok인가, QA 대상이 지금 코드인가, 상태 셋 | merge 게이트(`mr_check`, 기계) — `[x]`는 이 검사를 통과해야 의미가 있다 |
| 정책 결정·위험 인수·우회 | 사람(사용자) |

결정 블록에 「시뮬레이션」(E2E·리허설)이라고 적힌 결정은 운영 승인이 아니다 — merge가 `SIMULATED-DECISION`으로 막는다. 리허설 실행(환경변수 `VF_REHEARSAL=1`)에서만 `[state] SIMULATED-DECISION`으로 통과한다 — 커밋된 설정으로는 열리지 않는다. 제3자 재검증은 `verify-evidence --rehearsal`을 명시했을 때만 같은 상태(STATE)로 통과하고, 없으면 실패다(운영 검증). RED 대체 승인 `(승인 D-nnn)`도 같은 검사를 받는다. 위험 판단은 구현자 혼자 하지 않는다: 「위험: 없음」인데 바뀐 코드에 금액·권한·삭제 식별자가 있으면 review 단계부터 `- 위험 판단: <이유>`가 필요하고, 설계 확인(Codex)의 `POLICY:` 항목은 「영향·위험」 미확인으로 옮겨야 한다. 표준·강화는 구문 검사(`syntax_check`)만인 test_cmd로 merge하지 않는다.
