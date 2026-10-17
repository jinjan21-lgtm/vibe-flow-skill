# 동시 작업 충돌 분석

여러 세션·worktree·에이전트(Claude, Codex)가 같은 레포에서 동시에 골을 진행할 때 생기는 충돌과 대응이다. 외부 근거: 에이전트 PR 33,596건을 분석한 연구(arXiv 2607.04697)에 따르면, 저장소의 40.2%에서 동시에 열린 에이전트 PR 쌍이 있었다. 서로 다른 에이전트끼리의 쌍은 41.7%가 충돌해, 같은 에이전트끼리(19.8%)의 두 배였다.

| # | 충돌 | 언제 생기나 | 대응 | 장치 | 확인 |
|---|---|---|---|---|---|
| 1 | **골 ID 중복 발급** | 두 worktree가 각자 `docs/goals` 최댓값+1로 번호를 정함 | 모든 로컬·원격 브랜치의 `docs/goals` + 공유 장부를 스캔하고, git 공통 폴더에 잠금 파일을 두고 예약. 원격(origin)이 있으면 `refs/vibe-ids/G-###`도 원자 push로 예약(push 안 한 다른 복제본과도 안 겹침, 실패 시 발급 거부, `index.id_reserve: "scan"`이면 끔) | `goal_gate.py reserve-id` (judge가 사용) | **재현함** (아래), 테스트 `test_concurrent_reservations_do_not_collide`, `test_two_clones_get_different_ids` |
| 2 | **같은 골을 두 곳에서 작업** | 사용자가 다른 세션에 같은 요청을 다시 함 | **작업 전 선점** 단계에서 같은 골의 다른 브랜치(로컬·원격)·열린 MR·다른 사람의 7일 이내 착수 표시가 있으면 차단 → 합류하거나 골을 나눈다(사용자 결정) | `handoff.py claim` → `dupe.py`, `mr_check --stage claim/draft` | 테스트 `test_claim_pushes_and_blocks_other_user`, `test_same_goal_on_other_branch_blocks_draft` |
| 3 | **비슷한 요청이 다른 골로 중복** | 같은 요구가 다른 표현으로 다시 들어옴 | 열린 MR 제목·본문과 골·사용자 가치 문장의 유사도 경고, 「계획 vs 실제」에 중복 아님 근거 기록 | `dupe.py` (gh/glab 있을 때) | 테스트 `test_remote_same_goal_blocks_and_similar_warns` |
| 4 | **같은 파일 경합** | 다른 골 브랜치가 같은 파일을 고침 | 겹침 경고 + `git merge-tree`로 실제 충돌 예측. 충돌이 예상되면 먼저 머지되는 쪽을 정하고 나중 쪽은 리베이스 후 QA | `dupe.py`, `goal_gate.py overlap` | 테스트 `test_file_overlap_warns_but_passes`, `test_conflicting_branch_is_predicted` |
| 5 | **리뷰·QA 대상과 머지 대상 불일치** | QA 뒤 nit 수정, 다른 세션이 같은 worktree에 쓰기, 미커밋 변경 | QA 대상(commit/tree)이 지금 작업물(미커밋 포함) 스냅샷과 같아야 머지 | `mr_check --stage merge` | e2e 18단계(한 줄 추가 → 차단), 테스트 `test_merge_fails_after_uncommitted_change` |
| 6 | **오래된 base 위의 QA** | 다른 MR이 먼저 머지돼 base가 앞서 감 | base에 이 브랜치에 없는 커밋이 있으면 머지 차단 → 리베이스 후 QA 재실행 | `mr_check --stage merge` | 테스트 `test_merge_blocked_when_base_moved` |
| 7 | **작업 중 노스스타 개정** | 사용자가 다른 세션에서 노스스타를 고침 | 브랜치 분기 뒤 base의 노스스타가 바뀌었으면 골을 다시 judge 받아야 머지 | `mr_check --stage merge` | 테스트 `test_merge_flags_northstar_change_on_base` |
| 8 | **골 상태 경합** | 두 브랜치가 같은 골 파일의 status를 다르게 바꿈 | 골 파일의 status는 judge(생성)와 머지 직후 base에서만 바꾼다. 작업 브랜치에서는 골 파일을 고치지 않는다 | 규칙 (SKILL.md 기록 위치) | 규칙만 |
| 9 | **리뷰 기록 파일 공유** | 두 세션이 같은 worktree에서 `review.py`를 돌림 | `.vibe/review/`는 worktree마다 따로. 한 worktree = 한 골 = 한 세션 | 규칙 | 규칙만 |
| 10 | **브라우저 QA 동시 실행** | 두 세션이 같은 Aside 브라우저로 QA | 각자 새 탭을 열고 `QA.key`를 골 ID로 해서 캡처 폴더를 나눈다. 로그인·역할 전환이 필요한 QA는 한 번에 하나만 | 규칙 (qa-gate.md) | 규칙만 |

### 팀 핸드오프 연동으로 추가된 유형

| # | 충돌 | 언제 생기나 | 대응 | 장치 | 확인 |
|---|---|---|---|---|---|
| 11 | **동시 선점 경쟁** | 두 세션이 거의 같은 순간 같은 골을 집음 | 선점 전에 fetch, 같은 이름 원격 브랜치가 있으면 차단. push가 거부되면 rebase 후 중복 재검사, 두 번 실패하면 멈춤. push 성공(원격 브랜치 = HEAD) 확인 뒤에만 탐색 | `handoff.py claim` | 테스트 `test_claim_pushes_and_blocks_other_user` |
| 12 | **오래된 착수 표시** | 착수한 사람이 일을 놓고 떠남 | `claim_days`(7일)이 지나면 차단 대신 경고. 다시 집을 때 착수 줄을 교체하고 WORKLOG에 사유 | `dupe.py` | 테스트 `test_stale_claim_only_warns` |
| 13 | **핸드오프 문서 병합 충돌** | 여러 브랜치가 REMAINING·INDEX·토픽 파일에 줄을 추가 | `.gitattributes` `merge=union`을 WORKLOG 토픽 파일까지 확대. 다른 참여자 줄은 고치지 않음(표시 변경만) | `.gitattributes` | 테스트 `test_union_merge_keeps_both_index_lines` |
| 14 | **기록 누락·분리** | 기록을 잊거나 따로 커밋함 | 한 커밋에 작업 + WORKLOG·INDEX·REMAINING `[x]`(QA 뒤 마지막 작업 커밋에 amend). 기록만 담은 커밋, 착수 `[~]` 잔존, 작성자·골 ID 누락을 거부. QA 대상 이후 기록만 바뀐 것은 머지 검사가 허용 | `handoff.py check-record`, `mr_check --stage merge` | 테스트 `test_check_record_*`, `test_records_amended_into_last_work_commit_after_qa`, `test_merge_allows_record_only_change_after_qa` |
| 15 | **초안 노스스타로 골 생성** | 노스스타가 아직 사용자 확정 전 | `status: draft`면 judge가 판정 거부 | `goal_gate.py judge` | 테스트 `test_judge_refuses_draft_northstar` |

## 재현: 골 ID 중복 발급 (1번)

worktree 두 개(`wt-a`, `wt-b`)에서 새 골 번호를 정했다.

```
== 예전 방식 (각 worktree의 docs/goals 최댓값+1)
wt-a G-001
wt-b G-001          ← 중복
== 지금 방식 (reserve-id, 두 worktree 동시 실행)
wt-a G-001
wt-b G-002
장부: G-001 G-002   ← .git/vibe-flow/goal-ids.txt (worktree 공유)
```

잠금 파일은 60초가 지나면 죽은 잠금으로 보고 지운다. 장부는 커밋하지 않는 로컬 파일이라, 다른 PC의 세션과는 원격 브랜치 스캔으로만 맞춘다. 같은 번호를 두 PC가 동시에 쓰면 먼저 push한 쪽이 이기고, 나중 쪽은 2번(`dupe`)에서 걸린다.

## 운영 규칙 요약

- 한 worktree = 한 골 = 한 세션. 브랜치 이름은 `G-###/<설명>`.
- 일을 집기 전에 `handoff.py claim`으로 선점한다. 같은 골·착수 표시·겹침·충돌은 이때 본다.
- 머지 직전에 base가 앞서 갔으면 리베이스하고 QA를 다시 한다.
