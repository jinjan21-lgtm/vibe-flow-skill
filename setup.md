# 처음 설치 (레포마다 1회)

먼저 모드를 정한다 — [docs/structure.md](docs/structure.md). `docs/handoff/`(team-handoff)가 있으면 팀 모드, 아니면 개인 모드.

## 개인 레포 (session-handoff, `docs/`)

```bash
S=~/.claude/skills/vibe-flow
mkdir -p docs/goals && cp $S/templates/NORTHSTAR.md docs/ && cp $S/templates/G-000-maintenance.md docs/goals/
python $S/scripts/goal_gate.py install-hook
echo '.vibe/' >> .gitignore                 # MR 본문·리뷰 기록 등 로컬 작업 파일
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

`.gitattributes`에 `docs/handoff/WORKLOG/*.md merge=union`을 더한다(토픽 파일도 여러 사람이 줄을 추가함). `.gitignore`에 `.vibe/`를 더한다(MR 본문·리뷰 기록·이전 스냅숏 등 로컬 작업 파일 — 개인 레포도 같음). 각 참여자는 복제 후 한 번 `python .claude/skills/vibe-flow/scripts/goal_gate.py install-hook`을 실행한다(훅은 커밋되지 않는 로컬 설정).

team-handoff `SKILL.md`, `CLAUDE.md`, `AGENTS.md`에는 골 ID 표기와 `handoff.py precheck/claim/check-record` 호출 지점을 넣는다 — 형식은 structure.md의 표 그대로.

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
| `test_cmd` | - | QA 코드 단계 명령 |
| `dev_url` | - | QA 브라우저 단계 주소 |
| `ui_globs` | tsx·jsx·vue·css·html·pages·routes·components | 브라우저 QA 필수·디자인시스템 참조 판정 |
| `design_system` | `docs/design-system.md` | 디자인시스템 문서 |
| `design_skip` | `{"max_lines": 50, "max_files": 3}` | 이 이하면 설계 확인 생략 가능 |
| `claim_days` | 7 | 착수 표시 유효 기간 |
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
