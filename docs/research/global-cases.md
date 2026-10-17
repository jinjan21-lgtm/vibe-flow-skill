# 해외 사례 조사 (2026-10-17)

검증 표시: **[V]** 원문을 직접 열어 봄 · **[S]** 검색 결과나 2차 자료로만 봄 · **[U]** 확인 못 함.
결정 기호: ✅ 채택(반영함) · ⏸ 보류 · ❌ 기각. 근거와 반영 위치는 [decisions.md](../decisions.md).

| # | 사례 | 출처 | 핵심 방식 | vibe-flow와의 차이 | 결정 |
|---|---|---|---|---|---|
| 1 | Claude Code 공식 모범 사례 [V] | https://code.claude.com/docs/en/best-practices | 탐색 → 계획 → 구현 → 커밋. 한 문장으로 설명되는 diff는 계획 생략. 에이전트에게 통과/실패 기준(테스트·화면 비교)을 주고 증거를 보이게 함. 훅은 결정적, CLAUDE.md는 권고. 새 맥락의 리뷰어. 병렬은 worktree | 같은 방향. vibe-flow는 리뷰어를 다른 모델(Codex)로 둠. 사소한 변경 경로는 G-000이 이미 맡음 | ❌ 사소한 변경 별도 경로(G-000으로 충분, 골 ID 필수는 사용자 결정) · ✅ 심각도별 차단(이미 있음) |
| 2 | GitHub Spec Kit [S] | https://github.com/github/spec-kit | `constitution.md`(원칙·품질 게이트) → `/specify` → `/plan`(헌법 대조) → `/tasks`(ID, 병렬 표시, 파일 경로) | 노스스타 = 헌법 역할. 태스크가 건드릴 파일을 미리 선언하지 않음 | ⏸ MR에 예상 파일 목록(`files:`) — 지금은 실제 diff로 겹침 검사 |
| 3 | AWS Kiro specs·steering·hooks [V: steering / S: specs·hooks] | https://kiro.dev/docs/steering/ · https://kiro.dev/docs/specs/index | 요구사항을 EARS 형식("WHEN … THE SYSTEM SHALL …")으로. steering 파일을 `fileMatch` 글롭으로 필요할 때만 로드. IDE 이벤트 훅 | 완료 조건이 자유 서술. 맥락 로드가 파일 범위로 나뉘지 않음 | ❌ EARS 강제(한국어 "관찰 가능한 결과"로 충분) · ✅ 파일 범위 로드 → UI 변경 시 디자인시스템 자동 포함 |
| 4 | AGENTS.md 표준 [S] | https://infoq.com/news/2025/08/agents-md/ | 레포 루트의 Markdown 하나를 Codex·Cursor·Gemini CLI·Aider 등이 읽음 | 규칙이 Claude 전용 스킬 안에만 있음. 리뷰어 Codex는 프롬프트로만 봄 | ✅ setup.md에 AGENTS.md 블록 추가 |
| 5 | OpenAI Codex 모범 사례 [S] | https://developers.openai.com/codex/learn/best-practices | 작업마다 격리 샌드박스, 병렬 분할. 같은 실수가 반복되면 회고해 AGENTS.md를 고침 | 리뷰 지적이 지속 규칙으로 돌아가지 않음 | ✅ 반복 지적 → 규칙화 (review-loop.md) |
| 6 | Shape Up (Basecamp) [V] | https://basecamp.com/shapeup/1.5-chapter-06 | 피치 = 문제·appetite(고정 시간 예산)·해법·rabbit holes·no-gos | 제외 범위(no-gos)와 위험은 있음. appetite·rabbit holes 없음 | ⏸ appetite 칸 — 실사용에서 범위 확장이 계속되면 도입 |
| 7 | Google 엔지니어링 관행: 작은 CL [V] | https://google.github.io/eng-practices/review/developer/small-cls.html | 한 CL에 한 가지. 100줄은 대체로 괜찮고 1000줄은 너무 큼. 리팩터와 동작 변경 분리. 스택 CL | MR 크기 기준 없음 | ✅ review 단계 크기 경고 (400줄·10파일) |
| 8 | Devin Playbooks [S] | https://docs.devin.ai/product-guides/creating-playbooks | 절차·사후 조건·조언·금지 행동·사용자에게 필요한 것 | 레포 단위 금지 행동 목록·사용자 의존 항목 칸 없음 | ⏸ 금지 행동은 디자인시스템·노스스타 하지 않을 것으로 일부 대체 |
| 9 | BMAD Method [S] | https://codemyspec.com/blog/bmad-method-explained | 역할 에이전트(분석·PM·설계·SM·개발)가 PRD·설계를 만들고 스토리 파일로 쪼갬 | vibe-flow가 더 가벼움 | ❌ 역할 오버헤드 |
| 10 | Cursor Project Rules [S] | https://www.stackhawk.com/blog/cursor-rules/ | `.cursor/rules/*.mdc` 글롭·항상 적용 등 4가지 활성 방식 | 3번과 같은 아이디어 | (3번에 포함) |
| 11 | Aider [S] | https://cursor-alternatives.com/blog/aider-rules/ | `CONVENTIONS.md` 읽기 전용 로드, architect(계획 모델)·editor(편집 모델) 분리 | 구현(Claude)·판단(Codex) 분리와 비슷 | ❌ 새로 얻을 것 없음 |

## 주제별 정리

### 디자인시스템 참조 (사용자 질문)

| 방식 | 출처 | 요지 |
|---|---|---|
| Figma MCP + Code Connect [S] | https://help.figma.com/hc/en-us/articles/35280968300439 | 프레임의 컴포넌트·변수·레이아웃을 에이전트에 구조화해 주고, Figma 컴포넌트를 실제 코드 컴포넌트에 연결 |
| Storybook MCP [S] | https://storybook.js.org/docs/ai | 컴포넌트 목록(props, 예시, 테스트)을 토큰 효율적으로 제공. React 전용, API 변동 가능 |
| DTCG 디자인 토큰 2025.10 [S] | https://www.designtokens.org/tr/2025.10/ | 벤더 중립 토큰 JSON 첫 안정판 |
| Claude Code 문서 [V] | (1번) | UI 변경은 스크린샷을 찍어 디자인과 비교하고 차이를 고침 |

→ **최소판 채택**: `docs/design-system.md`(토큰 원천, 쓸 컴포넌트, 하지 않을 것, 기준 화면) + UI 변경 시 구현 전에 읽기 + 리뷰 입력에 자동 포함 + QA 브라우저 단계에서 기준 화면과 비교. Figma·Storybook MCP가 있으면 문서에 그 위치만 적는다.

### 중복 MR·병렬 에이전트 충돌 (사용자 요청)

| 근거 | 출처 | 요지 |
|---|---|---|
| 에이전트 PR 충돌 연구 [V: 초록] | arXiv 2607.04697 | 40.2% 저장소에서 동시 에이전트 PR. 서로 다른 에이전트 쌍 충돌 41.7% vs 같은 에이전트 19.8%. 충돌 파일 84%가 소스 |
| 중복 PR 탐지 — 시간 요인 [S] | https://research.monash.edu/en/publications/duplicate-pull-request-detection-when-time-matters/ | 가까운 시간에 열린 PR이 중복일 가능성이 큼 |
| 제목·설명 NLP [S] | https://scitepress.org/PublishedPapers/2025/132890 | 이슈와 PR을 함께 보면 중복을 더 잘 잡음 |
| 병합 충돌 예측 도구 [S, 미검증] | (Clash, Braidkeep) | worktree 감시, `git merge-tree`로 진행 중 브랜치 간 충돌 예측 |
| GitHub merge queue [S] | https://docs.github.com/en/enterprise-server@3.20/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue | 앞 PR들 + 최신 base 위에서 다시 시험 |

→ **채택**: 같은 골 중복 차단, 파일 겹침 + `git merge-tree` 충돌 예측, 비슷한 MR 경고, base 최신 확인(리베이스 후 QA). **보류**: 유사도에 시간 요인 반영, 파일 소유 잠금(TTL).
