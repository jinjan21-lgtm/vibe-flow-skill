# 경직성 점검 — 스크립트가 강제하는 규칙의 분류

근거: [논의](debates/2026-10-17-handoff-index-skills.md) F5·F6·F7. 원칙은 셋이다.

- **기계 강제** — 관측 가능한 불변식, 그리고 LLM이 압박에 밀리는 지점(앞선 압박 시험에서 실제로 밀린 것: 기록을 나중에, QA를 오래된 커밋에, 리뷰 라운드 추가). 사용자가 판정한 규칙(골 판정, 리뷰 최대 3라운드, 리뷰·QA 분리, UI 변경 시 Aside, 우회는 사용자 직접, 기록은 작업과 같은 커밋)은 **전부 여기**에 둔다.
- **LLM 판단** — 의미를 봐야 하는 것. 스크립트는 막지 않고 경고하거나, "판단을 적었는지"만 본다(판단 위임).
- **설정으로 조정** — 레포마다 다른 정책. `.vibe-flow.json`.

막힐 때는 `mr_check.py`가 메시지 아래에 **다음 행동**(준수 경로)을 붙인다. lint는 빠진 INDEX 줄을 **붙여 넣을 수 있는 형태로** 출력한다.

## 분류표

| # | 규칙 | 어디서 | 분류 | 이유 |
|---|---|---|---|---|
| 1 | 커밋 메시지·브랜치에 활성 골 ID | goal_gate check-commit | 기계 강제 | 사용자 판정(골 판정). 골 없는 작업이 가장 흔한 이탈 |
| 2 | 골 생성은 Codex 판정(CREATE)만 | goal_gate judge | 기계 강제 | 사용자 판정. 작업 에이전트는 자기 골에 관대 |
| 3 | 노스스타 draft면 판정 거부 | goal_gate judge · vf_git.northstar_status | 기계 강제 | 사용자 확정이 먼저. **인덱스 구조에서 INDEX만 보고 confirmed로 오판하던 구멍을 고침**(본문 주석을 본다) |
| 4 | 같은 골 이중 선점 차단 | dupe.find · handoff claim | 기계 강제 | 동시 작업 불변식. 논의 F14(범위 단위 선점)는 수요가 확인되면 — 정보 격차로 남김 |
| 5 | 비슷한 일·비슷한 MR·파일 겹침 | dupe.find | LLM 판단(경고) | 유사도는 의미 판단. 「계획 vs 실제」에 판단을 적게 함 |
| 6 | 브랜치 접두사 | mr_check · claim | 설정 `branch_prefixes` | 레포 규칙 |
| 7 | MR 「설계」 5요소가 채워짐 | mr_check draft | 기계 강제(형식) + LLM 판단(내용) | 칸이 비었는지만 기계가 본다. 설계 타당성은 Codex 설계 확인이 판단 |
| 8 | MR 제목·라벨 이름(「설계」「접근 방식」…) | mr_check · review | **설정 `mr_labels` (이번에 바꿈)** | 한국어 제목이 코드에 박혀 있어 영어 템플릿·다른 제목에서 깨졌다. 별칭을 기본 이름으로 바꿔 같은 검사를 쓴다 |
| 9 | 설계 확인 '확정' 전 build 금지 | mr_check build | 기계 강제 | 구현 전에 설계를 확정한다는 흐름의 핵심(사용자 요구) |
| 10 | 설계 확인 최대 2회 → 사람 판정 | mr_check · review --design | 기계 강제 | 끝없는 재설계 방지, 넘으면 사람 |
| 11 | 설계 생략은 작은 변경만, 커지면 차단 | mr_check review | 기계 강제 + 설정 `design_skip` | 생략 남용 방지. 크기 기준은 레포마다 |
| 12 | 400줄·10파일 넘으면 경고 | mr_check size_warning | LLM 판단(경고) + 설정 | MR 분할은 판단 |
| 13 | 「계획 vs 실제」 채움 | mr_check review | 기계 강제(형식) | 내용 적절성은 리뷰가 판단 |
| 14 | 리뷰 '판정: 확정', 최대 3라운드, 건너뛰기 금지, 3라운드는 고친 파일만 | mr_check qa · review --round | 기계 강제 | 사용자 판정(리뷰 최대 3라운드) |
| 15 | QA 대상 = 지금 작업물(스냅숏 tree), 기록·골 파일만 예외 | mr_check merge | 기계 강제 | 사용자 판정(리뷰·QA 분리) + 오래된 커밋 QA가 실제로 압박에 밀림 |
| 16 | UI 파일 변경 시 브라우저 통과 + 캡처 | mr_check merge | 기계 강제 + 설정 `ui_globs` | 사용자 판정(UI 변경 시 Aside) |
| 17 | **글롭에 안 걸린 코드 변경의 UI 영향** | mr_check merge | **LLM 판단 위임 (이번에 바꿈)** | 예전에는 글롭 미일치 = UI 없음으로 **조용히 통과**했다. 이제 브라우저 줄에 「해당 없음 — 이유」를 적어야 통과(닿으면 Aside). 글롭은 보조 신호. 끄려면 `ui_unclear_needs_reason: false` |
| 18 | base가 앞서 가면 리베이스 후 QA | mr_check merge | 기계 강제 | QA 대상 불변식 |
| 19 | 기준 이후 노스스타 변경 → 골 재판정 | mr_check merge | 기계 강제 | **팀 모드 경로(`docs/handoff/NORTHSTAR.md`)를 못 보던 버그를 고침**(`docs/NORTHSTAR.md` 고정이었다) |
| 20 | 기록은 작업과 같은 커밋(WORKLOG·INDEX·REMAINING) | handoff check-record | 기계 강제 | 사용자 판정 |
| 21 | 새 본문 항목의 INDEX 줄도 같은 커밋 | handoff check-record (인덱스 구조) | 기계 강제 | 20의 연장. 누락되면 INDEX가 stale |
| 22 | 작성자 `@user.name`, 앵커 `-작성자` | check-record | 기계 강제(형식) | 다인 협업에서 grep·충돌 회피 |
| 23 | D-nnn·L-nnn 번호 원격 예약, 실패 시 발급 거부 | handoff next-id | 기계 강제 + 설정 `index.id_reserve` | 독립 복제본 간 번호 중복은 사람이 못 막음. 원격 없이 발급하는 우회 `--scan-only`는 사용자 직접 |
| 24 | INDEX↔본문 불일치·끊긴 링크·union 중복 줄 | handoff lint | 기계 강제(오류) | 관측 가능한 불변식 |
| 25 | 임계값 초과·완료 잔존·시작 읽기량 초과 | handoff lint · precheck | 설정 `index.*` (경고) | 숫자는 운영값(논의 F2). 막지 않고 `archive`를 안내 |
| 26 | 결정 INDEX 대체 관계 vs 본문 상태 줄 어긋남 | handoff lint | LLM 판단(경고) | 본문 상태 줄은 사람이 고치는 텍스트, 어느 쪽이 맞는지 판단 필요 |
| 27 | 착수 표시 7일 만료 | dupe · precheck | 설정 `claim_days` | 팀 리듬 |
| 28 | 코드 QA 명령 | qa-gate · syntax_check | 설정 `test_cmd` | 레포마다 |
| 29 | Codex 응답에 VERDICT 없으면 중단 | review · goal_gate | 기계 강제 | 판정 없이 통과로 세지 않는다 |

## 이번에 고친 곳 (스크립트가 LLM 판단·설정이 맞는 것을 막고 있던 곳)

| # | 전 | 후 | 시험 |
|---|---|---|---|
| 8 | MR 제목·라벨이 한국어로 고정 — 영어 제목이면 「비어 있음」으로 차단 | `mr_labels` 별칭 | `FlexibilityTest.test_english_headings_via_mr_labels` |
| 17 | 글롭 미일치 = UI 없음 자동 통과 (판단이 없는데 통과 — 반대 방향의 경직) | 이유를 적는 판단 위임 | `FlexibilityTest.test_code_outside_ui_globs_needs_a_reason_not_silent_pass` |
| 3 | 인덱스 구조에서 노스스타 INDEX에 상태 주석이 없으면 confirmed | 본문 주석을 본다 | `IndexStructureTest.test_northstar_draft_is_read_through_index` |
| 19 | 노스스타 변경 감지가 개인 모드 경로 고정 | 설정 경로 + 본문 | 기존 `test_merge_flags_northstar_change_on_base` |
| 전체 | 차단 메시지만 출력 | 「다음 행동」 준수 경로 | `test_code_outside_ui_globs…`의 `다음 행동` |
| 25 | (새 규칙) 임계값을 오류로 막을 수도 있었다 | 경고 + archive 안내 | `test_archive_moves_done_old_lines_and_big_topic_keeping_links` |

## 바꾸지 않은 것과 이유

- 사용자 판정 규칙(1·2·14·15·16·20)은 표현·강도를 그대로 뒀다. 17은 16을 약화하지 않고, 16이 놓치던 경우를 판단 위임으로 덮는다.
- 4(같은 골 이중 선점)는 GPT가 범위 단위를 제안했지만(논의 F14), 지금은 같은 골 병행 수요가 관찰되지 않았다. 합류·골 나누기 경로가 안내된다.
- 파이썬을 없애거나 LLM 지시문으로 옮기지 않았다. 경직성의 원인은 "무엇을 막느냐"였다(논의 F6).
