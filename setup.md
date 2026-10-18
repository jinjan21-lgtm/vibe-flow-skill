# 처음 설치 (레포마다 1회)

먼저 모드를 정한다 — [docs/structure.md](docs/structure.md). `docs/handoff/`(team-handoff)가 있으면 팀 모드, 아니면 개인 모드.

## 개인 레포 (session-handoff, `docs/`)

```bash
S=~/.claude/skills/vibe-flow
mkdir -p docs/goals && cp $S/templates/NORTHSTAR.md docs/ && cp $S/templates/G-000-maintenance.md docs/goals/
python $S/scripts/goal_gate.py install-hook   # 기존 commit-msg 훅은 commit-msg.local로 옮겨 먼저 실행
echo '.vibe/' >> .gitignore                 # MR 본문(.vibe/mr-G-###.md)·리뷰 기록 등 로컬 작업 파일. MR 본문을 레포 루트에 두지 않는다(QA 대상 비교가 깨짐)
echo '{"base":"main","test_cmd":"npm test","dev_url":"https://dev.example.com"}' > .vibe-flow.json
```

## 팀 레포 (team-handoff, `docs/handoff/`)

스킬을 레포에 팀 공용 사본으로 넣어 모든 참여자·에이전트가 같은 버전을 쓴다.

```bash
S=.claude/skills/vibe-flow                  # 이 폴더를 통째로 복사해 둔 위치
mkdir -p docs/handoff/goals
cp $S/templates/NORTHSTAR.md docs/handoff/   # 첫 줄 주석 status: draft — 사용자 확정 전엔 골 판정 불가
cp $S/templates/G-000-maintenance.md docs/handoff/goals/
cat > .vibe-flow.json <<'EOF'
{"base": "main",
 "branch_prefixes": ["docs", "design", "proto", "plan", "research", "chore"],
 "test_cmd": "python .claude/skills/vibe-flow/scripts/syntax_check.py docs/prototype",
 "dev_url": "http://127.0.0.1:8800/",
 "ui_globs": ["docs/prototype/**", "docs/design/*.html"]}
EOF
```

이 `test_cmd`는 문서·프로토타입만 있는 파일럿 레포용(구문 검사)이다. 경량 골만 merge할 수 있다 — 표준·강화(위험 표식)는 구문 검사만으로 merge하지 않는다. 코드와 테스트가 있는 레포는 테스트 러너를 상세 출력으로 넣는다: `"test_cmd": "python -m unittest discover -v"`(구문 검사도 원하면 `&&`로 잇는다).

`.gitattributes`에 `docs/handoff/WORKLOG/*.md merge=union`을 더한다(토픽 파일도 여러 사람이 줄을 추가함). `.gitignore`에 `.vibe/`를 더한다(MR 본문·리뷰 기록·이전 스냅숏 등 로컬 작업 파일 — 개인 레포도 같음). 각 참여자는 복제 후 한 번 `python .claude/skills/vibe-flow/scripts/goal_gate.py install-hook`을 실행한다(훅은 커밋되지 않는 로컬 설정).

team-handoff `SKILL.md`, `CLAUDE.md`, `AGENTS.md`에는 골 ID 표기와 `handoff.py precheck/claim/check-record` 호출 지점을 넣는다 — 형식은 structure.md의 표 그대로.

설치 확인: `python $S/scripts/handoff.py precheck --run-tests` — 마지막에 착수 가능성(git·python·리뷰어(codex, 없으면 claude) PATH, `test_cmd`, 기준 테스트 결과)이 나온다. 리뷰어는 면제 없이 필수(골 판정·설계 확인·리뷰) — Codex CLI가 없으면 Claude Code(`claude`)가 별도 프로세스로 맡는다, 추적 파일에 커밋 안 된 변경이 있어도 착수 불가다. `착수 불가`면 그 항목부터 고친다.

제3자 재검증(리뷰어·감사): 원격에서 새로 `git clone`한 뒤 `python <vibe-flow>/scripts/handoff.py verify-evidence G-### [--commit <기록 커밋>]`. 커밋된 증거만으로 임시 clone에 `.vibe/`를 되살려 로컬과 같은 merge 검사를 돌린다(재연 — qa-gate.md 「결과 등록」). `--run-tests`면 커밋된 코드에서 테스트도 다시 돌린다(커밋의 test_cmd 실행 — 믿는 코드만). 종료 코드: 통과 0(재실행 일치), 실패 1, 옛 판 증거 3(`LEGACY` — 재검증 대상), 재실행 안 함 4(`UNPROVEN` — 통과 아님).

## UI가 있는 레포

```bash
cp $S/templates/design-system.md docs/
```

토큰·컴포넌트 원천과 하지 않을 것을 채운다. 다른 경로에 두면 `.vibe-flow.json`에 `"design_system": "<경로>"`.

## 다른 에이전트도 같은 규칙을 보게 (AGENTS.md)

```markdown
## 작업 규칙 (vibe-flow)
- 제품 방향과 하지 않을 것: <핸드오프 폴더>/NORTHSTAR.md
- 모든 커밋·브랜치·PR 제목에 활성 골 ID(G-###)를 넣는다. 맞는 골이 없으면 코드를 쓰지 않는다.
- 일을 집기 전에 handoff.py claim으로 선점하고, 구현 전에 설계 확인을 받는다.
- UI 변경은 docs/design-system.md를 따른다.
```

## 설정 키 (.vibe-flow.json)

| 키 | 기본값 | 뜻 |
|---|---|---|
| `base` | `main` | 기준 브랜치. 커밋이 없는 실험에서는 tree sha |
| `branch_prefixes` | 없음 | 팀 레포 브랜치 접두사 규칙 (claim·mr_check가 검사) |
| `handoff_dir` | 자동 (`docs/handoff` 또는 `docs`) | 핸드오프 폴더 |
| `northstar` / `goals_dir` | `<핸드오프 폴더>/NORTHSTAR.md` / `<핸드오프 폴더>/goals` | 노스스타·골 위치 |
| `test_cmd` | - | QA 코드 단계 명령. 없으면 `precheck`가 착수 불가(exit 1). verbose 출력 권장(`python -m unittest -v`, `pytest -v`) — 테스트별 결과가 QA 기록 `tests`에 남아 회귀를 대조한다 |
| `dev_url` | - | QA 브라우저 단계 주소 |
| `ui_globs` | tsx·jsx·vue·css·html·pages·routes·components | 브라우저 QA 필수·디자인시스템 참조 판정 |
| `design_system` | `docs/design-system.md` | 디자인시스템 문서 |
| `reviewer` | `auto` | 골 판정·설계 확인·리뷰 LLM. `auto`: codex, 없으면 claude(`claude -p`, 읽기 전용). `codex`·`claude`로 고정하면 그것이 없을 때 착수 불가(다른 것으로 바꾸지 않음) |
| `claude_model` | 없음 | claude 리뷰어 모델(`--model`). 없으면 Claude Code 기본값 |
| `codex_effort` | `high` | 골 판정·설계 확인·리뷰의 Codex 추론 강도(이 호출에만 `-c model_reasoning_effort=`로 전달, `~/.codex` 설정은 그대로). `""`이면 Codex 기본값 |
| `design_skip` | `{"max_lines": 50, "max_files": 3}` | 이 이하면 설계 확인 생략 가능 |
| `claim_days` | 7 | 착수 표시 유효 기간 |
| `remote` | 자동 (`origin` 있으면 원격 모드) | `false`면 로컬 모드 — claim은 로컬 커밋만, next-id 원격 예약 안 함 |
| `max_lines` / `max_files` | 400 / 10 | review 단계 크기 경고 |
| `ui_unclear_needs_reason` | `true` | 글롭에 안 걸린 코드 변경이면 QA 브라우저 줄에 「해당 없음 — 이유」 필요 |
| `mr_labels` | 없음 | MR 제목·라벨 별칭. 예: `{"Design": "설계", "Approach": "접근 방식"}` |
| `index` | structure.md 「설정」 | 인덱스 구조 임계값·시작 읽기 목표·번호 예약 방식(`id_reserve`: `remote`·`scan`) |

## 세부 스킬 설치

vibe-flow는 오케스트레이터이고 단계마다 세부 스킬이 있다(`skills/`). 스킬 목록에 따로 보여야 단독으로 부를 수 있다.

```powershell
# 개인: 각 세부 스킬을 ~/.claude/skills/ 아래에 junction으로
$V = "<vibe-flow 원본 폴더>"
foreach ($n in "vibe-claim","vibe-design","vibe-dev","vibe-review","vibe-qa","vibe-record") {
  New-Item -ItemType Junction -Path "$HOME\.claude\skills\$n" -Target "$V\skills\$n" }
```

```bash
# 팀 레포: vibe-flow 사본 옆에 세부 스킬 사본을 둔다
for n in vibe-claim vibe-design vibe-dev vibe-review vibe-qa vibe-record; do
  cp -r .claude/skills/vibe-flow/skills/$n .claude/skills/; done
```

세부 스킬은 스크립트·규칙을 vibe-flow 폴더에서 찾는다(개인 `~/.claude/skills/vibe-flow`, 팀 `.claude/skills/vibe-flow`). 사본을 고칠 때는 원본과 같은 내용인지 `diff -r`로 맞춘다.

## 대형 프로젝트 — 인덱스 구조로 옮기기

핸드오프 문서가 커져 세션 시작 읽기량이 목표(12,000자)를 넘으면 한 번 옮긴다(`handoff.py precheck`가 자 수를 보여 준다). **넘지 않으면 옮기지 않는다** — 작은 레포에서는 INDEX 머리말 때문에 오히려 읽기량이 는다(시험: 263자 → 2,279자). 형식은 structure.md 「인덱스 계층」.

```bash
git checkout -b chore/G-000-handoff-index
python $S/scripts/handoff.py migrate                         # 원본 스냅숏 .vibe/migrate/<시각>/
python $S/scripts/handoff.py verify-migration .vibe/migrate/<시각>   # 무손실 + 읽기량 이전/이후
python $S/scripts/handoff.py lint
```

본문은 원래 폴더로 이동만 하고 고치지 않는다. 옛 경로(`DECISIONS.md` 등)는 INDEX가 되어 기존 링크가 그대로 닿는다. 옮긴 뒤 team-handoff `SKILL.md`·`CLAUDE.md`·`AGENTS.md`의 읽기 순서를 「INDEX만」으로 바꾼다.
