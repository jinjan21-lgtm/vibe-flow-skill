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
