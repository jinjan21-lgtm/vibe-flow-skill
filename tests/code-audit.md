# 스크립트 코드 감사 (2026-10-17)

바깥눈: Aside 브라우저의 ChatGPT(추론 High). `scripts/` 8개 파일 원문 전체(2,488줄, 줄 번호 포함)를 한 번에 보내 (1) 정확성 결함 목록 (2) 구현 평가를 받았다. 감사자는 자체 임시 git 저장소에서 일부를 재현했다고 밝혔다. 아래 「처리」는 이쪽에서 **로컬 재현 → 실패하는 테스트(RED) → 수정 → 통과(GREEN)** 또는 **결함 아님 근거**로 다시 확인한 결과다 — 감사자 주장은 후보로만 다뤘다.

## 1. 정확성 결함 (감사 원문 요약)

| ID | 위치 | 심각도 | 주장 |
|---|---|---|---|
| F-01 | vf_git.py:39-47 | blocker | 스냅숏이 빈 임시 인덱스에 `add -A`만 해서, 추적 중인 무시 대상 파일이 스냅숏에서 빠진다 |
| F-02 | mr_check.py:188 | blocker | `- 코드: 통과하지 못함`이 `^-\s*코드:\s*통과` 접두어에 걸려 통과로 인정된다 |
| F-03 | vf_git.py:8-10 · mr_check.py:190-207 | major | 기본 글롭 `**/*.tsx`가 fnmatch에서 루트 `App.tsx`를 놓쳐 브라우저 QA가 빠질 수 있다 |
| F-04 | mr_check.py:97-103, 110-111 | blocker | `startswith(gid)`·`g in cur`가 ID 경계를 안 봐서 G-123이 G-1234 파일·브랜치로 통과한다 |
| F-05 | review.py:34-40 | blocker | Codex 실행이 실패해도 이전 출력 파일 내용을 그대로 판정으로 쓴다 |
| F-06 | goal_gate.py:182-185 | blocker | 메시지가 `Revert `·`Merge `로 시작하면 골 검사를 전부 건너뛴다 |
| F-07 | goal_gate.py:123-157 | blocker | 골 ID 예약이 로컬 잠금뿐이라 독립 clone 둘이 같은 G-###를 받는다 |
| F-08 | handoff.py:183-195 | blocker | 선점 커밋이 훅에서 거부돼도 「선점 커밋 완료」를 출력한다 |
| F-09 | handoff.py:188-193 | blocker | 선점 전에 stage돼 있던 무관한 파일이 선점 커밋에 섞인다 |
| F-10 | handoff.py:165-167 | blocker | 접두어 일치·비활성(done) 골도 선점할 수 있다 |
| F-11 | handoff.py:253-257 | blocker | 다른 골(G-1234)의 완료 줄로 G-123 기록 검사가 통과한다 |
| F-12 | goal_gate.py:209-218 | blocker | install-hook이 기존 commit-msg 훅을 덮어쓴다 |
| F-13 | hindex.py:302-325 | blocker | `## D-###` 항목이 없는 DECISIONS.md를 migrate하면 머리말 원문이 사라진다 |
| F-14 | syntax_check.py:19-33 | blocker | 검사 대상이 0개여도 통과(종료코드 0) |
| F-15 | dupe.py:36-47 | blocker | gh가 설치돼 있으면 GitLab에서도 glab 조회를 안 한다 |
| F-16 | dupe.py:81-88, 150-154 | blocker | 같은 작성자·날짜·작업의 착수 표시 두 개가 브랜치 구분 없이 하나로 합쳐진다 |
| F-17 | hindex.py:146-148, 495-515 | major | 보관된 WORKLOG 월 파일을 다시 보관 대상으로 잡아 `ui-2026-10-2026-10.md`가 생긴다 |

## 2. 처리

17건 모두 재현됐다(결함 아님 0건). 모든 항목을 실패하는 테스트로 먼저 재현(RED)하고 고친 뒤 통과(GREEN)를 확인했다. 테스트는 `tests/test_audit_*.py`(기존 `test_scripts.py`는 그대로).

| ID | 재현 | 처리 | 테스트 |
|---|---|---|---|
| F-01 | 됨 — 추적 중인 `cache/a.pyc`가 스냅숏에 없음 | `vf_git.snapshot`: HEAD가 있으면 임시 인덱스에 `read-tree HEAD` 뒤 `add -A`. merge 검사의 「추적 중인 무시 파일 제외+경고」는 유지 — 테스트 실행이 추적 중인 `.pyc`를 다시 쓰는 경우(별개 문제)를 막는다 | `test_snapshot_keeps_tracked_but_ignored_file` 외 1 |
| F-02 | 됨 — `- 코드: 통과하지 못함`이 merge 통과 | `mr_check.PASS = 통과(?=$\|[\s(（—–])`를 코드·브라우저 줄과 `startswith("통과")` 자리 셋에 적용 | `test_code_not_passed_wording_blocks_merge`, `test_browser_not_passed_wording_blocks_ui_merge` |
| F-03 | 됨 — 루트 `App.tsx`가 UI로 안 잡힘 | `vf_git.glob_match`: `**/`로 시작하는 글롭은 접두어 없이도 비교. mr_check·review 둘 다 사용 | `test_root_level_tsx_requires_browser` |
| F-04 | 됨 — `G-1234-*.md`·`work/G-1234`가 G-123로 통과 | 골 파일·브랜치 모두 `G-123(?!\d)` 경계 일치 | `test_goal_file_prefix_is_not_a_match`, `test_branch_with_longer_id_is_not_a_match` |
| F-08 | 됨 — pre-commit 거부에도 「선점 완료 — push 확인됨」 | 커밋 반환코드 검사, 실패면 git 출력과 함께 종료 1, push 안 함 | `test_claim_fails_and_does_not_push_when_hook_rejects_commit` 외 1 |
| F-09 | 됨 — stage돼 있던 `secret.txt`가 선점 커밋에 섞임 | 선점 자기 파일만 `git commit -- <paths>`, 다른 stage는 그대로 | `test_claim_commit_excludes_unrelated_staged_file` 외 1 |
| F-10 | 됨 — `G-1000-*.md`만 있어도 G-100 선점, `status: done` 골도 선점 | 골 파일 ID 경계 일치 + 머리 주석 `status: active` 필수. 브랜치 이름 검사도 경계 일치로 | `test_claim_rejects_id_prefix_of_other_goal`, `test_claim_rejects_inactive_goal`, `test_claim_rejects_branch_with_longer_id` |
| F-11 | 됨 — `- [x] G-0012 …`가 G-001 완료 줄로 인정 | `has_id()` 경계 일치. 같은 부분 문자열 버그가 있던 WORKLOG 제목·INDEX 줄·`[~]` 잔존 검사 3곳도 같이 | `test_check_record_rejects_done_line_of_longer_id` |
| F-05 | 됨 — Codex 실패 뒤 옛 `r1.txt`의 `VERDICT: CONFIRM`을 그대로 출력·종료 0 | `review.run_codex`: 실행 전 옛 출력 삭제, 종료코드≠0 또는 빈 출력이면 `.failed`로 바꾸고 종료 1(판정·`r<N>.tree` 안 씀). 같은 종류인 `goal_gate.run_codex`도 종료코드≠0이면 빈 결과(감사 범위 밖에서 발견) | `ReviewCodexFailureTest` 4개 |
| F-06 | 됨 — `Revert any old unrelated work`·`Merge my stuff`가 골 검사 통과 | merge는 `MERGE_HEAD`가 있을 때만(commit-msg 훅 실행 중 존재 확인), revert는 본문 `This reverts commit <hex>`이고 그 커밋이 실제로 있을 때만 면제. 남은 틈: 실제 커밋을 인용한 가짜 revert 꼬리말 | `RevertMergeBypassTest` 5개 |
| F-07 | 됨 — bare 원격의 두 clone이 둘 다 G-002 | `reserve_id`: origin이 있고 `id_reserve`가 remote면 `refs/vibe-ids/G-*` 원자 push 예약(D·L 번호와 같은 hindex 도우미 사용), 다른 push 실패는 발급 거부. 원격 없음·scan 모드는 종전대로 | `GoalIdRemoteReserveTest` 3개 |
| F-12 | 됨 — 기존 commit-msg 훅이 덮임 | 남의 훅은 `commit-msg.local`로 옮기고 새 훅이 먼저 실행(실패하면 중단). 그 자리가 차 있으면 거부, 재설치 멱등 | `InstallHookTest` 3개 |
| F-14 | 됨 — 빈 폴더·없는 경로가 `0/0 통과`·종료 0 | 대상 .js/.mjs가 0개면 「미검증」·종료 2 | `SyntaxCheckEmptyTest` 3개(node 없으면 건너뜀) |
| F-13 | 됨 — 머리말만 있는 DECISIONS.md를 migrate하면 본문 파일 없음·verify 실패 | 블록이 없고 머리말이 있으면 이번 달 본문 파일로 옮기고 INDEX 「본문:」에 연결. 블록이 있을 때는 원래 첫 본문 파일에 보존됨(시험으로 확인) | `test_header_only_decisions_survive_migration`, `test_header_kept_when_there_are_blocks` |
| F-15 | 됨 — GitLab 원격인데 gh 결과 사용, gh 실패 시 glab 미호출 | 원격 URL로 순서 결정(gitlab이면 glab 먼저), 종료코드 0인 결과만 쓰고 실패하면 다른 도구 | `RemoteMrsTest` 3개 |
| F-16 | 됨 — 같은 날 `feat/G-123-a`·`-b` 착수 표시가 하나로 합쳐짐 | 중복 제거 키에 브랜치 포함 | `ClaimKeyTest` 2개 |
| F-17 | 됨 — 두 번째 archive가 `ui-2026-10.md`를 다시 보관 | `<토픽>-YYYY-MM[-n].md`이고 `<토픽>.md`가 옆에 있으면 활성 토픽에서 제외(부모 없는 `sprint-2026-10.md`는 활성 유지) | `ArchiveTopicTest` 2개 |

## 3. 구현 평가 (감사 원문 요약)

| 관점 | 지적 | 감사자 분류 | 이번 처리 |
|---|---|---|---|
| 중복 | git subprocess 구현이 vf_git·goal_gate·hindex에 분산 | 구조 변경 | 골 후보 — 모듈 재구성은 이번 런의 「하지 말 것」 |
| 중복 | 변경 파일 겹침 계산이 goal_gate·dupe에 중복 | 구조 변경 | 골 후보 |
| 중복 | 골 ID 처리가 dupe·goal_gate·handoff·mr_check에 분산 | 구조 변경 | 골 후보 — 이번엔 F-04·F-10·F-11로 각 자리의 경계 일치만 고침. 공용 파서는 후보 |
| 과대 파일·함수 | hindex.py에 이전·검증·보관·점검·번호 발급 혼재, `migrate` 한 함수가 너무 큼 | 구조 변경 | 골 후보 — 감사자 권고(plan → validate → apply → verify 분리, `hindex/` 패키지)를 그대로 후보로 |
| git 호출 | 실패를 빈 stdout처럼 처리 | 구조 변경 | 부분 고침 — 실패가 게이트를 잘못 통과시키던 자리(claim 커밋 F-08, Codex 실행 F-05)만 반환코드 검사. `vf_git.git()` 자체의 예외화는 골 후보 |
| git 성능 | 브랜치마다 반복 git 호출 | 국소 | 골 후보 — 정확성 영향 없음, 측정 먼저 |
| Windows | Codex 실행 방식·반환코드 처리가 goal_gate·review에서 다름 | 국소 | 이번에 고침 — 두 곳 모두 종료코드≠0이면 판정 없음 |
| 경로 | git 파일명을 `splitlines()`로 파싱(-z 미사용) | 구조 변경 | 골 후보 — 개행 든 파일명에서만 깨짐 |
| 경로 | 설정 경로와 git 경로 구분자 혼용 | 국소 | 골 후보 — 재현 사례 없음(테스트는 Windows에서 실행) |
| 개행 | handoff가 `splitlines()` 뒤 LF로 다시 씀 | 국소 | 골 후보 — 팀 레포는 `.gitattributes`로 정규화 |
| 인코딩 | stdout 전체를 UTF-8로 가정 | 구조 변경 | 골 후보 |

## 4. 재검토 (A4) — 고친 코드를 감사자가 다시 봄

수정마다 감사자에게 「수정 전→후 diff + 수정 후 전체 파일 + 새 테스트」를 보내 해소 여부와 **수정이 만든 새 결함**을 받았다. 새 결함도 같은 방식(재현 → RED → 수정 → GREEN)으로 처리했다.

| 차수 | 기존 결함 판정 | 새 결함 | 처리 |
|---|---|---|---|
| 1차 | 17건 중 해소 8 · 부분 해소 9 | N-01~N-06 (blocker 6) | 아래 표 |
| 2차 | 직전 15건 중 해소 11 · 부분 해소 4 | M-01~M-07 (blocker 7) | 아래 표 |
| 3차 | M-01·M-05·M-07·F-12 해소, M-02·M-03·M-04·M-06 부분 해소 | K-01~K-05 (blocker 5) | 아래 표 |
| 4차 | K-01·K-04·K-05 등 해소, K-02·K-03 부분 해소 | J-01~J-09 (게이트 증거 연결 쪽 새 경로) | 아래 표 |
| 5차 | J 9건 중 해소 4 · 부분 해소 5 | H-01~H-05 (blocker 5) | 런 5에서 처리 — 아래 「5차 처리」 |
| 6차 | H 5건 중 해소 4 · 부분 해소 1(H-04) | G-01~G-08 (blocker 7 · major 1) | 아래 「6차 처리」 |
| 7차 | G·H·J 11건 중 해소 6 · 부분 해소 5 | E-01~E-05 (blocker 5, 모두 새 clone 재검증 쪽) | 아래 「7차 처리」 |
| 8차 | E 5건 중 해소 4 · 부분 해소 1 | B-01~B-06 — B-01은 오판(감사 입력에 review.py가 빠짐; review.py는 conds·contract를 기록함), B-02~B-06 처리 | 아래 |

| ID | 내용 | 처리 |
|---|---|---|
| N-01 | 본문에 `This reverts commit <실제 sha>`만 넣으면 아무 변경이나 골 검사 면제 | staged 변경이 인용 커밋의 역변경과 같을 때만 면제(이후 M-01로 강화) |
| N-02 | 실행 권한 없던 기존 훅을 체인해 모든 커밋이 `Permission denied` | 생성 훅은 `[ -x ]`일 때만 `.local` 실행 |
| N-03 | 라운드 재실행 실패 뒤 옛 `r1.tree`만으로 2라운드 진행 | 라운드 완료 = VERDICT 있는 출력 + tree 둘 다, 재실행 전 그 라운드 이후 결과 무효화 |
| N-04 | 머리말만 있는 DECISIONS migrate가 기존 월 파일을 덮어씀 | migrate가 만들 파일을 먼저 계산, 하나라도 있으면 아무것도 바꾸지 않고 중단 |
| N-05 | 보관 파일 제외가 lint 색인 검사까지 빠뜨림 | 보관 대상(활성)과 검사 대상(보관 포함) 목록 분리 |
| N-06 | 골 상태를 첫 HTML 주석에서만 읽어 유효한 골 거부 | goal_gate와 같은 규칙(`field()`)으로 |
| F-04·F-11 잔여 | `G-123abc`가 G-123로 일치 | 경계 `(?![0-9A-Za-z])` |
| F-01 잔여 | merge 검사가 추적 중인 무시 파일을 QA 비교에서 뺌 | **정책으로 유지(결함 아님 근거):** 무시 대상은 빌드 산출물로 선언된 파일이다. 테스트 실행이 추적 중인 `.pyc`를 다시 써서 QA tree와 영원히 안 맞던 실제 사례(1회차 두 에이전트가 우회)를 막는 장치이고, 제외할 때마다 경고와 `git rm --cached` 정리 골 후보 안내를 낸다. 감사자는 "부분 해소"로 남김 |
| F-07 잔여 | `id_reserve: scan` 모드는 유일성 보장 없음 | 정책: 사용자가 명시적으로 고르는 원격 없는 발급 방식(문서화됨) |
| M-01 | 공백만 다른 가짜 revert가 patch-id로 면제 | patch-id 제거. 임시 인덱스에 HEAD + 인용 커밋 역diff 정확 적용 → 그 tree가 staged tree와 같을 때만 면제 |
| M-02 | `CHECKED: arbitrary` 반복으로 근거 검사 통과 | 완료 조건 1..N 번호, `CHECKED: <n> — 근거`가 n마다 정확히 한 번 |
| M-03 | 체크박스 없는 완료 조건 항목은 미체크로 안 셈 | 모든 항목이 `[x]`여야 merge |
| M-04 | 이전 골의 `d1.meta`·`r1.tree`가 새 골을 막거나 통과시킴 | 기록에 골 ID, 같은 골만 인정(이후 K-05로 브랜치·base까지) |
| M-05 | `예상 100000줄·999파일`도 생략 허용 | 예상치를 파싱해 design_skip 기준과 비교 |
| M-06 | 개인 모드에서 `docs/` 아래 코드가 크기에서 빠짐 | `is_record`를 기록 파일만으로(이후 K-03으로 정확한 파일명), QA 대상 비교도 같은 함수 |
| M-07 | `check-record --commit`이 현재 브랜치 골까지 요구 | `--commit`이면 그 커밋 메시지의 골 ID만 |
| F-12 잔여 | 남의 훅에 `goal_gate.py` 문자열만 있어도 우리 훅으로 오인 | 생성기가 쓰는 정확한 표식 줄 또는 이전 생성본 전문 일치만 |
| K-01 | 리뷰와 merge의 완료 조건 파서가 달라 번호 목록이 리뷰 근거에서 빠짐 | 공용 `completion_items()` 하나 |
| K-02 | 목록 없는 서술형 완료 조건으로 merge 통과 | 항목 1개 이상, 목록 밖 서술은 형식 오류 |
| K-03 | `docs/PLANET.md`가 PLAN 접두어로 기록 취급 | 정확한 파일명 + hindex가 만드는 분할·보관 파일명 패턴만 |
| K-04 | `예상 ,줄`에서 ValueError로 중단 | 숫자 패턴 `\d+(?:,\d{3})*`, 형식 오류는 검사 결과로 |
| K-05 | 같은 골의 다른 브랜치·rebase 전 리뷰 결과 재사용 | 기록에 골·브랜치·base(merge-base tree), 하나라도 다르면 무효(재실행) |
| J-01 | 내용 없는 `- [x]` 항목이 완료 조건으로 인정 | 빈 항목은 오류 |
| J-02 | 아무 `PLAN-*.md`나 기록으로 제외 | `PLAN-body(-N).md` 또는 PLAN.md가 링크한 분할 파일만 |
| J-03 | test_cmd가 바뀌어도 옛 성공 기록으로 QA 통과 | 기록의 cmd가 현재 test_cmd와 같아야 |
| J-04 | `.txt`도 브라우저 캡처로 인정 | 이미지·영상 확장자만 |
| J-05 | `{"exit": 0}`만 있는 qa json이 기록 검사 통과 | tree·cmd·exit 필수, tree가 커밋된 MR 「QA 결과」 대상과 일치 |
| J-06 | 리뷰 뒤 완료 조건을 바꿔도 옛 확정 재사용 | 리뷰 기록에 완료 조건 해시, 다르면 재리뷰 |
| J-07 | 리뷰 tree를 못 읽는 git 오류가 「변경 없음」으로 통과 | 읽기·비교 실패는 오류 |
| J-08 | qa_run import 실패 시 QA 증거 검사 생략(fail-open) | 검증기 없음 = 머지 금지(fail closed) |
| J-09 | 없는 `D-999`로 사람 판정 예외 | DECISIONS에 `## D-nnn` 블록이 있고 골 ID를 담아야 |

품질 평가(C1)에서 나온 게이트 지적도 같은 방식으로 고쳤다: 설계·리뷰 「판정: 확정」을 실제 Codex 기록(`d<N>.txt`·`r<N>.txt`, VERDICT CONFIRM·blocker 없음)과 대조, CONFIRM인데 blocker FINDING이 있으면 무효, 리뷰 확정 뒤 코드가 바뀌면 재리뷰 요구, QA 「코드: 통과」는 `qa_run.py` 실행 기록(종료코드·tree)과 대조하고 기록 커밋에 `<핸드오프>/mr/G-###-qa.json`, 브라우저 증거는 실제 파일 존재 확인.

### 5차 처리 (런 5 — 각각 실패 테스트 먼저, tests/test_r5_*.py)

| ID | 내용 · 처리 |
|---|---|
| H-01 | 「QA 결과」의 HTML 주석 안 SHA를 QA 대상으로 고름 → `qa_run.target()` 하나(주석 제거 뒤 파싱)를 handoff·qa_run·mr_check가 공용 |
| H-02 | 골 둘을 묶은 MR의 증거 export 실패 → 나열된 골마다 G-###.md·-qa.json·-review.md |
| H-03 | 다른 브랜치 리뷰 원문 export → 스탬프(골·브랜치·base)가 지금과 맞는 라운드만 |
| H-04 | 커밋된 MR 사본과 지금 MR이 달라도 DONE → 「골·완료 조건·제외 범위」 정규화 해시 비교 |
| H-05 | 「없음(…위험 설명)」으로 설계 생략 → 정확히 「없음」만 |

**감사 경과 요약:** 1차 17건 → 수정마다 재감사 → 새 결함 6 → 7 → 5 → 9 → 5건. 새로 나오는 결함은 점점 좁은 경계 사례(주석 속 값, 다중 골, 문자열 「없음」 뒤 설명)로 옮겨 갔지만 0으로 수렴하지는 않았다. 게이트를 「텍스트 확인」에서 「실제 증거 대조」로 바꿀 때마다 새 대조 경로가 생겨 그 경로의 경계가 다시 결함이 됐다.

**런 5에서 함께 넣은 것(품질 평가 감점 대응):** 리뷰 지적 장부(2·3라운드 CONFIRM은 열린 blocker·major ID가 모두 RESOLVED여야, major만 CARRY 가능 · mr_check가 장부 재계산), 3라운드 뒤 사람 판정 재개 계약(유효 r3 + 결정 블록이 골·열린 blocker ID 전부, 설계는 유효 d2 필수), `handoff.py verify-evidence`(새 clone에서 커밋된 파일만으로 재검증, 변조 7가지 FAIL 시험), precheck 착수 가능 점검(git·python·codex·test_cmd), 강도 프로필(금액·권한·데이터·외부 계약 표식이면 테스트 이름·「- 회귀:」 필수), QA 테스트 개수 자동 기록. E2E에서 드러난 `candidate --help` 후보 생성·lint의 `x](말)` 링크 오탐도 실패 테스트 먼저 고침.

### 6차 처리 (런 5)

| ID | 내용 | 처리 |
|---|---|---|
| G-01 | QA 대상 tree는 어떤 커밋에서도 닿지 않아 새 clone에 없음 → 정상 기록도 verify-evidence FAIL | 객체가 없으면 기록 커밋에서 재구성(기록 파일만 부모 판으로 되돌린 tree) → QA tree와 비교. `git clone --no-local` 시험 |
| G-02 | verify-evidence가 마지막 VERDICT만 봄 | 리뷰 원문의 라운드 전부로 장부(blocker·major) 재계산, 사람 판정이면 결정 블록이 열린 ID를 적어야 |
| G-03 | `RESOLVED: 없음 (F1 미해결)`을 F1 해결로 읽음 | RESOLVED는 정확히 「없음」 또는 ID 목록, 그 밖은 형식 오류(리뷰 무효·merge 차단) |
| G-04 | qa·merge 장부가 blocker만 | blocker·major 모두(major는 CARRY로만 닫힘) |
| G-05 | 「사람 결정:」 줄 없이 사람 판정 통과 | 줄 항상 필수, 「없음」은 열린 지적이 없을 때만 |
| G-06 | python이 없어도 착수 가능 | python·python3·py 중 하나 없으면 착수 불가 |
| G-07 | 강화 프로필이 「테스트는 나중에」「회귀: 예정」 통과 | 테스트 식별자 필수, QA 「회귀:」 식별자는 레포 테스트 파일에 실재해야 |
| G-08 | 건너뛴 테스트를 통과로 셈 | 통과·전체·건너뜀 따로, `2/3 통과(1 건너뜀)` |

함께: H-04 잔여(「사용자 가치」도 계약 해시에), J-05 잔여(check-record도 qa json cmd를 커밋된 test_cmd와 대조), J-06 잔여(완료 조건 해시 없는 옛 리뷰 기록은 재실행 요구).

### 7차 처리 (런 5)

| ID | 내용 | 처리 |
|---|---|---|
| E-01 | 새 clone 재검증이 커밋 안 된 PLAN.md로 기록 파일을 분류 | is_record가 커밋된 PLAN.md 내용을 받음 |
| E-02 | 영속 증거에서 리뷰 대상 tree·완료 조건·계약 해시를 대조 안 함 | export가 회차마다 스탬프(tree·골·브랜치·base·conds·contract·code_tree)를 남기고, verify가 결정 회차의 해시를 커밋된 MR과·리뷰 tree의 코드를 QA 코드 tree와 대조 |
| E-03 | 설계 확인(dN) 기록만으로 코드 리뷰 인정 | `## rN.txt` 회차만 코드 리뷰로, 없으면 FAIL |
| E-04 | MR 골 ID 불일치·빈 완료 조건을 놓침 | 빈 항목 FAIL, 검증하는 골 ID가 커밋된 MR 「골」에 있어야 |
| E-05 | 새 clone에서 3라운드·재개 계약 없이 사람 판정 통과 | 유효 r3 + 「사람 결정」 줄(로컬과 같은 decision_cover) + 줄의 tree = r3 tree |
| G-01 잔여 | QA 전에 바뀐 기록까지 되돌려 재구성이 어긋남 | qa_run이 기록 파일을 뺀 `code_tree`를 저장, verify는 커밋에서 같은 방식으로 계산해 비교(옛 기록만 재구성) |

함께: G-07 잔여(테스트 존재는 정의만 — 주석 속 이름 불인정), G-08 잔여(전부 건너뜀은 실패), J-05 잔여(커밋된 설정에 test_cmd 없으면 check-record 실패).

### 8차 처리 (런 5)

| ID | 내용 | 처리 |
|---|---|---|
| B-01 | review.py가 계약 해시를 안 씀 | 결함 아님 — `review.py`가 r<N>.tree에 `conds:`·`contract:`, d<N>.meta에 `design:`을 씀. 감사 입력 diff에서 review.py를 빠뜨린 탓 |
| B-02 | 전부 건너뜀인데 exit 0이면 증거로 재사용 | qa 기록에 `ok`(exit 0이고 전부 건너뜀 아님), verify·check-record·verify-evidence가 ok 요구 |
| B-03 | 다른 파일의 같은 이름 테스트로 회귀 통과 | 한정된 식별자는 전체 접미 일치 |
| B-04 | 새 clone 검증이 스탬프의 골을 안 봄 | 결정 회차 스탬프 goal에 검증 골 포함 필수 |
| B-05 | r3 하나만 있어도 사람 판정 통과 | r1·r2·r3 연속 필수 |
| B-06 | 명령 오류도 RED로 기록 | 파싱된 실패 테스트 1건 이상만 RED |

함께(품질 평가 C4 대응): 「미검증·생략 항목」이 「없음」이 아니면 사람 승인(D-nnn) 없이는 merge 차단, 추적 중인 무시 파일도 비교(빌드 산출물만 예외), 표준·강화 프로필은 RED 증거(구현 전 실패 → QA에서 통과한 테스트) 필수, UI 캡처를 `<핸드오프>/mr/G-###-evidence/`로 내보내고 새 clone에서 존재 확인.

## 5. 런 6 — 단일 판정 엔진 뒤 재감사 (Aside ChatGPT 추론 High, 새 대화)

런 6 변경: verify-evidence를 별도 검사 묶음에서 **재연(replay)**으로 바꿈 — 커밋된 증거로 임시 clone에 `.vibe/`를 되살려 로컬과 같은 `mr_check --stage merge`. 증거 판 `EVIDENCE_SCHEMA=2`(낮은 판은 LEGACY, 종료 3), 상태 셋(UNVERIFIED·ACCEPTED-RISK·POLICY-PENDING — 모두 차단), CHECKED 근거 실재 검사·근거 테스트 실행 대조, RED의 골·기준 결속. 이식 중 드러난 빈틈(r3 하나만 남긴 사람 판정 — 단일 엔진이 마지막 회차만 봄)은 `[1, 2, 3]` 요구로 막음(설계 d1·d2도).

| 차수 | 직전 지적 | 새 지적 | 처리 |
|---|---|---|---|
| 9차 | B-02~B-05 해소, B-06 부분 해소 | A9-01~A9-10 (blocker 5 · major 5) | 아래 |

### 9차 처리 (런 6 — tests/test_r6_audit9.py, 이식 시험 tests/test_r6_engine.py)

| ID | 심각도 | 내용 | 처리 |
|---|---|---|---|
| A9-01 | blocker | 빈 값·`<…>` 자리표시 미검증·미확인 줄이 통과 | `_items`가 정확한 `없음`만 빈 것으로, 빈 값·자리표시는 UNVERIFIED·POLICY-PENDING 줄 자체로 |
| A9-02 | blocker | 없는 테스트 이름으로 해소, 부분 문자열로 다른 항목 결정 재사용, 결정 블록이 항목을 안 적어도 닫힘 | 해소 근거는 실재 + QA 기록에서 ok인 테스트 또는 실재 파일:줄, 항목은 정규화 전체 일치, 결정·위험 인수 블록에 그 항목이 있어야 |
| A9-03 | blocker | `미충족 — <없는 id>` + CONFIRM, r1 CHECKED 삭제로 근거 대조 회피 | review.py: 미충족은 그 응답의 FINDING id, CONFIRM과 동시 불가. qa·merge: r1 CHECKED가 완료 조건 1..N을 한 번씩, 형식, 미충족 FINDING은 뒤 라운드 RESOLVED로 닫혀야 |
| A9-04 | blocker | 없는 tree + 지금 코드의 code_tree를 적은 위조 QA·리뷰 기록으로 재연 통과 | 재연이 기본으로 커밋된 코드에서 test_cmd를 다시 돌려 통과·수·테스트별 결과·코드 tree를 기록과 대조(`--no-rerun`은 「실행 사실 미확인」 표시). 리뷰 원문 자체의 위조는 Codex 출력 텍스트라 기계로 증명 못 함 — 남은 한계로 기록 |
| A9-05 | major | 명령 오류도 RED 파일로 남음, GREEN 뒤 RED도 증거 | RED는 실패 테스트를 찾았을 때만 기록(`red_valid`), merge는 GREEN보다 먼저 돈 RED만 |
| A9-06 | major | 로컬은 옛 RED로 통과, export는 최신 RED만 → 재연 FAIL | `mr_check.select_red` 하나를 merge·export가 같이 씀(로컬이 고른 RED를 커밋) |
| A9-07 | major | 추적 중인 .pyc만 바뀌면 로컬 통과·재연 FAIL | `qa_run.code_tree`가 `tracked_artifact`도 뺌(code_diff와 같은 제외 집합). 시험 중 임시 index `git rm --cached` 거부 결함도 드러나 `update-index --force-remove`로 |
| A9-08 | blocker | 0건 실행·수를 못 읽는 출력이 QA 통과 | `qa_run.ok`가 읽은 수(통과 ≥ 1, 전체 > 0) 요구, syntax_check 출력(`[syntax] N/M 통과`)도 수로 읽음 |
| A9-09 | major | r1·r2를 지운 r3 CONFIRM으로 장부 회피 | 일반 확정도 유효 라운드가 r1부터 연속 |
| A9-10 | major | 낮은 판 증거를 로컬은 통과, 재연은 LEGACY | 로컬 merge도 `schema_problems`(설계·리뷰 기록·QA 기록 판) |

RED 확인: 이 차수는 수정과 회귀 시험을 같은 묶음으로 썼다 — 수정 전 코드에서 실패를 따로 돌려 보지 않았다(시험 18개는 수정 뒤 통과). A9-07의 임시 index 결함은 시험이 처음 실패해 드러났다.

| 10차 | A9 해소 6 · 부분 해소 4(A9-03·04·05·06) | A10-01~A10-08 (blocker 3 · major 4 · minor 1) | 아래 |

### 10차 처리 (런 6 — tests/test_r6_audit10.py)

| ID | 심각도 | 내용 | 처리 |
|---|---|---|---|
| A10-01 | blocker | merge가 CHECKED 근거의 실재·표준 프로필 테스트 이름을 다시 보지 않음 | `checked_complete_problems`가 조건마다 마지막 근거에 `checked_ref_problems(need_test=프로필≠경량)` |
| A10-02 | blocker | r1 '미충족'이 RESOLVED만으로 닫히고 실행 근거는 생략 | `checked_map`: '미충족'을 닫는 라운드가 그 조건의 새 CHECKED 근거를 달아야 하고, 그 근거 테스트가 QA에서 ok(`checked_tests`가 마지막 근거). review.py 2·3라운드 CHECKED도 같은 근거 규칙, 프롬프트에 명시 |
| A10-03 | blocker | 재실행 없는 검증이 종료 0 | `verify-evidence`: 재실행 없으면 UNPROVEN(종료 4, 통과 아님), 0은 `--run-tests` 재실행 일치일 때만 |
| A10-04 | major | 고른 RED가 없어도 예전 -red.json 사본이 남아 재연이 다르게 판정 | export가 지금 고른 RED가 없으면 사본 삭제 |
| A10-05 | major | 초 단위 started 문자열 비교로 같은 초의 RED→GREEN 거부 | started 마이크로초, `_before`가 시각으로 비교 |
| A10-06 | major | 수만으로(수집 오류 포함) RED 인정 | `red_valid`는 실패한 테스트 이름 1개 이상 필수, GREEN에 테스트별 결과가 없으면 RED→GREEN 연결 불가 |
| A10-07 | major | 제3자 검증이 커밋의 test_cmd를 자동 실행 | 재실행은 `--run-tests`로 명시했을 때만, 재연 merge 통과 뒤에만, 환경변수 허용 목록(`RUN_ENV`). OS 격리는 하지 않음 — 믿지 않는 코드는 격리된 환경에서(문서) |
| A10-08 | minor | exit 0·수 없음인데 MR 코드 줄 '통과' | 줄 문구도 `qa_run.ok` 기준 |

| 11차 | A10 해소 6(A10-07은 정의된 신뢰 범위 안) · 부분 해소 2(A10-01·02 — 사람 판정 경로), A9 잔여 해소 3 · 부분 1(A9-03, 같은 원인) | A11-01~A11-05 (blocker 1 · major 3 · minor 1) | 아래 |

### 11차 처리 (런 6 — tests/test_r6_audit11.py)

| ID | 심각도 | 내용 | 처리 |
|---|---|---|---|
| A10-01·02·A9-03 잔여 | blocker | 사람 판정 경로가 CHECKED 근거 검사를 건너뜀 | `human_review`도 `checked_complete_problems` — 결정 줄의 ID는 '미충족' 지적만 닫고, 완료 조건마다 실재 근거·QA 대조는 그대로 |
| A11-01 | major | Jest/Vitest 실패 출력에서 RED 불가(이름 파싱 없음, 전부 실패 수 파싱 실패) | `parse_tests`에 jest(`--verbose`, 파일 › describe › 이름, 실패 요약 ●)·vitest(`--reporter=verbose`, 파일 > … > 이름), jest·vitest 수 파서가 'passed' 없는 줄도 |
| A11-02 | major | r2 이후의 '미충족'(minor라 장부 밖)이 RESOLVED 없이 사라짐 | `checked_map`이 모든 라운드의 조건별 이력을 추적 — 어느 라운드의 미충족이든 그 라운드 FINDING, 뒤 RESOLVED, 그 뒤 새 근거 |
| A11-03 | major | 테스트가 실행 중 코드를 바꿔도 통과(재실행 대조 포함) | `qa_run.run`이 실행 전·후 코드 tree(기록·산출물 제외)를 비교 — 바뀌면 ok false·`changed_code`, RED로도 안 받음. 재실행 대조는 같은 qa_run을 쓰므로 같은 판정 |
| A11-04 | blocker | 커밋된 QA 기록 tree 값('../..')으로 재연이 바깥 파일을 덮어씀 | 재연이 쓰기 전에 QA·RED tree를 40자리 16진수로 검증, 도장 branch도 `check-ref-format --branch`·'-' 시작 금지 |
| A11-05 | minor | 수만 실패를 알리는 출력에서 RED CLI IndexError | main도 `red_valid` 하나로 판정, 명시적 거부 메시지 |

| 12차 | 사람 판정 경로·A11-03·A11-05 해소, A11-01·A11-02·A11-04 부분 해소 | A12-01 (major 1) | 아래 |

### 12차 처리 (런 6 — tests/test_r6_audit12.py)

| ID | 심각도 | 내용 | 처리 |
|---|---|---|---|
| A11-01 잔여 | major | JS/TS 테스트 이름을 근거·존재 확인·실행 대조가 못 알아봄(_test_files가 `*.test.ts` 제외) | `JS_TEST_ID`(jest '파일 › 묶음 › 이름', vitest '파일 > …'), `test_exists`가 그 파일의 `it/test('이름')`, `test_match`는 구분자 무관 전체 일치, `_test_files`가 `*.test|spec.*` 포함 |
| A11-04 잔여 | blocker | 커밋에 든 `.vibe`(심볼릭 링크)를 따라 재연이 바깥에 씀 | 재연은 clone에 `.vibe`가 이미 있으면(링크 포함) 쓰기 전에 FAIL, 새로 만든 뒤 실제 경로가 clone 안인지 확인 |
| A12-01 | major | 미충족 → 근거 → RESOLVED 순서도 통과(닫히기 전 근거를 사후 승인) | `checked_map`: 지적이 열려 있는 동안 단 근거는 확정 근거가 아님(같은 라운드는 RESOLVED가 먼저). 사람 판정은 결정 시점이 기록 밖이라 미충족 뒤 근거를 받되 실재·QA 대조는 그대로. 2·3라운드 CHECKED 번호 범위도 merge에서 재검사 |

기타: 셸 heredoc의 백슬래시 처리로 스크립트에 제어 문자(\b·\1)가 들어간 편집이 한 번 있었다 — 전 파일 제어 문자 0 확인 뒤 고침(LESSONS 8회째).

| 13차 | 12차 열린 3건 모두 해소 | A13-01·A13-02 (major 2) | 아래 |

### 13차 처리 (런 6 — tests/test_r6_audit13.py)

| ID | 심각도 | 내용 | 처리 |
|---|---|---|---|
| A13-01 | major | 사람 판정으로 받은 최종 근거가 QA 실행 대조에서 빠짐(checked_tests가 결정 ID를 모름) | `human_closed_ids(text)` 하나로 결정 ID를 구해 `checked_complete_problems`·`checked_tests`(→`checked_run_problems`)가 같은 최종 근거를 씀 |
| A13-02 | major | 쉼표·괄호가 든 JS 테스트 이름을 잘라 다른(통과한) 테스트로 대체 | JS 식별자는 파일부터 칸(';'·줄 끝) 끝까지, 끝의 '(파일:줄)'만 뗌 — 이름 중간에서 자르지 않고 전체 일치 |

| 14차 (S1 60aed2d) | A13-01 해소, A13-02 부분 해소(';'에서 잘림) | A14-01 (major 1) | 아래 |

### E2E S1 결함과 14차 처리 (tests/test_r6_e2e_s1.py)

S1로 돌린 E2E 4건(t3w1·t3w2·t4w1·t4w2)이 모두 숨은 문제 없이 구현·QA까지 갔지만 merge 검사에서 같은 이유로 막혔다 — 에이전트들은 게이트를 고치거나 우회하지 않고 멈춰 결정 대기로 보고했다(흐름 의도대로). S1은 무효, S2에서 4건을 다시 돌린다.

| ID | 출처 | 내용 | 처리 |
|---|---|---|---|
| S1-E1 | E2E 4건 | 리뷰 근거 `Class.test_x (tests/test_a.py:62)`의 괄호 속 파일 경로까지 테스트 이름으로 뽑아 'QA 기록에 없음' — 프롬프트가 요구한 형식 그대로인데 merge 차단 | RED(`test_file_line_is_not_a_test_id`) 확인 → `test_ids`가 '파일:줄'을 지운 뒤 이름을 뽑음 → GREEN |
| S1-E2 | t4w1 | 미확인 문구 속 쉼표가 한 항목을 둘로 쪼갬 | 상태 항목 구분을 ';'로(`ITEM_SPLIT`), 템플릿·qa-gate 표기 |
| A13-02 잔여 | 14차 | JS 이름 속 ';'에서 잘림 | 한 식별자는 다음 JS 식별자 시작 전까지(사이 구분자만 뗌), 마지막은 줄 끝에서 '(파일:줄)'만 뗌 |
| A14-01 | 14차 major | 결정 블록에 없는 지적 ID를 MR 결정 줄만으로 닫음 | `human_closed_ids`가 결정 줄 ID ∩ 결정 블록에 적힌 ID |

| 15차 (S2 9b9b916) | A13-02 잔여·A14-01·S1-E1·S1-E2 해소 | A15-01·A15-02 (major 2) | 아래 |

### 15차 처리 (tests/test_r6_audit15.py — 실패 3건 확인 뒤 수정)

| ID | 심각도 | 내용 | 처리 |
|---|---|---|---|
| A15-01 | major | '정책 A; <정책 B>'의 자리표시를 나누기 전에 지워 B의 미결이 사라짐 | `_items`가 먼저 ';'로 나누고 항목마다 — 빈 항목·자리표시가 하나라도 있으면 그 줄 자체가 미결 |
| A15-02 | major | JS 테스트 제목 안에 다른 JS 식별자 문자열이 있으면 둘로 쪼개져 건너뛴 테스트가 통과로 대체 | 한 줄에 JS 식별자는 하나(첫 시작부터 줄 끝, 끝 '(파일:줄)'만 뗌). '- 회귀:'는 줄 여럿(`regression_ids`) |

E2E S2(t3x1·t3x2·t4x1·t4x2): 셋은 merge·`verify-evidence --run-tests`까지 통과(과제 3 숨은 테스트 12/12 ×2). t4x1은 「미확인: ADR에 법인 할인 포함 여부」를 POLICY-PENDING으로 막고 사람 결정을 요청하며 정지 — 상태 셋이 의도대로 작동. A15 수정으로 판이 바뀌어 S3로 4건 다시.
