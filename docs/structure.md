# 공통 구조 — vibe-flow × team-handoff × session-handoff

세 스킬이 같은 형식을 쓴다. vibe-flow는 **흐름**(골·선점·설계·리뷰·QA·머지)을, 핸드오프 스킬은 **기록**(PLAN·REMAINING·WORKLOG·LESSONS·DECISIONS)을 맡는다. 둘이 만나는 곳은 골 ID와 착수 표시다.

## 모드

| 모드 | 판별 | 핸드오프 폴더 | 작성자 표기 | 기록 시점 |
|---|---|---|---|---|
| 팀 (team-handoff) | `.claude/skills/team-handoff/` 또는 `docs/handoff/` 존재 | `docs/handoff/` | `@git user.name` 필수 | 작업과 **같은 커밋** |
| 개인 (session-handoff) | 위가 없고 `docs/PLAN.md` 등 존재 | `docs/` | 생략 | 태스크 완료 즉시 |

`.vibe-flow.json`의 `handoff_dir`로 덮어쓸 수 있다. `scripts/handoff.py detect`가 판별 결과를 보여 준다.

## 위치

| 무엇 | 팀 | 개인 |
|---|---|---|
| 노스스타 | `docs/handoff/NORTHSTAR.md` | `docs/NORTHSTAR.md` |
| 골 | `docs/handoff/goals/G-###-<slug>.md` | `docs/goals/` |
| 골 후보 | `…/goals/candidates/` | 같음 |
| 사람이 내린 결정 | `docs/handoff/DECISIONS.md` (D-nnn) | `docs/` 아래 결정 문서 |
| 골 판정(Codex) | 골 파일의 `judge:` 줄 | 같음 |
| 디자인시스템 | `docs/design-system.md` (설정 `design_system`) | 같음 |
| 설정 | `.vibe-flow.json` | 같음 |

노스스타 첫 줄 주석에 `status: draft | confirmed`. **draft면 `judge`가 판정하지 않는다** — 사용자가 확정해야 골을 만들 수 있다.

## 골 ID가 들어가는 곳

| 어디 | 형식 | 예 |
|---|---|---|
| 브랜치 | 팀: `<접두사>/G-###-<주제>` — 접두사 필수(`.vibe-flow.json`의 `branch_prefixes`, 파일럿 팀 레포는 `docs·design·proto·plan·research·chore`) / 개인: `G-###-<주제>` 또는 `G-###/<주제>` | `proto/G-012-vendor-search` |
| 커밋 | 메시지 어딘가에 `G-###` (훅이 검사) | `G-012 거래처 검색 API` |
| PR/MR 제목 | `G-### <골 제목>` | `G-012 거래처 이름 부분 검색` |
| REMAINING 할 일 | `- [ ] G-### 할 일 → 링크` (골이 없으면 ID 없이) | |
| REMAINING 착수 | `- [~] G-### 할 일 (착수 @작성자 YYYY-MM-DD) → <브랜치 또는 PR>` | `- [~] G-012 거래처 검색 (착수 @jinjan21 2026-10-17) → proto/G-012-vendor-search` |
| REMAINING 완료 | `- [x] G-### 할 일 (@완료자 YYYY-MM-DD)` | |
| WORKLOG 항목 제목 | `## YYYY-MM-DD G-### 한 줄 제목 @작성자 #tag {#YYYY-MM-DD-slug-작성자}` | |
| INDEX 한 줄 | `- YYYY-MM-DD [topic] @작성자 G-### 한 줄 요약 → [topic.md#anchor](…)` | |

골과 무관한 기록(토의·결정 정리 등)은 지금처럼 ID 없이 쓴다. 동작이 바뀌지 않는 변경은 `G-000`.

## 흐름과 기록이 만나는 지점

| vibe-flow 단계 | 핸드오프 동작 | 명령 |
|---|---|---|
| 사전체크 | 읽을 순서대로 읽기, 다른 참여자 변경 요약, 7일 이내 착수 표시·결정 대기·보류·후보 확인 | `handoff.py precheck` |
| 선점 | fetch → 중복 검사 → 브랜치 → REMAINING 착수 줄 커밋 → push → **push 성공 확인 후에만 탐색** (거부 시 rebase 후 중복 재검사). 로컬 모드(`origin` 없음 또는 `"remote": false`)는 로컬 커밋만 — `선점(로컬 모드 — 원격 없음): <브랜치>@<sha>` | `handoff.py claim G-### "<할 일>" <브랜치>` |
| 구현·리뷰·QA | 기록 없음 (진행 상황의 원천은 PR/MR) | - |
| 보류·무인 멈춤 | REMAINING에 `- [ ] 결정: …` 또는 보류 사유 + PR 링크 | - |
| QA 뒤, 머지 전 | WORKLOG 토픽 항목 + INDEX 한 줄 + REMAINING `[x]` + MR 본문 사본 `<핸드오프>/mr/G-###.md`(「리뷰 기록」·「QA 결과」 포함)를 **작업과 같은 커밋**에. QA 결과를 보고 쓰므로 마지막 작업 커밋에 합친다(`git commit --amend`, 이미 push했으면 자기 브랜치에 `--force-with-lease`). 머지 검사는 QA 대상 커밋 이후 기록·골 파일만 바뀐 것을 허용한다 | `handoff.py check-record` (HEAD 한 커밋) |
| 머지 후 | 골 status `done`. base 기준으로 바꾸되, main 직접 커밋이 금지된 레포는 `chore/G-###-done` 브랜치의 PR로(골 파일만 바꾸는 커밋은 훅이 허용) | - |
| 실수 | LESSONS `(@작성자, 날짜)` | - |

## 인덱스 계층 (대형 프로젝트)

장문 프로젝트에서는 본문을 세션마다 읽지 않는다. **진입 인덱스 → 문서별 INDEX → 본문** 3단으로 찾아 들어간다. 근거: [논의](debates/2026-10-17-handoff-index-skills.md) F1·F9·F13.

```
docs/handoff/INDEX.md            진입 인덱스 — 문서마다 한 줄: INDEX 경로 · 무엇이 있나 · 언제 본문을 여나
├── PLAN.md                      INDEX ─→ PLAN-body.md
├── REMAINING.md                 활성 목록(그 자체가 INDEX) ─→ REMAINING-done-YYYY-MM.md
├── mr/G-###.md                  골별 MR 본문 사본(검증 증거). 세션 시작에 읽지 않음, 링크 검사 제외
├── DECISIONS.md                 INDEX ─→ DECISIONS-2026-10.md, DECISIONS-2026-10-2.md, … (결정 날짜의 달마다)
├── LESSONS.md                   INDEX ─→ LESSONS-body.md
├── NORTHSTAR.md                 INDEX ─→ NORTHSTAR-body.md
├── goals/INDEX.md               INDEX ─→ goals/G-###-<slug>.md
└── WORKLOG/INDEX.md             INDEX(최근 30줄) ─→ WORKLOG/<topic>.md, 지난 INDEX는 WORKLOG/INDEX-YYYY-MM.md
```

- **옛 경로가 INDEX가 된다.** `DECISIONS.md`·`PLAN.md`를 가리키던 링크는 그대로 INDEX에 닿고, INDEX에서 본문으로 간다.
- **본문 파일은 원래 파일과 같은 폴더에 둔다.** 본문 속 상대 링크(`../planning/…`)가 그대로 맞는다.
- **본문 텍스트는 이동만 한다.** 고치거나 줄이지 않는다. 통합·폐기·반영 같은 정리는 INDEX의 상태 표시로 한다.
- INDEX 첫 줄에 `<!-- vibe-index: <문서> -->`. 이 표식이 있는 문서만 새 규칙(check-record·lint)이 적용된다 — 아직 옮기지 않은 레포는 예전대로 동작한다.

### 문서별 INDEX 형식·분할·보관

| 문서 | INDEX 한 줄 | 본문 분할 | 보관(archive) | 세션 시작에 읽나 |
|---|---|---|---|---|
| PLAN | `- [섹션 제목](PLAN-body.md#앵커) — 한 줄 요약` | 본문 20,000자 초과 시 `##` 섹션 단위로 `PLAN-<slug>.md` | 변경 이력 행은 본문에 남긴다(보관 없음) | INDEX |
| REMAINING | 할 일 줄 자체(`[ ]`·`[~]`·결정 대기). 형식은 위 「골 ID가 들어가는 곳」 | 상세는 링크된 문서 | `[x]` 줄(들여쓴 하위 줄 포함)을 완료 월의 `REMAINING-done-YYYY-MM.md`로, 원래 소제목을 같이 적어 옮긴다 | 전부 |
| DECISIONS | `- D-nnn 제목 · YYYY-MM-DD · @결정자 · 유효 \| 대체됨→D-mmm · 대체 D-kkk · #태그 → [본문](DECISIONS-2026-10-2.md#앵커)` | **결정 날짜의 달마다 한 파일** `DECISIONS-YYYY-MM.md`(논의 F15). 한 달이 50건 또는 20,000자를 넘으면 같은 달 `-2`, `-3`. 새 결정은 이번 달 마지막 파일 끝에(`next-id`가 안내) | INDEX가 200줄을 넘으면 대체된 결정의 줄을 `DECISIONS-INDEX-replaced.md`로 | **아니오** — 탐색 단계에서 태그로 찾는다(`grep "#HOME-01" DECISIONS.md`) |
| LESSONS | `- L-nnn 한 줄 (N회) → [본문](LESSONS-body.md)` | 본문 30,000자 초과 시 `LESSONS-body-2.md` | 없음(교훈은 지우지 않는다). 절차에 반영된 교훈은 INDEX 줄 끝에 `· 반영: <문서>` | INDEX |
| WORKLOG | 기존 형식 `- YYYY-MM-DD [topic] @작성자 G-### 요약 → [topic.md#앵커](…)` | 토픽 파일 30,000자 초과 시 archive가 `<topic>-YYYY-MM.md`로 옮기고, 새 `<topic>.md`에 옛 앵커마다 넘김 앵커를 남긴다 | `INDEX.md`는 최근 30줄. 넘으면 오래된 줄을 그 달의 `INDEX-YYYY-MM.md`로 | INDEX(최근 30줄) |
| NORTHSTAR | `- [섹션](NORTHSTAR-body.md#앵커) — 한 줄` + status 주석은 본문에 그대로 | 분할 없음(10줄 안팎이 원칙) | 개정은 본문 개정 이력에 | INDEX |
| 골 | `- G-### 제목 · active \| done \| dropped · → [G-###-slug.md](G-###-slug.md)` | 골마다 파일 | done·dropped 줄은 `goals/INDEX-done.md`로(골 파일은 그 자리에) | INDEX(활성만) |

결정 INDEX의 `#태그`는 결정 블록에 나온 화면 ID(`HOME-01`, `ADM-04` …)와 「영향」 줄의 코드 이름(`#core.js`, `#calc.util`)이다(최대 8개). 태그가 "언제 본문을 여는가"의 신호다 — 지금 작업이 닿는 화면·모듈 태그가 있는 줄만 연다. 태그가 없는 주제는 INDEX 제목 grep → 본문 파일 grep 순으로 걸린 블록만 연다.

**결정의 유효 상태는 계산한다.** INDEX 줄은 추가만 하고 고치지 않는다(병합 충돌 방지). 새 결정 줄에 `대체 D-kkk`가 있으면 D-kkk는 그때부터 「대체됨」이다. 본문의 `상태` 줄도 팀 규칙대로 바꿀 수 있지만, lint는 둘이 어긋나면 알린다.

**임계값의 "자"는 문자 수다(바이트 아님 — 한글은 UTF-8로 3바이트라 `wc -c`는 약 1.5배로 나온다).** 크기 판단은 직접 재지 말고 `handoff.py lint`·`archive --dry` 출력을 따른다.

### 세션 시작 읽기량

**목표: 12,000자 이하**(진입 인덱스 + 위 표에서 "세션 시작에 읽나"가 INDEX·전부인 것). `handoff.py precheck`가 읽을 순서와 자 수 합을 보여 주고, 넘으면 무엇을 보관하면 되는지 알린다. 본문은 골이 정해진 뒤 INDEX에서 고른 것만 연다 — 이 양은 상한에 넣지 않는다. 숫자는 `.vibe-flow.json`의 `index` 키로 바꿀 수 있다(아래).

### 기록할 때 INDEX도 같은 커밋에

| 본문에 새로 쓴 것 | 같은 커밋에 들어가야 하는 INDEX 줄 |
|---|---|
| `## D-nnn` (DECISIONS 본문) | `DECISIONS.md`에 `D-nnn` 줄 |
| `L-nnn`이 든 교훈 줄 (LESSONS 본문) | `LESSONS.md`에 `L-nnn` 줄 |
| `## ` 섹션 (PLAN·NORTHSTAR 본문) | 그 INDEX에 섹션 앵커 줄 |
| WORKLOG 토픽 항목 | `WORKLOG/INDEX.md` 줄 (예전과 같음) |
| 새 골 파일 | `goals/INDEX.md`에 `G-###` 줄 |

`handoff.py check-record`가 검사한다(vibe-index 표식이 있는 문서만).

### 번호 발급 (D-nnn · L-nnn)

`handoff.py next-id D` — 작업 트리 + 모든 로컬·원격 브랜치 + 예약 장부 + 원격 예약 ref(`refs/vibe-ids/*`)를 훑어 다음 번호를 고르고, **원격이 있으면 `refs/vibe-ids/D-nnn`을 원자적으로 push해 예약한다**(이미 있으면 거부 → 다음 번호). 아직 push하지 않은 다른 복제본의 번호도 이것으로 막는다. 원격 예약이 실패하면 번호를 내주지 않는다 — 원격 없이 쓰는 우회(`--scan-only`)는 사용자가 직접 실행한다. 설정 `index.id_reserve: "scan"`이면 원격 예약을 하지 않는다(원격에 ref를 쓸 수 없는 레포).

### 상태의 원천

| 상태 | 원천 | 파생 표시 |
|---|---|---|
| 골 상태 | 골 파일 `status:` | goals/INDEX.md (lint가 대조) |
| 착수 | 원격 브랜치 + 원격 REMAINING의 `[~]` | 로컬 REMAINING |
| 결정 유효 | DECISIONS INDEX의 `대체` 관계 | 본문 `상태` 줄 |
| 단계(설계·리뷰·QA) | MR 본문 + 스냅숏 tree sha | - |
| 번호 | 원격 `refs/vibe-ids/*` + 전 브랜치 스캔 | 예약 장부 |

### 설정 (`.vibe-flow.json`의 `index`)

```json
{"index": {"start_budget": 12000, "decisions_per_file": 50, "body_max_chars": 20000,
           "topic_max_chars": 30000, "worklog_index_lines": 30, "decisions_index_lines": 200,
           "remaining_active_lines": 80, "id_reserve": "remote"}}
```

### 명령

| 명령 | 하는 일 |
|---|---|
| `handoff.py migrate` | 예전 구조를 새 구조로(본문 이동 + INDEX 생성 + 원본 스냅숏 `.vibe/migrate/<시각>/`) |
| `handoff.py verify-migration <스냅숏>` | 무손실 검증: 본문을 원래 순서로 다시 붙여 원본과 바이트 비교, 옮긴 줄의 순서·개수 |
| `handoff.py archive [--dry]` | 완료 항목·오래된 INDEX 줄·임계값 넘은 본문 이동(링크 유지). **다음 작업 커밋에서 그 작업의 기록을 쓰기 전에** 돌린다(lint는 HEAD 골의 방금 쓴 `[x]` — HEAD^에 없던 줄 — 은 잔존으로 경고하지 않는다) — 이동만 담은 커밋은 기록만 담은 커밋과 같아서 만들지 않는다 |
| `handoff.py lint` | INDEX↔본문 불일치, 끊긴 링크, 임계값 초과, 완료 잔존, 결정 상태 어긋남 |
| `handoff.py precheck` | 읽을 순서(INDEX만) + 자 수 합 + 기존 사전체크 |
| `handoff.py next-id D\|L` | 번호 발급(위) |

## 병합 충돌

`docs/handoff/REMAINING.md`, `LESSONS.md`, `WORKLOG/INDEX.md`, `DECISIONS.md`는 `.gitattributes`의 `merge=union`. 인덱스 구조에서는 추가로 `INDEX.md`, `goals/INDEX.md`, `WORKLOG/INDEX-*.md`, `DECISIONS-YYYY-MM*.md`, `LESSONS-body*.md`, `REMAINING-done-*.md`도 union이다(두 세션이 같은 본문 파일 끝에 결정을 붙여도 충돌하지 않게). union이 남긴 같은 번호·같은 줄 두 개는 lint가 잡는다. 골 파일은 골마다 다른 파일이라 충돌 가능성이 낮지만, 같은 골 파일을 두 브랜치가 고치면 충돌할 수 있다. 그래서 골 파일은 작업 브랜치에서 고치지 않고 status는 base에서만 바꾼다. 착수 표시가 7일 넘게 그대로면 누구든 다시 집을 수 있다 — 이때도 fetch와 중복 재검사를 거치고, 착수 줄을 교체하고 WORKLOG에 사유를 쓴다.
