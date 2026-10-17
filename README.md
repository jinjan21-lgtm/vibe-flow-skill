# vibe-flow

바이브코딩(AI 에이전트가 코드를 쓰는 개발)을 위한 Claude Code 스킬입니다. 에이전트가 **할 일을 스스로 넓히는 것**과 **다 됐다고 스스로 판정하는 것**을 막기 위해, 판단을 바깥에 둡니다 — 골·설계·리뷰는 Codex가, 머지 가능 여부는 QA 증거와 스크립트가 정합니다.

```
/vibe-flow            전체 흐름(오케스트레이터)
/vibe-review          리뷰만 — 진입 조건을 먼저 검사
```

## 원칙

- **골 ID 없는 작업은 시작하지 않는다.** 모든 브랜치·커밋·PR에 `G-###`. 골은 노스스타와 대조해 Codex가 판정(CREATE/REJECT/MERGE)하고, 노스스타가 초안이면 판정하지 않습니다.
- **선점이 탐색보다 먼저.** 착수 표시를 push한 뒤에만 코드를 읽어 여러 세션의 중복 작업을 막습니다.
- **구현 전에 설계 확인.** MR 본문 「설계」 다섯 칸을 Codex가 확인(최대 2회)해야 구현 단계로 넘어갑니다.
- **리뷰는 Codex 최대 3라운드, QA는 별개.** QA는 지금 작업물(미커밋 포함)에서 하고, 화면이 바뀌면 브라우저 확인과 캡처가 필수입니다.
- **기록은 작업과 같은 커밋.** 핸드오프 기록(작업 이력·남은 일·결정)과 그 인덱스 줄까지 한 커밋에 들어가야 합니다.
- **우회는 사용자가 직접.** 에이전트는 게이트를 넘는 명령을 대신 실행하지 않습니다.

## 흐름과 세부 스킬

| 단계 | 세부 스킬 | 넘어가는 조건 |
|---|---|---|
| 사전체크 · 골 확인 · 선점 | `vibe-claim` | 선점 push 확인 |
| 탐색 · 설계 · 설계 확인 | `vibe-design` | `mr_check --stage build` |
| 구현 (프론트엔드·백엔드·풀스택 프로필) | `vibe-dev` | `--stage review` |
| 리뷰 (Codex 최대 3라운드) | `vibe-review` | `--stage qa` |
| QA (코드 + 화면이면 브라우저) | `vibe-qa` | 「QA 결과」 |
| 기록 · 머지 | `vibe-record` | `check-record` + `--stage merge` |

`vibe-flow`(오케스트레이터)는 `python scripts/mr_check.py <mr> --next`로 지금 단계를 찾아 세부 스킬을 차례로 부릅니다. 세부 스킬을 따로 불러도 같은 진입 조건을 검사하므로, 진입점이 여러 개라고 단계 생략 권한이 생기지 않습니다. 개발 유형(기능·API·풀스택·버그·리팩터링·긴급·설정·테스트 보강)별 차이는 [docs/task-types.md](docs/task-types.md).

## 핸드오프 기록과 인덱스 구조

기록 형식은 핸드오프 스킬(팀: `docs/handoff/` — [team-handoff-skill](https://github.com/jinjan21-lgtm/team-handoff-skill), 개인: `docs/`)과 같습니다 — [docs/structure.md](docs/structure.md). 기록이 커진 대형 프로젝트는 **인덱스 구조**로 옮깁니다.

```
docs/handoff/INDEX.md   진입 인덱스 → 문서별 INDEX(PLAN·DECISIONS·LESSONS·NORTHSTAR·goals·WORKLOG) → 본문
```

- 세션 시작에는 INDEX만 읽습니다(목표 12,000자). 결정은 시작에 읽지 않고 화면·모듈 태그로 찾습니다(`grep "#HOME-01" DECISIONS.md`).
- 본문은 옮기기만 하고 고치지 않습니다. 옛 경로는 INDEX가 되어 기존 링크가 그대로 닿습니다.
- 결정·교훈 번호(`D-nnn`·`L-nnn`)는 `handoff.py next-id`가 모든 브랜치와 원격 예약(`refs/vibe-ids/*`)을 보고 발급해, 여러 사람이 같은 날 기록해도 겹치지 않습니다.

```bash
python scripts/handoff.py migrate                 # 예전 구조 → 인덱스 구조 (원본 스냅숏)
python scripts/handoff.py verify-migration <스냅숏>  # 무손실 검증 + 읽기량 이전/이후
python scripts/handoff.py lint | archive | precheck | next-id D
```

어떤 규칙을 기계가 막고, 어떤 것을 판단·설정에 맡기는지는 [docs/flexibility.md](docs/flexibility.md).

## 구성

| 파일 | 내용 |
|---|---|
| `SKILL.md` | 오케스트레이터 — 흐름, 골 규칙, 무인 실행 멈춤 조건, 우회 지시 처리 |
| `skills/vibe-*/SKILL.md` | 단계별 세부 스킬 6개 |
| `profiles/` | 프론트엔드·백엔드·풀스택 구현 지침 |
| `review-loop.md` · `qa-gate.md` | 설계 확인·리뷰 3라운드 규칙, QA 절차 |
| `setup.md` | 레포마다 처음 설치, 설정 키(`.vibe-flow.json`) |
| `templates/` | 노스스타, G-000, MR 본문, 설계·리뷰 프롬프트, 디자인시스템 |
| `scripts/` | `goal_gate.py`(골 판정·커밋 훅) · `handoff.py`·`hindex.py`(선점·기록·인덱스) · `mr_check.py`(단계 검사) · `review.py`(Codex 설계 확인·리뷰) · `dupe.py`(중복·겹침) · `syntax_check.py` |
| `docs/` | 공통 구조, 아키텍처, 동시 작업 충돌, 결정 기록, 토론 기록, 사례 조사 |
| `tests/test_scripts.py` | 스크립트 회귀 테스트 (임시 git 레포·로컬 bare 원격 2인 시나리오 포함) |

## 설치

```bash
git clone https://github.com/jinjan21-lgtm/vibe-flow-skill ~/.claude/skills/vibe-flow
# 세부 스킬을 스킬 목록에 따로 보이게
for s in ~/.claude/skills/vibe-flow/skills/*; do ln -s "$s" ~/.claude/skills/$(basename "$s"); done
```

Windows는 `New-Item -ItemType Junction`(setup.md). 팀 레포는 `.claude/skills/` 아래에 사본을 두어 모든 참여자가 같은 버전을 씁니다. 레포마다 처음 할 일(노스스타·G-000·커밋 훅·설정)은 [setup.md](setup.md).

준비물:

1. **Python 3.10+**, **git**
2. **Codex CLI** — 골 판정·설계 확인·리뷰에 씁니다(`codex exec`).
3. **핸드오프 스킬** — 팀 레포는 [team-handoff](https://github.com/jinjan21-lgtm/team-handoff-skill)를 `.claude/skills/team-handoff/`에 함께 둡니다.
4. **브라우저 QA** — 화면 변경 확인용. [qa-run](https://github.com/jinjan21-lgtm/qa-run-skill)의 Aside 캡처 도구를 씁니다.

## 검증

- `python -m unittest tests/test_scripts.py` — 73개(골 판정·단계 검사·리뷰 라운드·선점·기록·인덱스 이전 무손실·번호 원격 예약·2인 같은 날 기록 병합 등)
- 스킬 문서는 [superpowers:writing-skills](https://github.com/obra/superpowers) 방식(RED 기준선 → GREEN → REFACTOR)으로 서브에이전트 시험을 거쳤습니다: 단계 스킬 단독 호출, 오케스트레이터 무인 진행, 개발 유형 8개, 바뀐 규칙별 재시험. 실제 팀 레포(비공개) 이전에서 결정 100여 건 무손실, 세션 시작 읽기량 약 54,000자 → 9,500자.

- **개발 퀄리티 실험** — 같은 요청을 vibe-flow 있음/없음 에이전트가 실제로 구현해 숨은 테스트로 채점: [tests/quality-record.md](tests/quality-record.md). 명확한 작은 일은 품질 차이 없이 약 6배 느리고, 요청서와 운영값이 충돌하는 일에서는 대조군이 혼자 결정해 요청을 어긴 반면 vibe-flow는 설계 확인에서 멈춰 사람 결정을 받은 뒤 전부 맞는 코드를 냈다.

## License

MIT
