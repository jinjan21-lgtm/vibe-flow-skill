# e2e 기록 — 샘플 레포 한 바퀴 (2026-10-17)

샘플: 파이썬 표준 라이브러리 HTTP 서버 + `static/index.html`·`app.js` + unittest. 거래처 목록에 검색이 없는 상태에서 시작한다.
커밋 금지 조건이라 **스냅샷 모드**로 돌렸다. 구현 전 작업 트리의 tree sha를 기준(`base`)으로 삼고, 리뷰와 QA 대상도 tree sha로 기록했다. 실제 커밋 흐름은 `tests/test_scripts.py`가 덮는다.

| # | 단계 | 명령 | 결과 |
|---|---|---|---|
| 1 | setup.md | `cp templates/NORTHSTAR.md`, `G-000`, `goal_gate.py install-hook` | `.git/hooks/commit-msg` 설치 |
| 2 | 노스스타 | 목적 1줄, 판단 원칙 1줄, 하지 않을 것 2줄 | - |
| 3 | 골 후보 | `goal_gate.py candidate "거래처 이름 부분 검색"` → 네 칸 작성 | 후보 파일 |
| 4 | 바깥눈 판정 | `goal_gate.py judge <후보> --apply` (Codex 실호출, 6.6초) | `VERDICT: CREATE` — 목적·판단 원칙 인용, 하지 않을 것 비해당, G-000과 중복 아님 → `G-001` 생성 |
| 5 | 브랜치·기준 | `git checkout -b G-001/vendor-search`, `vf_git.snapshot()` | 기준 tree `f328b53` |
| 6 | Draft MR | `mr-body.md` 작성 → `mr_check.py --stage draft` | 통과 (dupe 검사 포함, 겹치는 작업 없음) |
| 7 | 테스트 먼저 | 부분 일치·대소문자·0건·빈 검색어 테스트 4개 추가 | `FAILED (errors=4)` |
| 8 | 구현 | `vendors.search`, `/api/vendors?q=`, 검색창·0건 안내 | 5/5 통과 |
| 9 | 계획 vs 실제 | 계획 밖 변경 1건(목록 렌더링 textContent) 기록 → `--stage review` | 통과 |
| 10 | 리뷰 1 (전체) | `review.py --round 1 --mr mr-body.md --tests .vibe/test-summary.txt` | `CHANGES · blocker 1` — app.js:3, 응답 순서가 뒤바뀌면 이전 결과가 최신 결과를 덮음 (재현 경로 포함) |
| 11 | 수정 | 요청 순번으로 최신 응답만 반영 | 테스트 5/5 |
| 12 | 리뷰 2 (diff) | `review.py --round 2 ...` | `CONFIRM · 지적 없음` → 리뷰 기록 `판정: 확정` |
| 13 | qa 단계 검사 | `mr_check.py --stage qa` | 통과 |
| 14 | QA 코드 | `python -m unittest discover -s tests -t .` | 5/5 |
| 15 | QA 브라우저 | `python server.py 8765` + Aside `openTab('http://127.0.0.1:8765/')`, `QA.shot` A1~A3, `crop.py` | "한빛" → 2건 ✅, "acme" → Acme Korea ✅, "없는이름" → 안내 문구 ✅ |
| 16 | QA 등록 | 「QA 결과」에 `대상 tree: 02a121a…`, 코드·브라우저 통과, 캡처 3장 | - |
| 17 | merge 검사 | `mr_check.py --stage merge` | **통과** |
| 18 | 음성 시험 | QA 뒤 `app.js`에 한 줄 추가 → merge 검사 | 차단: "QA 대상이 지금 작업물과 다름 — 재검증 필요". 원복 후 통과 |
| 19 | 커밋 훅 | `check-commit`에 "fix" (브랜치 `G-001/…`) | **버그 발견**: 커밋 없는 브랜치에서 브랜치 이름의 골 ID를 못 읽음 → 수정 후 통과, 테스트 추가 |

리뷰 라운드 3은 2라운드에서 확정돼 쓰이지 않았다. 3라운드 동작(`--files`로 부분 diff, 4라운드 거부, 라운드 건너뛰기 거부)은 `tests/test_scripts.py`의 `ReviewGateTest`로 확인했다.

## e2e에서 나온 결함과 조치

| 결함 | 조치 |
|---|---|
| 커밋 없는 브랜치에서 `rev-parse --abbrev-ref HEAD`가 `HEAD`를 돌려줘 브랜치 골 ID를 놓침 | `vf_git.current_branch()`(symbolic-ref)로 교체, 테스트 추가 |
| QA 캡처 영역을 `body`로 잡으면 폭 1440px이 640px로 줄어 글씨가 작아짐 | qa-gate.md에 "영역은 콘텐츠 컨테이너로" 추가 |
| 리뷰가 실제로 잡은 것: 비동기 응답 순서 경쟁 | 프로세스가 의도대로 작동 (근거 있는 blocker → 수정 → diff 라운드 확정) |
