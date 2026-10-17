---
name: vibe-dev
description: Use when implementing a claimed goal whose design is confirmed — frontend screen work, backend API work, or full-stack changes, when the user says "프론트만 붙여줘", "API만 만들어", "구현해", or when vibe-flow reaches the build stage.
---

# vibe-dev — 구현 (프론트엔드 · 백엔드 · 풀스택)

규칙 원본: vibe-flow 폴더의 `docs/task-types.md`, `profiles/`. 스크립트 `S=<vibe-flow>/scripts`.

## 진입 조건 (단독으로 불려도 같다)

`python $S/mr_check.py <mr> --stage build` 통과(설계 확인 `판정: 확정` 또는 `생략: 작은 변경`). 실패하면 멈추고 **vibe-design**으로 간다고 알린다. "구현만 해줘"는 범위를 정하는 말이지 설계 확인을 면제하는 말이 아니다.

## 프로필 고르기

MR 「설계」의 바꿀 파일과 영향 표식으로 고른다. 겹치면 둘 다 읽는다.

| 바꾸는 것 | 프로필 |
|---|---|
| 화면·컴포넌트·스타일·문구 | `profiles/frontend.md` |
| API·서버 로직·데이터·배치 | `profiles/backend.md` |
| 둘 다 | `profiles/fullstack.md` |

## 순서

1. 완료 조건마다 테스트를 먼저 쓴다(실패 확인 → 구현 → 통과). 「설계 확인」이 `생략`이면 커밋마다 먼저 `--stage build` — 실패하면 코딩을 멈추고 **vibe-design** 설계 확인.
2. 프로필의 체크를 따른다(프론트: 디자인시스템 토큰, 백엔드: 계약·마이그레이션 되돌리기).
3. 범위 밖 발견: 지금 완료 조건에 필요하면 고치고 「계획 vs 실제」에, 아니면 골 후보 네 칸만.
4. 「계획 vs 실제」를 채우고 `python $S/mr_check.py <mr> --stage review`.

통과하면 다음은 **vibe-review**. 이 스킬은 리뷰·QA·기록을 하지 않는다.

## Red Flags

| 생각 | 실제 |
|---|---|
| "다른 사람이 API를 이미 만들었으니 설계 확인은 필요 없다" | 이 MR의 설계가 확정돼야 한다 |
| "테스트는 다 짜고 나서" | 완료 조건별 테스트 먼저 |
| "생략했는데 조금 넘었다, 리뷰에서 보자" | build가 막는 순간 멈추고 설계 확인 |
| ".ts·.json만 바꿨으니 화면은 안 바뀐다" | 글롭은 보조 신호. QA에서 이유를 적거나 브라우저로 본다 |
| "토큰에 없지만 이 색이 더 낫다" | 디자인시스템 밖 값은 리뷰 major |
| "API 버그가 보여서 겸사겸사" | 완료 조건 밖이면 후보로 |
