#!/usr/bin/env python3
"""MR 본문이 현재 단계로 넘어갈 조건을 갖췄는지 기계적으로 검사한다.

  python mr_check.py <mr-body.md> --stage claim|draft|build|review|qa|merge
  python mr_check.py <mr-body.md> --next     처음 실패하는 단계와 그 단계의 세부 스킬(오케스트레이터용)

  claim  : 「골」에 활성 G-###, 브랜치 이름에 그 골 ID(팀 레포는 접두사 규칙도), 중복 없음 (dupe.py)
  draft  : + 사용자 가치·완료 조건·제외 범위·영향·위험·검증 계획·설계(5요소)가 채워짐, 중복 재검사
  build  : + 「설계 확인」에 '판정: 확정' 또는 '생략: 작은 변경 (예상 N줄·M파일)' (구현 전에, 생략 중엔 커밋마다).
           확인은 2회까지. 생략인데 예상치나 코드 변경이 design_skip 기준을 넘으면 차단
  review : + 「계획 vs 실제」. 이 골의 설계 확인이 구현 뒤에 돌았으면(goal이 같은 d<N>.meta) '- 순서: 구현 선행 (사유)' 필요.
           400줄·10파일 넘으면 경고. 크기는 코드만 센다(핸드오프 기록 파일·골 파일 제외 — is_record)
           draft부터 「완료 조건」은 체크리스트 항목만(completion_items — review.py 번호표와 같은 파서).
           build부터 「설계 확인」 '판정: 확정'(사람 판정 D-nnn 제외)은 최근 유효 d<N>.txt가 CONFIRM·blocker 0이어야 함.
           유효 = 기록(d<N>.meta·r<N>.tree)의 골·브랜치·기준 tree가 지금과 같음. d<N>.meta design(「설계」 해시)이
           지금 「설계」와 다르거나 없으면 차단(설계가 확인 뒤 바뀜)
  qa     : + 「리뷰 기록」에 "판정: 확정", 라운드 3회 이하. 최근 유효 r<N>.txt가 CONFIRM·blocker 0이고,
           그 r<N>.tree 뒤로 코드(기록 파일·.vibe/ 제외)가 안 바뀌었어야 함(바뀌면 --round N+1, 3이면 사람). merge도 같다
           지적 장부: 유효 라운드에서 열린 blocker·major가 뒤 라운드 RESOLVED(major는 CARRY)로 닫히지 않았으면 차단.
           RESOLVED 값은 '없음' 또는 ID 목록만(그 밖은 차단). r<N>.tree에 conds(완료 조건 해시)가 없으면 차단.
           r<N>.tree contract(완료 조건·제외 범위·사용자 가치·영향·위험 해시)가 없거나 다르면 차단(리뷰 재실행).
           '판정: 확정 (사람 판정 D-nnn)'은 유효 r3 + 결정 블록(골 ID·남은 ID) + '- 사람 결정: D-nnn — <ID들|없음> (tree <r3 sha>)'
           줄 필수. 그 tree 뒤 코드가 바뀌면 새 사람 판정(새 D-nnn, 바뀐 tree).
           (설계 확인도 같다: 유효 d2 필수 + 남은 blocker ID — 확인 없이 결정만 쓰는 우회 금지)
  merge  : + 「완료 조건」 항목이 모두 '- [x]'(체크박스 없는 항목도 미체크).
           「QA 결과」의 대상(commit 또는 tree)이 지금 작업물(미커밋 포함)과 같고 코드 통과.
           UI 파일이 바뀌었으면 브라우저 통과 + 캡처. 노스스타가 기준 이후 바뀌었으면 골 재판정 필요.
           base가 앞서 갔으면 리베이스 후 QA. 상태 셋(STATES — UNVERIFIED·ACCEPTED-RISK·POLICY-PENDING)은 모두 차단.
           리뷰 라운드 1 CHECKED 근거 테스트가 QA 기록 tests에서 모두 ok. 표준·강화는 이 골·기준의 RED 기록.
           handoff.py verify-evidence는 이 검사를 커밋된 증거로 재연한다(같은 함수 — 차이는 handoff.REPLAY_DIFF)
  강도 프로필(profile): 강화(위험·데이터·API 줄에 금액·결제·권한·인증·개인정보·삭제·마이그레이션·외부 API 계약)면
           draft부터 「검증 계획」 '- 코드:'에 회귀 테스트, merge에서 「QA 결과」 '- 회귀:'(QA 기록 tests에 모두 ok). 위험 값은 정확히 '없음'만 없음
  --next DONE은 HEAD의 <핸드오프>/mr/G-###.md 「골」「완료 조건」「제외 범위」가 작업 MR과 같아야 한다

레포 루트에서 실행한다. 설정은 .vibe-flow.json (vf_git.DEFAULT_CFG 참고).
기준(base)은 브랜치·커밋 이름 또는 tree sha(커밋 없는 스냅샷 모드)다.
통과하면 exit 0, 아니면 빠진 항목을 출력하고 exit 1.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vf_git  # noqa: E402

DRAFT = ["사용자 가치", "완료 조건", "제외 범위", "영향·위험", "검증 계획"]
DESIGN_ITEMS = ["접근 방식", "바꿀 모듈", "데이터·API", "대안", "테스트 계획"]
EMPTY = {"", "-", "(진행 전)", "(작성 예정)", "tbd", "todo"}
PASS = r"통과(?=$|[\s(（—–])"   # '통과하지 못함' 같은 말은 통과가 아니다
STAGES = ["claim", "draft", "build", "review", "qa", "merge"]
# 막혔을 때 준수 경로 — 메시지에 이 말이 있으면 해당 안내를 붙인다
HINTS = [("비어 있음", "templates/mr-body.md 안내대로 그 칸을 채운다"),
         ("골 파일 없음", "python goal_gate.py candidate \"<제목>\" → judge <후보> --apply"),
         ("G-### 없음", "「골」 칸에 활성 골 ID를 적는다"),
         ("브랜치", "브랜치 이름을 <접두사>/G-###-<주제>로(git branch -m)"),
         ("착수", "그 작업에 합류하거나 골을 나눈다 — 사용자와 정한다"),
         ("같은 골", "그 작업에 합류하거나 골을 나눈다 — 사용자와 정한다"),
         ("예상 규모", "구현 전에 '- 생략: 작은 변경 (예상 N줄·M파일)'로 적는다 — 기준을 넘을 것 같으면 설계 확인"),
         ("구현 선행", "「설계 확인」에 '- 순서: 구현 선행 (<사유>)'를 적는다 — 사후 설계 확인을 숨기지 않는다"),
         ("review.py --design", "python review.py --design 1 --mr <mr-body.md>"),
         ("리뷰 기록", "python review.py --round 1 --mr <mr-body.md>"),
         ("설계 확인 기록", "Codex 출력(.vibe/review/d<N>.txt)이 판정이다 — 지금 브랜치에서 review.py --design을 다시 받는다"),
         ("뒷받침하지 않음(", "MR의 '판정: 확정'은 최근 유효 라운드(r<N>.txt VERDICT: CONFIRM, blocker 0)를 옮겨 적는 것이다"),
         ("리뷰 확정 뒤", "review-loop.md 「확정 뒤 코드 변경」 — 고친 파일만 다음 라운드(--files), 3라운드를 썼으면 사용자에게"),
         ("체크리스트 항목", "「완료 조건」을 '- [ ] <관찰 가능한 결과>' 줄로만 쓴다(설명은 들여 쓴 이어지는 줄로)"),
         ("회를 넘음","자동 진행을 멈추고 사용자에게 남은 지적을 보고한다(사람 판정)"),
         ("재검증", "qa-gate.md 순서로 지금 작업물에 QA를 다시 하고 「QA 결과」 대상을 갱신"),
         ("브라우저", "qa-gate.md 「브라우저」 — Aside로 확인하고 캡처를 붙인다"),
         ("UI 판정", "화면에 닿는지 판단해 브라우저 줄에 근거를 적는다(닿으면 Aside)"),
         ("완료 조건 미체크", "QA로 확인한 완료 조건을 '- [x]'로 — 확인 못 한 조건은 QA를 다시"),
         ("리베이스", "git pull --rebase origin <base> 뒤 QA 다시"),
         ("노스스타", "python goal_gate.py judge로 골 재판정")]


def sections(text):
    out, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            cur = m.group(1)
            out[cur] = []
        elif cur:
            out[cur].append(line)
    # 템플릿 안내 주석은 내용으로 치지 않는다
    return {k: re.sub(r"<!--.*?-->", "", "\n".join(v), flags=re.S).strip() for k, v in out.items()}


def filled(s, name):
    body = s.get(name, "").strip()
    if body.lower() in EMPTY:
        return False
    # 템플릿 자리표시(<...>), 목록 기호, 체크박스, "라벨:" 접두어를 지우고 남는 내용이 있어야 채운 것
    rest = re.sub(r"<[^>\n]+>", "", body)
    rest = re.sub(r"^\s*(?:[-*]|\d+\.)?\s*(?:\[[ x]\])?\s*(?:[^:\n]{1,12}:)?", "", rest, flags=re.M)
    return bool(re.search(r"\w", rest))


def design_items_missing(body):
    """「설계」 칸의 5요소: '- 접근 방식: …' 처럼 라벨 뒤에 내용이 있어야 한다."""
    miss = []
    for label in DESIGN_ITEMS:
        m = re.search(rf"^\s*[-*]?\s*{label}[^:\n]*:(.*)$", body, re.M)
        if not m or not re.search(r"\w", re.sub(r"<[^>\n]+>", "", m.group(1))):
            miss.append(f"「설계」의 '{label}' 비어 있음")
    return miss


# 핸드오프 폴더 바로 아래 기록 파일 — 정확한 이름과 hindex.py의 분할·보관 이름만(docs/structure.md 「문서별 규칙」).
# 접두사로 보면 PLANET.md·INDEXER.md 같은 코드 문서까지 빠진다
RECORD_NAME = re.compile(r"(?:PLAN(?:-body(?:-\d+)?)?|WORKLOG|REMAINING(?:-done-\d{4}-\d{2})?|LESSONS(?:-body(?:-\d+)?)?"
                         r"|DECISIONS(?:-\d{4}-\d{2}(?:-\d+)?|-INDEX-replaced)?|NORTHSTAR(?:-body)?|INDEX)\.md")
QA_RECORD = re.compile(r"G-\d{3,}-(?:qa|red)\.json")   # <핸드오프>/mr/G-###-qa.json·-red.json: qa_run.py 실행 기록 사본(기록 커밋에 넣는다)


def is_record(f, cfg, plan=None):
    """핸드오프 기록 파일만: 골 폴더, <핸드오프>/mr/, <핸드오프>/WORKLOG/ 토픽, 핸드오프 폴더 바로 아래 RECORD_NAME.
    코드 위험이 아니므로 크기·구현 여부·QA/리뷰 뒤 변경에서 뺀다.
    개인 모드는 핸드오프가 docs/라 폴더로만 가리면 docs/ 아래 코드까지 빠진다 — .md가 아니면 기록이 아니다.
    plan: PLAN.md 본문(커밋에서 읽은 것) — 주면 작업 트리 대신 이것으로 PLAN 링크를 본다(verify-evidence)."""
    p = vf_git.paths(cfg)
    h, goals = p["handoff"].rstrip("/"), p["goals"].rstrip("/")
    d, _, name = f.rpartition("/")
    if (d == h + "/mr" and QA_RECORD.fullmatch(name)) or re.fullmatch(re.escape(h) + r"/mr/G-\d{3,}-evidence/.+", f):   # 내보낸 캡처도 기록
        return True
    if not f.endswith(".md"):
        return False
    if f.startswith((goals + "/", h + "/mr/", h + "/WORKLOG/")) or f in (p["northstar"], p["northstar"][:-3] + "-body.md"):
        return True
    if d == h and re.fullmatch(r"PLAN-[\w-]+\.md", name) and not RECORD_NAME.fullmatch(name):
        return plan_linked(h, name, plan)   # PLAN 섹션 분할 파일(hindex)은 PLAN.md 목차가 링크한 것만
    return d == h and bool(RECORD_NAME.fullmatch(name))


def plan_linked(h, name, plan=None):
    """PLAN.md(작업 트리, plan을 주면 그 본문)가 그 파일을 링크하는가 — 링크 없는 PLAN-*.md는 기록이 아니라 코드로 센다."""
    if plan is None:
        p = os.path.join(h, "PLAN.md")
        if not os.path.exists(p):
            return False
        plan = _read(p)
    return bool(re.search(rf"\]\(\s*(?:\./)?{re.escape(name)}(?:#[^)]*)?\)", plan))


def code_changes(cfg, old=None, cur=None):
    """기준 대비 바뀐 코드(기록 제외) — (파일 목록, 줄 수)."""
    old = old or vf_git.base_tree(cfg["base"])
    cur = cur or vf_git.snapshot()
    files = [f for f in vf_git.changed_files(old, cur) if not is_record(f, cfg)]
    lines = 0
    for row in vf_git.git("diff", "--numstat", old, cur).splitlines():
        a, b, path = (row.split("\t") + ["", ""])[:3]
        if a.isdigit() and b.isdigit() and not is_record(path, cfg):
            lines += int(a) + int(b)
    return files, lines


def diff_size(cfg):
    files, lines = code_changes(cfg)
    return lines, len(files)


ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*?)\s*$")


def completion_body(text):
    m = re.search(r"^##\s+완료 조건\s*\n(.*?)(?=^##\s|\Z)", re.sub(r"<!--.*?-->", "", text, flags=re.S), re.M | re.S)
    return m.group(1) if m else ""


def completion_items(text):
    """「완료 조건」 목록 항목 [(체크됨, 문구)] — '-'·'*'·'+'·'1.'·'1)' 모두. 리뷰 번호표(review.py)와 머지 체크가 같이 쓴다.
    '- [x]'만 체크됨이다('- [ ]'도, 체크박스 없는 항목도 미체크)."""
    out = []
    for line in completion_body(text).splitlines():
        m = ITEM.match(line)
        if m:
            c = re.match(r"\[([ xX])\]\s*(.*)$", m.group(1))
            out.append((bool(c) and c.group(1) in "xX", c.group(2) if c else m.group(1)))
    return out


def completion_hash(text):
    """완료 조건 문구(체크 상태 제외, 공백 정규화)의 해시 — review.py가 r<N>.tree에 남기고 qa·merge가 대조한다."""
    import hashlib
    norm = "\n".join(" ".join(t.split()) for _, t in completion_items(text))
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def _norm_hash(parts):
    import hashlib
    norm = "\n\n".join("\n".join(" ".join(x.split()) for x in p.splitlines() if x.strip()) for p in parts)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def design_hash(text, cfg=None):
    """「설계」 문구(주석·공백·빈 줄 무시)의 해시 — review.py --design이 d<N>.meta 'design:'에 남기고 build부터 대조한다."""
    return _norm_hash([sections(vf_git.normalize_mr(text, cfg)).get("설계", "")])


REVIEW_CONTRACT = ("완료 조건", "제외 범위", "사용자 가치", "영향·위험")


def contract_hash(text, cfg=None):
    """리뷰 계약(완료 조건 문구·제외 범위·사용자 가치·영향·위험)의 해시 — r<N>.tree 'contract:'. qa·merge가 대조한다."""
    text = vf_git.normalize_mr(text, cfg)
    s = sections(text)
    return _norm_hash(["\n".join(t for _, t in completion_items(text))] + [s.get(k, "") for k in REVIEW_CONTRACT[1:]])


def contract_problem(rec, text):
    """r<N>.tree의 contract가 지금 MR 계약과 다르면(없어도 — fail closed) 메시지, 같으면 ''."""
    old = record_fields(rec).get("contract")
    if old and old == contract_hash(text):
        return ""
    return (f"리뷰 뒤 계약(「{'」「'.join(REVIEW_CONTRACT)}」)이 바뀜({os.path.basename(rec)}"
            + ("" if old else ": contract 해시 없음") + ") — 리뷰 재실행(review.py --round 1)")


def completion_prose(text):
    """「완료 조건」에서 목록 항목이 아닌 문장 줄(들여쓴 줄은 앞 항목의 이어지는 줄로 본다)."""
    return [x.strip() for x in completion_body(text).splitlines()
            if x.strip() and not ITEM.match(x) and not x[:1].isspace()]


def unchecked_conditions(text):
    """「완료 조건」 항목 중 '- [x]'가 아닌 수."""
    return sum(1 for ok, _ in completion_items(text) if not ok)


def mr_goal(text, cfg=None):
    """MR 「골」의 골 ID(여럿이면 쉼표로). .vibe/review 기록이 어느 골의 것인지 적고 대조한다."""
    s = sections(vf_git.normalize_mr(text, cfg))
    return ",".join(sorted(set(re.findall(r"\bG-\d{3,}\b", s.get("골", "")))))


REVIEW_DIR = os.path.join(".vibe", "review")
VERDICT = re.compile(r"^VERDICT:\s*(CONFIRM|CHANGES)", re.M)


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def record_fields(path):
    """.vibe/review 기록 파일의 'key: value' 줄들. 없으면 {}."""
    if not os.path.exists(path):
        return {}
    return {k: v.strip() for k, v in re.findall(r"^(\w+):[ \t]*(.*)$", _read(path), re.M)}


def record_goal(path):
    """.vibe/review 기록 파일의 'goal:' 줄. 없으면(예전 형식) ''."""
    return (record_fields(path).get("goal") or "").split(" ")[0]


def current_base(cfg):
    try:
        return vf_git.base_tree(cfg["base"])
    except RuntimeError:
        return ""


def record_stamp(goal, cfg):
    """.vibe/review 기록(r<N>.tree·d<N>.meta)에 남기는 맥락: 골·브랜치·기준 tree(base와의 merge-base)."""
    return f"schema: {vf_git.EVIDENCE_SCHEMA}\ngoal: {goal}\nbranch: {vf_git.current_branch()}\nbase: {current_base(cfg)}\n"


def record_problem(path, goal, cfg):
    """기록이 지금 맥락(같은 골·같은 브랜치·같은 기준)의 것이 아니면 그 이유, 맞으면 ''.
    같은 골이라도 다른 브랜치나 리베이스 전 기준에서 받은 확인은 지금 코드에 대한 것이 아니다."""
    f = record_fields(path)
    if not f:
        return f"{os.path.basename(path)} 없음"
    old = record_goal(path)
    if not goal or old != goal:
        return f"{os.path.basename(path)}는 {'골 표시 없는 예전 기록' if not old else f'다른 골({old})의 것'}(지금 골: {goal or '없음'})"
    br = vf_git.current_branch()
    if f.get("branch") != br:
        return f"{os.path.basename(path)}는 다른 브랜치({f.get('branch') or '표시 없음'})의 것(지금 브랜치: {br})"
    if f.get("base") != current_base(cfg):
        return f"{os.path.basename(path)}의 기준 tree가 지금 기준과 다름(리베이스·기준 변경) — 다시 받아야 함"
    return ""


def findings(text):
    """'FINDING: <id> | <심각도> | …' 줄들(templates/review-prompt.md 형식)."""
    rows = []
    for line in text.splitlines():
        m = re.match(r"^FINDING:\s*(.+)$", line.strip())
        if m:
            parts = [p.strip() for p in m.group(1).split("|")]
            rows.append({"id": parts[0], "sev": parts[1] if len(parts) > 1 else "?", "raw": line.strip()})
    return rows


def blockers(text):
    return [x for x in findings(text) if x["sev"].lower() == "blocker"]


FID = re.compile(r"(?<![0-9A-Za-z])[A-Za-z][A-Za-z0-9_-]*")   # 지적 ID(F1·B-2). 한글 조사가 붙어도 ID만
CARRY = re.compile(r"^CARRY:[ \t]*([A-Za-z][A-Za-z0-9_-]*)\s*[—–-]+\s*골 후보\s*\S", re.M)


def has_fid(fid, text):
    return bool(re.search(rf"(?<![0-9A-Za-z-]){re.escape(fid)}(?![0-9A-Za-z])", text))


RESOLVED_NONE = re.compile(r"없음\s*\.?\s*")
RESOLVED_LIST = re.compile(r"[A-Za-z][A-Za-z0-9_-]*(?:[\s,]+[A-Za-z][A-Za-z0-9_-]*)*[\s,]*")


def resolved_problems(text):
    """'RESOLVED:' 값은 정확히 '없음'(뒤 공백·마침표 허용) 또는 쉼표·공백으로 나눈 지적 ID 목록만. 그 밖은 형식 오류."""
    return [f"RESOLVED 형식 오류: '{v.strip()[:40]}' — 값은 '없음' 또는 지적 ID 목록만"
            for v in re.findall(r"^RESOLVED:[ \t]*(.*)$", text, re.M)
            if not (RESOLVED_NONE.fullmatch(v) or RESOLVED_LIST.fullmatch(v))]


def resolved_ids(text):
    """'RESOLVED: F1, F2' 줄의 ID들('없음'은 빈 집합). 형식이 어긋난 줄('없음 (F1 미해결)' 등)은 아무것도 닫지 않는다."""
    return {i for line in re.findall(r"^RESOLVED:[ \t]*(.*)$", text, re.M)
            if RESOLVED_LIST.fullmatch(line) for i in FID.findall(line)}


def carried_ids(text):
    """'CARRY: <id> — 골 후보 <사유>' 줄의 ID들. major만 넘길 수 있다(blocker는 닫아야 한다)."""
    return set(CARRY.findall(text))


GATE_SEVS = ("blocker", "major")   # 장부가 막는 심각도(qa·merge·review.py) — major는 CARRY로 넘길 수 있다


def ledger(rounds, sevs=("blocker",)):
    """지적 장부: 회차 [(n, 출력)]를 차례로 — RESOLVED(major는 CARRY도)로 닫고, 그 회차 지적을 연다. {id: (심각도, n)}."""
    open_ = {}
    for n, t in rounds:
        for i in resolved_ids(t):
            open_.pop(i, None)
        for i in carried_ids(t):
            if open_.get(i, ("",))[0] == "major":
                open_.pop(i)
        for x in findings(t):
            if x["sev"].lower() in sevs:
                open_[x["id"]] = (x["sev"].lower(), n)
    return open_


def valid_rounds(kind, goal, cfg):
    """이 골·브랜치·기준의 유효 회차 [(n, 출력)] 순서대로(VERDICT 있는 출력 + 지금 맥락의 기록)."""
    out = []
    for n in ((1, 2) if kind == "d" else (1, 2, 3)):
        p = os.path.join(REVIEW_DIR, f"{kind}{n}.txt")
        rec = os.path.join(REVIEW_DIR, f"{kind}{n}.{'meta' if kind == 'd' else 'tree'}")
        if os.path.exists(p) and VERDICT.search(_read(p)) and not record_problem(rec, goal, cfg):
            out.append((n, _read(p)))
    return out


def decision_cover(did, sec, open_, cfg, label, blk=None):
    """사람 결정 재개 계약: 「<label>」 '- 사람 결정: D-nnn — <지적 ID들>'이 열린 blocker를 모두 적고,
    결정 블록(DECISIONS*.md '## D-nnn')도 그 ID를 모두 적어야 한다(review-loop.md 「사람 결정 뒤 재개」)."""
    m = re.search(rf"^\s*-\s*사람 결정:\s*{did}(?!\d)\s*[—–-]+\s*(\S.*)$", sec, re.M)
    listed = set(FID.findall(m.group(1))) if m else set()
    miss = []
    if not m:
        miss.append(f"「{label}」에 '- 사람 결정: {did} — <지적 ID들>' 줄 없음 — 열린 지적이 없으면 '— 없음'")
    lack = sorted(i for i in open_ if i not in listed)
    if lack:
        miss.append(f"「{label}」 '- 사람 결정: {did} — <지적 ID들>'에 열린 지적 {', '.join(lack)} 없음 — 사람이 푼 지적 ID를 모두 적는다")
    blk = decision_block(did, cfg)[1] if blk is None else blk   # verify-evidence는 커밋된 블록을 준다
    absent = sorted(i for i in open_ if blk and not has_fid(i, blk))
    if absent:
        miss.append(f"결정 {did} 블록에 열린 지적 {', '.join(absent)} 없음 — 결정이 어떤 지적을 풀었는지 적는다")
    return miss


def latest_round(kind, goal, cfg):
    """이 골·브랜치·기준의 가장 최근 유효 회차 (n, VERDICT, 출력) — 설계 d2→d1, 리뷰 r3→r1. 없으면 None.
    유효 = VERDICT 있는 <kind><n>.txt + 지금 맥락의 기록(리뷰 .tree, 설계 .meta)."""
    for n in ((2, 1) if kind == "d" else (3, 2, 1)):
        out = os.path.join(REVIEW_DIR, f"{kind}{n}.txt")
        rec = os.path.join(REVIEW_DIR, f"{kind}{n}.{'meta' if kind == 'd' else 'tree'}")
        if not os.path.exists(out):
            continue
        text = _read(out)
        v = VERDICT.search(text)
        if v and not record_problem(rec, goal, cfg):
            return n, v.group(1), text
    return None


def round_not_confirmed(kind, goal, cfg):
    """MR이 '확정'이라 적었을 때 실제 Codex 기록이 뒷받침하지 않는 이유. 뒷받침하면 ''."""
    got = latest_round(kind, goal, cfg)
    if not got:
        recs = [os.path.join(REVIEW_DIR, f"{kind}{n}.{'meta' if kind == 'd' else 'tree'}") for n in (1, 2, 3)[:2 if kind == "d" else 3]]
        why = [record_problem(p, goal, cfg) for p in recs if os.path.exists(p)]
        return "이 골·브랜치·기준의 유효한 기록 없음" + (f" — {why[0]}" if why else "")
    n, verdict, text = got
    if verdict != "CONFIRM":
        return f"최근 {kind}{n}.txt는 VERDICT {verdict}"
    if blockers(text):
        return f"최근 {kind}{n}.txt에 blocker FINDING {len(blockers(text))}개"
    return ""


ARTIFACT_EXT = (".pyc", ".pyo", ".class", ".o", ".obj")


def tracked_artifact(f, cfg):
    """실수로 추적 중이어도 QA 비교에서 빼는 산출물 — 고정 목록(__pycache__/·.pyc·.pyo·.class·.o·.obj) + qa_ignore_tracked 글롭."""
    return "__pycache__/" in f or f.endswith(ARTIFACT_EXT) or vf_git.glob_match(f, cfg.get("qa_ignore_tracked") or [])


def code_diff(old, cur, cfg):
    """두 tree 사이 바뀐 코드 — 기록 파일(is_record)과 .vibe/(로컬 작업 상태)를 빼고,
    추적 중인 산출물(tracked_artifact — 테스트마다 바뀜)도 뺀다. .gitignore에 걸려도 추적 중인 코드는 코드다. (코드 목록, 뺀 산출물)."""
    names = vf_git.git("diff", "--name-only", old, cur, check=True)   # git 실패는 '변경 없음'이 아니다(RuntimeError)
    code = [f for f in names.splitlines() if f and not is_record(f, cfg) and not f.startswith(".vibe/")]
    ignored = {f for f in code if tracked_artifact(f, cfg)}
    return [f for f in code if f not in ignored], ignored


def changed_since(seen, cfg, seen_code=""):
    """기록이 본 tree(seen) 뒤 지금 작업물에서 바뀐 코드 파일. 판정 엔진의 유일한 「그 뒤 코드가 바뀌었나」 비교 —
    로컬 merge와 verify-evidence 재연(replay)이 같이 쓴다. seen tree 객체가 없으면(새 clone — amend 전 tree는 clone되지
    않는다) 기록에 남은 code_tree(기록 파일을 뺀 tree)를 지금 코드 tree와 비교한다. 둘 다 없으면 RuntimeError."""
    cur = vf_git.snapshot()
    if re.fullmatch(r"[0-9a-f]{7,40}", seen or "") and vf_git.obj_type(seen) == "tree":
        return code_diff(seen, cur, cfg)[0]
    if seen_code:
        import qa_run
        now = qa_run.code_tree(cur, cfg)
        return [] if now == seen_code else [f"(코드 tree {now[:10]} ≠ 기록 {seen_code[:10]})"]
    raise RuntimeError(f"tree {str(seen)[:12]} 없음")


def diverged_design_checks(goal, cfg=None):
    """이 골의 설계 확인 중 코드가 이미 기준과 달랐던 회차(review.py가 .vibe/review/d<N>.meta에 남긴다).
    지금 맥락(골·브랜치·기준)이 아닌 meta는 이전 작업의 것이라 보지 않는다."""
    cfg = cfg or vf_git.config()
    hit = []
    for n in (1, 2):
        p = os.path.join(REVIEW_DIR, f"d{n}.meta")
        if goal and not record_problem(p, goal, cfg) and record_fields(p).get("diverged") == "yes":
            hit.append(f"d{n}")
    return hit


def decision_block(did, cfg):
    """결정 파일(<핸드오프>/DECISIONS*.md)의 '## D-nnn' 블록 (파일 이름, 블록 본문). 없으면 ("", "")."""
    import glob
    h = vf_git.paths(cfg)["handoff"]
    for f in sorted(glob.glob(os.path.join(h, "DECISIONS*.md"))):
        m = re.search(rf"^##\s+{did}(?!\d).*?(?=^##\s|\Z)", _read(f), re.M | re.S)
        if m:
            return os.path.basename(f), m.group(0)
    return "", ""


def decision_problem(did, gids, cfg):
    """사람 판정 D-nnn이 결정 파일(<핸드오프>/DECISIONS*.md)에 '## D-nnn' 블록으로 있고 그 블록이 이 골 ID를 적었는가."""
    name, blk = decision_block(did, cfg)
    if not name:
        return f"{vf_git.paths(cfg)['handoff']}/DECISIONS*.md에 '## {did}' 결정이 없음"
    if gids and all(re.search(rf"(?<![0-9A-Za-z]){g}(?![0-9A-Za-z])", blk) for g in gids):
        return ""
    return f"결정 블록({name})에 이 골 ID({', '.join(gids) or '없음'})가 없음"


def _none(v):
    """값이 정확히 '없음'(뒤에 공백·마침표만)일 때만 없음. '없음(…실제 위험…)'은 위험 설명이다(H-05)."""
    return bool(re.fullmatch(r"없음\s*\.?", (v or "").strip()))


def risk_values(s):
    """(「영향·위험」 '- 위험:' 값, 「설계」 '데이터·API 변경:' 값). 줄이 없으면 None."""
    r = re.search(r"^\s*[-*]?\s*위험\s*:(.*)$", s.get("영향·위험", ""), re.M)
    a = re.search(r"^\s*[-*]?\s*데이터·API[^:\n]*:(.*)$", s.get("설계", ""), re.M)
    return (r.group(1).strip() if r else None), (a.group(1).strip() if a else None)


def risky(s):
    """「영향·위험」 '- 위험:'이나 「설계」 '데이터·API 변경:'이 '없음'이 아니면 위험 표식(줄이 없어도)."""
    return not all(v is not None and _none(v) for v in risk_values(s))


# 강화 프로필 표식(docs/task-types.md 「강도 프로필」): 위험 줄·데이터·API 줄에 이 말이 있으면 회귀 테스트를 이름으로 요구
STRONG = re.compile(r"금액|결제|권한|인증|개인정보|삭제|마이그레이션|외부\s*API|API\s*계약", re.I)


def profile(s):
    """강도 프로필: 강화(STRONG 표식) · 표준(그 밖의 위험 표식) · 경량(위험 표식 없음 — 크기는 design_skip이 본다)."""
    if any(v and not _none(v) and STRONG.search(v) for v in risk_values(s)):
        return "강화"
    return "표준" if risky(s) else "경량"


def line_value(body, label):
    m = re.search(rf"^\s*[-*]?\s*{label}\s*:(.*)$", body, re.M)
    return re.sub(r"<[^>\n]+>", "", m.group(1)).strip() if m else ""


def goal_checks(s, cfg):
    miss = []
    gids = re.findall(r"\bG-\d{3,}\b", s.get("골", ""))
    gdir = vf_git.paths(cfg)["goals"]
    if not gids:
        miss.append("「골」에 G-### 없음")
    for gid in gids:
        hit = [fn for fn in os.listdir(gdir) if re.match(rf"{gid}(?![0-9A-Za-z])", fn)] if os.path.isdir(gdir) else []
        if not hit:
            miss.append(f"{gid} 골 파일 없음 ({gdir})")
        else:
            with open(os.path.join(gdir, hit[0]), encoding="utf-8") as f:
                # 재연(verify-evidence — REPLAY_DIFF): 기록 커밋은 골을 done으로 닫는다 — 그 커밋에서는 done도 그 골이다
                ok_st = r"active|done" if cfg.get("_replay") else r"active"
                if not re.search(rf"^status:\s*(?:{ok_st})\b", f.read(), re.M):
                    miss.append(f"{gid} 상태가 active 아님")
    return miss, gids


def branch_checks(gids, cfg):
    miss = []
    cur = vf_git.current_branch()
    if gids and not any(re.search(rf"(?<![0-9A-Za-z]){g}(?![0-9A-Za-z])", cur) for g in gids):
        miss.append(f"브랜치 '{cur}' 이름에 골 ID({', '.join(gids)}) 없음")
    pre = cfg.get("branch_prefixes") or []
    if pre and cur.split("/")[0] not in pre:
        miss.append(f"브랜치 '{cur}'가 레포 접두사 규칙({'|'.join(pre)})/G-###-주제 를 따르지 않음")
    return miss


def check(text, stage, cfg):
    text = vf_git.normalize_mr(text, cfg)
    s = sections(text)
    i = STAGES.index(stage)
    miss, gids = goal_checks(s, cfg)
    miss += branch_checks(gids, cfg)

    if stage in ("claim", "draft"):
        import dupe
        blocks, warns = dupe.find(text, cfg)
        miss += blocks
        for w in warns:
            print("[dupe] 경고:", w)
    goal = ",".join(sorted(set(gids)))
    if i >= 1:
        import dupe
        miss += dupe.scope_overlaps(text, cfg)     # 남이 공지한 착수 범위와 겹침 — draft부터 merge까지 매번
        miss += scope_problems(text, stage, cfg)   # 내 범위 공지 — build부터
        miss += [f"「{n}」 비어 있음" for n in DRAFT if not filled(s, n)]
        if filled(s, "완료 조건"):
            prose = completion_prose(text)
            if not completion_items(text) or prose:
                miss.append("완료 조건은 체크리스트 항목으로 — 「완료 조건」의 줄마다 '- [ ] <관찰 가능한 결과>'"
                            + (f"(목록 밖 문장: '{prose[0][:40]}')" if prose else "(항목 0개)"))
            empty = sum(1 for _, t in completion_items(text) if not t.strip())
            if empty:
                miss.append(f"「완료 조건」에 빈 항목 {empty}개 — 항목마다 관찰 가능한 결과를 적는다")
        miss += design_items_missing(s.get("설계", ""))
        code = line_value(s.get("검증 계획", ""), "코드")
        if profile(s) == "강화" and not test_ids(code):
            miss.append("강화 프로필(금액·권한·개인정보·삭제·마이그레이션·외부 API 계약) — 「검증 계획」 '- 코드:'에 "
                        "회귀 테스트(이름)를 적는다")
    if i >= 2:
        dc = s.get("설계 확인", "")
        confirmed = re.search(r"판정:\s*확정", dc)
        skipped = re.search(r"생략:\s*작은 변경", dc)
        if not (confirmed or skipped):
            miss.append("「설계 확인」에 '판정: 확정'(또는 '생략: 작은 변경') 없음 — review.py --design 먼저")
        human = re.search(r"판정:\s*확정\s*[(（]\s*사람 판정\s*(D-\d+)", dc)
        if confirmed and human:
            why = decision_problem(human.group(1), gids, cfg)
            if why:
                miss.append(f"「설계 확인」 사람 판정 {human.group(1)}: {why} — 결정을 D-nnn으로 기록하고 이 골 ID를 적는다")
            drounds = valid_rounds("d", goal, cfg)
            if not drounds:   # 사람 판정은 Codex 설계 확인 2회 뒤에만 — 확인 없이 결정 문서만 쓰는 우회를 막는다
                miss.append(f"「설계 확인」 사람 판정 {human.group(1)}: 설계 확인 기록(d1·d2) 없음 — 사람 판정은 설계 확인 2회 뒤에만")
            else:   # 2회를 다 쓴 뒤에만, 남은 blocker를 결정이 모두 적어야 한다
                if [n for n, _ in drounds] != [1, 2]:   # d2 하나만 남긴 것은 2회를 다 쓴 것이 아니다
                    miss.append(f"「설계 확인」 사람 판정 {human.group(1)}: 유효 기록 d1·d2가 모두 있어야 함 — 사람 판정은 설계 확인 2회 뒤에만")
                else:
                    miss += decision_cover(human.group(1), dc, {x["id"]: ("blocker", 2) for x in blockers(drounds[-1][1])},
                                           cfg, "설계 확인")
                # 사람이 정하는 것은 지적의 처리이지 검토 증거가 아니다 — d1·d2 원문도 같은 형식 규칙(A19-01 잔여)
                import review as _rv
                for dn_, dtext_ in drounds:
                    bad = _rv.design_problems(dtext_)
                    if bad:
                        miss.append(f"설계 확인 원문 d{dn_}.txt가 지금 형식이 아님(요소별 CHECKED·POLICY): {'; '.join(bad[:3])} — "
                                    "review.py --design 다시")
        if confirmed and not human:
            # MR 문구가 아니라 Codex 출력이 판정이다 — 최근 d<N>.txt가 CONFIRM이고 blocker가 없어야 한다
            why = round_not_confirmed("d", goal, cfg)
            if why:
                miss.append(f"「설계 확인」은 '판정: 확정'인데 설계 확인 기록이 뒷받침하지 않음({why}) — "
                            "review.py --design 1(또는 2)을 지금 브랜치에서 다시")
            else:   # 확인 기록은 그때의 「설계」 문구에 묶인다 — 해시 없는 예전 기록도 stale
                dn, _, dtext = latest_round("d", goal, cfg)
                if record_fields(os.path.join(REVIEW_DIR, f"d{dn}.meta")).get("design") != design_hash(text, cfg):
                    miss.append(f"설계가 확인 뒤 바뀜(d{dn}.meta) — review.py --design 다시(남은 회차 안에서) 또는 사람 판정")
                # 원문 형식도 review.py가 받을 때와 같은 규칙으로 다시 본다(A19-01 — 원문이 뒤에 바뀌거나 옛 형식이면)
                import review as _rv
                bad = _rv.design_problems(dtext)
                if bad:
                    miss.append(f"설계 확인 원문 d{dn}.txt가 지금 형식이 아님(요소별 CHECKED·POLICY): {'; '.join(bad[:3])} — "
                                "review.py --design 다시")
        if len(re.findall(r"^-\s*확인\s*\d", dc, re.M)) > 2:
            miss.append("설계 확인이 2회를 넘음 — 사람 판정 필요")
        if skipped and not confirmed and risky(s):
            miss.append("위험 표식이 있으면 설계 확인 생략 불가 — 「영향·위험」 '- 위험:'과 「설계」 '데이터·API 변경:'이 '없음'일 때만 생략")
        if skipped and not confirmed:
            # 생략은 구현 전에 정한다 — 예상치를 먼저 적고, build를 커밋마다 돌려 넘는 순간 멈춘다
            lim = cfg.get("design_skip", {})
            ml, mf = lim.get("max_lines", 50), lim.get("max_files", 3)
            num = r"(\d+(?:,\d{3})*)"   # 1,200은 되고 ','·'1,2'는 형식 오류(빠진 항목) — 예외로 죽지 않는다
            est = re.search(rf"생략:\s*작은 변경\s*[(（]\s*예상\s*{num}\s*줄\s*[·・,/ ]\s*{num}\s*파일", dc)
            if not est:
                miss.append("「설계 확인」 생략에 예상 규모 없음(또는 형식 오류) — '- 생략: 작은 변경 (예상 N줄·M파일)'")
            elif int(est.group(1).replace(",", "")) > ml or int(est.group(2).replace(",", "")) > mf:
                miss.append(f"예상 규모가 생략 기준을 넘음(기준 {ml}줄·{mf}파일) — review.py --design 필요")
            lines, files = diff_size(cfg)
            if lines > lim.get("max_lines", 50) or files > lim.get("max_files", 3):
                miss.append(f"설계 확인을 생략했지만 코드 변경이 {lines}줄·{files}파일로 커짐 — 코딩을 멈추고 review.py --design 필요")
    if i >= 2:
        miss += design_policy_problems(goal, cfg, s)
        miss += design_major_problems(goal, cfg, s)
    if i >= 3 and profile(s) == "경량":
        hits = risk_code_hits(cfg)
        judged = re.search(r"^\s*[-*]?\s*위험 판단\s*:\s*(\S.{9,})$", s.get("영향·위험", ""), re.M)
        if hits and not judged:
            miss.append(f"「영향·위험」 위험이 '없음'인데 바뀐 코드에 금액·권한·삭제 관련 식별자({', '.join(hits)}) — 위험을 다시 "
                        "판단해 '- 위험:'에 적거나(표준·강화), 위험이 아니면 '- 위험 판단: <이유>'를 적는다")
    if i >= 3 and not filled(s, "계획 vs 실제"):
        miss.append("「계획 vs 실제」 비어 있음")
    if i >= 3:
        late = diverged_design_checks(goal, cfg)
        if late and not re.search(r"^\s*-\s*순서:\s*구현 선행\s*[(（—–:-]\s*\S{2,}", s.get("설계 확인", ""), re.M):
            miss.append(f"설계 확인({', '.join(late)})이 구현 시작 뒤에 돌았음 — 「설계 확인」에 '- 순서: 구현 선행 (사유)' 필요")
    if stage == "review":
        size_warning(cfg)
        pf = profile(s)
        print(f"[profile] {pf}" + {"경량": " — 리뷰 1라운드 예상(지적이 나오면 2·3라운드)",
                                   "강화": " — 회귀 테스트를 「검증 계획」·「QA 결과」 '- 회귀:'에 이름으로"}.get(pf, ""))
    if i >= 4:
        rv = s.get("리뷰 기록", "")
        if not re.search(r"판정:\s*확정", rv):
            miss.append("「리뷰 기록」에 '판정: 확정' 없음")
        if len(re.findall(r"^-\s*라운드\s*\d", rv, re.M)) > 3:
            miss.append("리뷰 라운드가 3회를 넘음 — 사람 판정 필요")
        if re.search(r"판정:\s*확정", rv):
            miss += review_evidence(goal, cfg, text)
    if stage == "merge":
        n = unchecked_conditions(text)
        if n:
            miss.append(f"완료 조건 미체크 {n}개 — 「완료 조건」 항목은 모두 '- [x]'여야 함('- [ ]'·체크박스 없는 항목)")
        miss += merge_checks(s.get("QA 결과", ""), cfg)
        miss += unverified_problems(s.get("QA 결과", ""), gids, cfg, s=s)
        miss += checked_run_problems(goal, cfg, s.get("QA 결과", ""), text)
        if profile(s) != "경량":
            miss += red_evidence(s.get("QA 결과", ""), gids, cfg)
            if syntax_only_cmd(cfg.get("test_cmd") or ""):
                miss.append("표준·강화 프로필 — test_cmd가 구문 검사만(syntax_check)이다. 구문 검사만으로는 동작을 확인하지 않는다: "
                            "완료 조건을 확인하는 자동 테스트를 두고 test_cmd에 넣는다")
        for did in mr_decision_ids(text):
            if simulated_block(decision_block(did, cfg)[1] or ""):
                if cfg.get("rehearsal") is True:   # 리허설 실행(환경변수 VF_REHEARSAL=1 — vf_git.config)만 통과
                    print(f"[state] SIMULATED-DECISION {did} — 리허설 실행의 시뮬레이션 결정(운영 승인 아님)")
                else:
                    miss.append(f"SIMULATED-DECISION {did} — 시뮬레이션 결정은 운영 승인이 아니다: 실제 결정자가 결정 블록을 "
                                "다시 적기 전 merge 불가(리허설 실행만 환경변수 VF_REHEARSAL=1 — 커밋된 설정으로는 열리지 않음)")
        miss += schema_problems(goal, cfg, s.get("QA 결과", ""))
        if profile(s) == "강화":
            ids, bad_lines = regression_ids(s.get("QA 결과", ""))
            if bad_lines:
                miss.append(f"강화 프로필 — 「QA 결과」 '- 회귀:' 줄에 테스트 식별자가 없음(자리표시·설명뿐): {', '.join(bad_lines[:3])}")
            if not ids:
                miss.append("강화 프로필 — 「QA 결과」에 '- 회귀: <돌린 회귀 테스트 이름>' 줄 필요"
                            "(test_x · Class.test_x · tests/x.py::name)")
            gone = [t for t in ids if not test_exists(t)]
            if gone:
                miss.append(f"강화 프로필 — 「QA 결과」 '- 회귀:'의 {', '.join(gone)}가 레포 테스트 파일에 없음 — 돌린 테스트 이름을 적는다")
            if ids:
                miss += regression_evidence(ids, s.get("QA 결과", ""))
    return miss


SIMULATED = re.compile(r"시뮬레이션|simulat", re.I)


def simulated_block(blk):
    """결정 블록이 시뮬레이션 결정(E2E·리허설 — 운영 승인 아님)이라고 적었는가."""
    return bool(SIMULATED.search(blk or ""))


def mr_decision_ids(text):
    """MR이 근거로 쓴 결정 ID(사람 결정·정책 결정·위험 인수 줄)."""
    t = re.sub(r"<!--.*?-->", "", text or "", flags=re.S)
    ids = set(re.findall(r"^\s*[-*]?\s*(?:사람 결정|정책 결정|위험 인수|사람 승인)\s*:\s*(D-\d+)", t, re.M))
    ids.update(re.findall(r"[(（]\s*승인\s*(D-\d+)\s*[)）]", t))   # RED 대체 승인(23차)도 시뮬레이션 검사 대상
    return sorted(ids)


# 위험 자기 분류 교차 확인(진단 평가 C6): '위험: 없음'이어도 바뀐 코드(추가된 줄)에 이런 식별자가 있으면 판단 근거를 적게 한다
RISK_WORDS = {"price", "amount", "tax", "discount", "refund", "payment", "charge", "invoice", "billing",
              "money", "currency", "auth", "authn", "authz", "authorize", "authentication", "login", "password", "passwd",
              "token", "secret", "permission", "permissions", "role", "roles", "admin", "delete", "drop", "truncate",
              "migrate", "migration", "purge"}   # 흔한 단어(total·remove)는 빼서 잡음을 줄인다
# 접두어로 보는 위험 어간 — authorization·authenticator·migrating·permissions·privileges 등(A20-01: 정확 일치만 보면 놓친다)
RISK_STEMS = ("auth", "migrat", "permiss", "privileg", "credential", "passw", "delet", "payment", "refund", "billing")
RISK_KO = re.compile(r"금액|요금|세금|할인|환불|결제|권한|인증|비밀번호|삭제")


def risk_tokens(line):
    """한 줄에서 위험 식별자 토큰 — snake_case·camelCase를 쪼개서 본다(A19-03: delete_account·paymentAmount도)."""
    out = set()
    for ident in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", line or ""):
        for part in ident.split("_"):
            for tok in re.findall(r"[A-Z]+(?=[A-Z][a-z]|\b|\d)|[A-Z]?[a-z]+|\d+", part):
                if tok.lower() in RISK_WORDS or tok.lower().startswith(RISK_STEMS):
                    out.add(tok.lower())
    out.update(m.group(0) for m in RISK_KO.finditer(line or ""))
    return out


def syntax_only_cmd(cmd):
    """test_cmd가 구문 검사(syntax_check)만 하는가 — 이어 붙인 명령 중 테스트 러너가 하나도 없으면 구문 검사만이다
    (A19-04: 테스트를 잇는 명령은 막지 않는다, A20-02: 'echo' 같은 것만 이어도 구문 검사만이다)."""
    if "syntax_check" not in cmd:
        return False
    # node로 테스트 파일(*.test.js·*.spec.mjs …)을 직접 돌리거나 node --test 도 테스트 실행이다 — node build.js 같은 것은 아니다
    return not re.search(r"\b(?:unittest|pytest|jest|vitest|mocha|ava|tap|nose2?|tox|go\s+test|cargo\s+test|"
                         r"(?:npm|pnpm|yarn)\s+(?:run\s+)?test|phpunit|rspec|gradle\w*\s+test|mvn\s+test|dotnet\s+test|"
                         r"node\s+(?:--test|\S+\.(?:test|spec)\.[cm]?[jt]sx?))(?![\w.-])", cmd)


def scope_problems(text, stage, cfg):
    """내 선점 범위 공지: 이 골의 내 착수 줄([~] … @나)이 있으면, 공지된 범위(원격 모드는 origin/<브랜치>의 REMAINING)가
    build부터 「설계」 바꿀 파일을, review부터 실제로 바꾼 파일(기록 제외)도 덮어야 한다 — 동료가 그 범위를 보고 피하거나 조율한다.
    착수 줄이 없으면(선점 흐름을 안 쓴 개인 레포 등) 검사하지 않는다."""
    import dupe
    gids = sorted(set(re.findall(r"\bG-\d{3,}\b", dupe.section(text, "골"))) - {"G-000"})
    if not gids or STAGES.index(stage) < 2:
        return []
    gid, me, cur = gids[0], vf_git.me(), vf_git.current_branch()
    rem = f"{vf_git.paths(cfg)['handoff']}/REMAINING.md"
    mine = re.compile(rf"^\s*-\s*\[~\]\s*.*(?<![\w-]){re.escape(gid)}(?![\w-]).*\(착수\s*@{re.escape(me)}\s+\d{{4}}-\d{{2}}-\d{{2}}\).*$", re.M)
    try:
        with open(rem, encoding="utf-8") as f:
            local = f.read()
    except OSError:
        return []
    if not mine.search(local):
        return []
    remote = cfg.get("remote", True) is not False and "origin" in vf_git.git("remote").split()
    if not remote:
        return []   # 로컬 모드(원격 없음)는 범위를 볼 동료가 없다 — 공지를 요구하지 않는다(scope는 로컬 커밋으로 쓸 수는 있다)
    where = f"origin/{cur}"
    m = mine.search(vf_git.git("show", f"{where}:{rem}") or "")
    sm = re.search(r"·\s*범위:\s*(.*)$", m.group(0)) if m else None
    files = dupe.scope_list(sm.group(1)) if sm else []
    how = f"python handoff.py scope {gid} --mr <MR> — 「설계」 바꿀 파일을 착수 줄에 붙여 push"
    if not files:
        return [f"선점 범위 공지 없음({where}의 착수 줄) — {how}. 동료가 범위를 보고 피하거나 조율한다"]
    need = dupe.planned_files(text)
    if STAGES.index(stage) >= 3:
        need += [f for f in dupe.touched_files(cfg) if not is_record(f, cfg)]
    out = [f for f in dict.fromkeys(need) if not any(dupe.path_hit(f, s) for s in files)]
    return [f"공지 범위 밖 파일: {', '.join(out[:5])}{' …' if len(out) > 5 else ''} — {how}(범위를 다시 공지)"] if out else []


def risk_code_hits(cfg):
    """기준 대비 지금 작업물에서 추가된 코드 줄(기록·테스트 파일 제외)에 나온 위험 식별자(최대 5개, 정렬)."""
    try:
        base = vf_git.base_tree(cfg["base"])
        cur = vf_git.snapshot()
        names = code_diff(base, cur, cfg)[0]
    except (RuntimeError, KeyError):
        return []
    tests = {os.path.normpath(p) for p in _test_files()}
    hits = set()
    for f in names:
        if os.path.normpath(os.path.join(".", f)) in tests or os.path.normpath(f) in tests:
            continue
        diff = vf_git.git("diff", "-U0", base, cur, "--", f)
        for line in diff.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                hits.update(risk_tokens(line[1:]))
    return sorted(hits)[:5]


def design_policy_items(goal, cfg):
    """최근 유효 설계 확인 회차의 'POLICY: <항목> — <이유>' 항목 이름('없음' 제외)."""
    got = latest_round("d", goal, cfg) if goal else None
    if not got:
        return []
    items = []
    for v in re.findall(r"^POLICY:[ \t]*(.*)$", got[2], re.M):
        name = re.split(r"\s+[—–]\s+", v.strip(), maxsplit=1)[0].strip()
        if name and not _none(name):
            items.append(name)
    return items


def design_policy_problems(goal, cfg, s):
    """설계 확인(Codex)이 적은 'POLICY: <항목> — <이유>'는 MR 「영향·위험」 '- 미확인:' 항목이나 '- 정책 결정: D-nnn — <항목>'에
    그대로 있어야 한다(진단 평가 C6 — 정책 판단 필요성을 구현 에이전트 혼자 분류하지 않게). 최근 유효 설계 확인 회차 기준."""
    items = design_policy_items(goal, cfg)
    if not items:
        return []
    risk = re.sub(r"<!--.*?-->", "", s.get("영향·위험", ""), flags=re.S)
    listed = [x for line in re.findall(r"^\s*[-*]?\s*(?:미확인|정책 미결)\s*:(.*)$", risk, re.M) for x in (_items(line) or [])]
    gids = re.findall(r"\bG-\d{3,}\b", goal or "")
    # 정책 결정 줄은 그 결정이 실재하고 골 ID와 항목을 적었을 때만 POLICY를 덮는다(A19-02 — 없는 D-999로 비켜 가지 못하게)
    listed += [item for did, item in re.findall(r"^\s*[-*]?\s*정책 결정\s*:\s*(D-\d+)\s*[—–:-]+\s*(\S.*?)\s*$", risk, re.M)
               if _decision_names(did, item, gids, cfg)]
    lack = [x for x in items if not any(_same(x, y) for y in listed)]
    return [f"설계 확인 POLICY 「{x}」가 MR 「영향·위험」 '- 미확인:'(또는 '- 정책 결정: D-nnn — {x}')에 없음 — 그대로 옮긴다(사람 결정 전 merge 차단)"
            for x in lack]


def design_major_problems(goal, cfg, s):
    """설계 확인이 CONFIRM이어도 그 회차의 blocker·major FINDING은 「설계 확인」에 '- 반영: <id> — <어떻게>' 또는
    '- 넘김: <id> — 골 후보 <사유>'로 처리를 적어야 구현에 들어간다(진단 평가 C7)."""
    got = latest_round("d", goal, cfg) if goal else None
    if not got:
        return []
    dc = re.sub(r"<!--.*?-->", "", s.get("설계 확인", ""), flags=re.S)
    done = set(re.findall(r"^\s*[-*]?\s*(?:반영|넘김)\s*:\s*([A-Za-z][A-Za-z0-9_-]*)\s*[—–:-]+\s*\S.{4,}$", dc, re.M))
    # 2회 뒤 사람 판정 경로: '- 사람 결정: D-nnn — <ID…>'가 처리다(결정의 실재·골·회차는 위 설계 확인 검사가 본다)
    for ids in re.findall(r"^\s*[-*]?\s*사람 결정\s*:\s*D-\d+\s*[—–:-]+\s*(.+)$", dc, re.M):
        done.update(FID.findall(ids))
    return [f"설계 확인 {x['sev']} {x['id']}가 처리되지 않음 — 「설계 확인」에 '- 반영: {x['id']} — <어떻게>' "
            f"(또는 '- 넘김: {x['id']} — 골 후보 <사유>')"
            for x in findings(got[2]) if x["sev"].lower() in ("blocker", "major") and x["id"] not in done]


def regression_ids(qa):
    """「QA 결과」 '- 회귀:' 줄들(여럿 가능 — JS 식별자는 한 줄에 하나)의 (테스트 식별자, 잘못된 줄). 안내 주석 밖만.
    값의 '<…>'는 지우지 않는다 — 'renders <div>'처럼 실제 테스트 이름일 수 있다(A16-01). 값 전체가 자리표시('<…>')이거나
    식별자가 하나도 없는 줄은 잘못된 줄로 돌려준다(다른 줄이 있다고 무시되지 않게)."""
    qa = re.sub(r"<!--.*?-->", "", qa or "", flags=re.S)
    ids, bad = [], []
    for v in re.findall(r"^\s*[-*]?\s*회귀\s*:(.*)$", qa, re.M):
        got = [] if re.fullmatch(r"\s*<[^>\n]*>\s*", v) else test_ids(v)
        if got:
            ids += got
        else:
            bad.append(v.strip()[:60] or "(빈 값)")
    return ids, bad


# 테스트 식별자 규칙은 testids.py 한 곳(mr_check·qa_run 공용) — 예전 이름으로 그대로 쓴다
from testids import (TEST_ID, JS_TEST_START, JS_TRAIL_REF, JS_TEST_FILE, CODE_REF, js_parts, js_names,  # noqa: E402,F401
                     test_ids, _test_files, test_exists, _last, _qual, test_match)


CHECKED_LINE = re.compile(r"^CHECKED:[ \t]*(\d+)\s*[—–-]+\s*(\S.*)$", re.M)


def checked_ref_problems(evidence, need_test=False):
    """리뷰 CHECKED 근거 한 줄의 문제. '미충족 — <id>'는 근거가 아니라 판정이라 검사하지 않는다.
    근거 = 레포 테스트 파일에 정의된 테스트 이름(test_exists) 또는 '파일:줄'(파일이 있고 줄이 그 안). 근거가 실재하지 않거나
    없으면 리뷰가 확인했다고 볼 수 없다. need_test(표준·강화)면 테스트 이름이 하나 이상 — 완료 조건을 실행된 테스트에 묶는다."""
    ev = (evidence or "").strip()
    if ev.startswith("미충족"):
        return []
    tids = test_ids(ev)
    refs = CODE_REF.findall(ev)
    if not tids and not refs:
        return [f"근거에 테스트 이름도 '파일:줄'도 없음: '{ev[:50]}'"]
    bad = [f"근거 테스트 {t}가 레포 테스트 파일에 없음" for t in tids if not test_exists(t)]
    for path, line in refs:
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                n = sum(1 for _ in f)
        except OSError:
            bad.append(f"근거 파일 {path} 없음")
            continue
        if not 1 <= int(line) <= n:
            bad.append(f"근거 {path}:{line} — 줄 범위 밖(1~{n})")
    if need_test and not tids:
        bad.append("표준·강화 프로필 — 근거에 이 조건을 확인하는 테스트 이름이 필요(파일:줄만으로는 실행 증거에 묶이지 않음)")
    return bad


def unmet_problems(evidence, text):
    """'미충족 — <FINDING id>' 근거의 모순(A9-03): 같은 응답의 FINDING에 그 id가 없거나, 응답이 VERDICT: CONFIRM이면
    (충족 안 된 완료 조건이 있는데 확정) 무효."""
    ev = (evidence or "").strip()
    if not ev.startswith("미충족"):
        return []
    bad = []
    ids = FID.findall(ev[len("미충족"):])
    known = {x["id"] for x in findings(text)}
    if not ids or not any(i in known for i in ids):
        bad.append(f"'미충족' 근거가 이 응답의 FINDING id를 가리키지 않음: '{ev[:40]}'")
    if re.search(r"^VERDICT:\s*CONFIRM", text, re.M):
        bad.append("'미충족' 완료 조건이 있는데 VERDICT: CONFIRM — 모순")
    return bad


def checked_map(goal, cfg, extra_closed=()):
    """유효 라운드를 차례로 보며 완료 조건별 근거 이력을 만든다(A10-02·A11-02).
    (r1의 {번호: [근거…]} 또는 None, {번호: 마지막 근거(그 뒤 '미충족' 없음)}, {번호: 닫히지 않은 '미충족' FINDING id}, 문제 목록).
    어느 라운드든 'CHECKED: n — 미충족 — <id>'는 그 라운드의 FINDING id여야 하고, 뒤 라운드 RESOLVED(또는 사람 결정
    extra_closed)로 닫혀야 하며, 그 뒤 라운드가 그 조건의 새 근거를 달아야 한다."""
    rounds = valid_rounds("r", goal, cfg)
    first, final, pending, early, bad = {}, {}, {}, {}, []
    for n, t in rounds:
        here = {x["id"] for x in findings(t)}
        for i in resolved_ids(t):   # 같은 라운드 안에서는 RESOLVED가 먼저 — 닫고 새 근거를 다는 순서
            for k in pending:
                pending[k].discard(i)
        for k, ev in CHECKED_LINE.findall(t):
            k, ev = int(k), ev.strip()
            if n == 1:
                first.setdefault(k, []).append(ev)
            if ev.startswith("미충족"):
                ids = set(FID.findall(ev[len("미충족"):]))
                if not ids or not ids <= here:
                    bad.append(f"리뷰 r{n} CHECKED {k}번 '미충족'이 그 라운드의 FINDING id를 가리키지 않음")
                pending.setdefault(k, set()).update(ids)
                final.pop(k, None)   # 미충족 뒤에는 새 근거가 필요하다
                early.pop(k, None)
            elif pending.get(k):
                early[k] = ev   # A12-01: 지적이 닫히기 전에 단 근거는 확정 근거가 아니다(미충족 → RESOLVED → 새 근거 순서)
            else:
                final[k] = ev
    for k in pending:
        if pending[k] and pending[k] <= set(extra_closed) and k not in final and k in early:
            final[k] = early[k]   # 사람 판정: 결정이 지적을 닫는 시점은 기록 밖 — 미충족 뒤에 단 근거면 받는다(실재·QA 대조는 그대로)
        pending[k] -= set(extra_closed)
    return (first if any(n == 1 for n, _ in rounds) else None), final, {k: v for k, v in pending.items() if v}, bad


def checked_complete_problems(goal, cfg, text, extra_closed=()):
    """qa·merge: 리뷰 근거를 review.py가 받을 때와 같은 규칙으로 다시 본다(A9-03·A10-01·A10-02·A11-02 — 원문이 뒤에
    바뀌거나 지워져도). r1 CHECKED가 지금 「완료 조건」 1..N을 한 번씩. 조건마다 마지막 근거가 checked_ref_problems를 통과
    (실재하는 테스트·파일:줄, 표준·강화는 테스트 이름). '미충족'은 RESOLVED(사람 판정이면 결정 줄의 ID — extra_closed)로
    닫히고 그 뒤 새 근거가 있어야 한다. 사람 판정도 같은 검사를 받는다 — 사람이 정하는 것은 지적의 처리이지 테스트 실행이 아니다."""
    first, final, pending, bad = checked_map(goal, cfg, extra_closed)
    if first is None:
        return []   # 라운드 기록 자체가 없는 경우는 review_evidence·human_review가 막는다
    n_items = len(completion_items(text))
    need = profile(sections(vf_git.normalize_mr(text, cfg))) != "경량"
    bad = [f"{b} — 리뷰 재실행" for b in bad]
    lack = [str(i) for i in range(1, n_items + 1) if len(first.get(i, [])) != 1]
    extra = [str(k) for k in first if not 1 <= k <= n_items]
    if lack or extra:
        bad.append(f"리뷰 r1 CHECKED가 완료 조건 1~{n_items}을 한 번씩 덮지 않음(빠지거나 겹침: {', '.join(lack + extra)}) — 리뷰 재실행")
    later = sorted({int(k) for n, t in valid_rounds("r", goal, cfg) if n > 1 for k, _ in CHECKED_LINE.findall(t)
                    if not 1 <= int(k) <= n_items})
    if later:
        bad.append(f"리뷰 2·3라운드 CHECKED 번호 {', '.join(map(str, later))}가 완료 조건 1~{n_items} 밖 — 리뷰 재실행")
    for k in range(1, n_items + 1):
        if pending.get(k):
            bad.append(f"리뷰 CHECKED {k}번 '미충족' FINDING {', '.join(sorted(pending[k]))}이 뒤 라운드 RESOLVED로 닫히지 않음 — "
                       "고친 뒤 다음 라운드에서 닫는다(3라운드 뒤면 사람 판정)")
            continue
        ev = final.get(k)
        if ev is None:
            if first.get(k):
                bad.append(f"완료 조건 {k}번의 확인 근거 없음 — '미충족'을 닫은 라운드가 'CHECKED: {k} — <테스트 이름·파일:줄>'을 달아야 한다")
            continue
        bad += [f"리뷰 CHECKED {k}번 {p} — 리뷰 재실행" for p in checked_ref_problems(ev, need)]
    return bad


def human_closed_ids(text, cfg=None):
    """「리뷰 기록」이 사람 판정이면 그 결정 줄('- 사람 결정: D-nnn — <ID들>')의 지적 ID 중 **결정 블록(DECISIONS '## D-nnn')에도
    적힌 것**, 아니면 빈 집합 — MR 문구만으로 사람이 다루지 않은 지적을 닫지 못한다(A14-01, 심각도 무관).
    완료 조건의 최종 근거는 이 ID로만 갈린다 — checked_complete_problems·checked_tests가 같은 값을 쓴다(A13-01)."""
    rv = sections(text or "").get("리뷰 기록", "")
    h = HUMAN_REVIEW.search(rv)
    if not h:
        return set()
    dl = re.search(rf"^\s*-\s*사람 결정:\s*{h.group(1)}(?!\d)\s*[—–-]+\s*(\S.*)$", rv, re.M)
    if not dl:
        return set()
    blk = decision_block(h.group(1), cfg or vf_git.config())[1] or ""
    return {i for i in FID.findall(dl.group(1)) if has_fid(i, blk)}


def checked_tests(goal, cfg, text=None):
    """완료 조건마다 최종 리뷰 근거(checked_map — 사람 판정이면 결정 ID 포함)의 테스트 이름 {조건 번호: [이름…]}."""
    return {k: test_ids(ev) for k, ev in checked_map(goal, cfg, human_closed_ids(text, cfg))[1].items()}


def checked_run_problems(goal, cfg, qa, text=None):
    """merge: 리뷰가 완료 조건 근거로 든 테스트가 QA 실행 기록 tests에서 모두 ok — [x]가 실행된 테스트에 묶인다."""
    cited = {k: v for k, v in checked_tests(goal, cfg, text).items() if v}
    if not cited:
        return []
    tests = (_qa_record(qa) or {}).get("tests")
    if not isinstance(tests, dict):
        return ["리뷰 근거 테스트의 실행 결과 없음 — QA 기록에 테스트별 결과(tests)가 없다. test_cmd를 상세 출력(-v)으로 qa_run"]
    bad = []
    for k, ids in sorted(cited.items()):
        for t in ids:
            got = [v for name, v in tests.items() if test_match(t, name)]
            if not got or any(v != "ok" for v in got):
                bad.append(f"완료 조건 {k}의 근거 테스트 {t}({'·'.join(got) or 'QA 기록에 없음'})")
    return [f"리뷰 근거 테스트가 QA 실행에서 ok가 아님 — {', '.join(bad[:4])}"] if bad else []


# 검증·결정 상태(qa-gate.md 「상태 셋」) — merge 출력과 verify-evidence가 같은 이름을 쓴다
#   UNVERIFIED     기술적 미검증(「QA 결과」 '- 미검증·생략 항목과 사유:'). 결정으로 통과가 되지 않는다 — 항상 차단
#   ACCEPTED-RISK  미검증 항목의 배포 위험을 사용자가 인수(D-nnn). 상태로만 남고 게이트는 열리지 않는다 — 머지는 사용자가 직접 우회
#   POLICY-PENDING 정책 미결(「영향·위험」 '- 미확인:'이 정책 결정·해소로 닫히지 않음). 위험 인수로는 닫히지 않는다 — 차단
STATES = ("UNVERIFIED", "ACCEPTED-RISK", "POLICY-PENDING")
ITEM_SPLIT = r"[;；]"   # 항목 구분은 ';' — 자연어 항목 속 쉼표로 한 항목이 둘로 갈리지 않게(E2E S1 t4w1)


def _items(val):
    """'항목; 항목' 값의 항목들. 정확히 '없음'이면 []. 먼저 나눈 뒤 항목마다 본다 — 빈 항목이나 자리표시(<…>)가 하나라도
    있으면 None(값이 없다 = 판정 불가, 그 줄 자체가 미결). 자리표시를 먼저 지우면 '정책 A; <정책 B>'의 B가 사라진다(A15-01)."""
    raw = (val or "").strip()
    if _none(raw):
        return []
    items = [x.strip() for x in re.split(ITEM_SPLIT, raw)]
    if not raw or any(not x or re.search(r"<[^>\n]*>", x) for x in items):
        return None
    return items


def _norm_item(x):
    return " ".join((x or "").split()).rstrip(".").strip()


def _same(item, other):
    """항목 일치는 정규화한 전체 문자열로만(A9-02 — 부분 문자열로 다른 항목의 결정·해소를 재사용하지 못하게)."""
    return _norm_item(item) == _norm_item(other)


def _decision_names(did, item, gids, cfg):
    """결정 D-nnn이 유효하고(이 골 ID) 그 블록이 항목을 적었는가 — 결정이 실제로 그 항목을 다뤘다는 연결(A9-02)."""
    if decision_problem(did, gids, cfg):
        return False
    blk = decision_block(did, cfg)[1] or ""
    return _norm_item(item) in " ".join(blk.split())


def _resolution_ok(why, qa):
    """'- 해소: <항목> — <근거>'의 근거가 실재하는가: 테스트 이름이면 레포에 정의돼 있고 QA 실행 기록 tests에서 ok,
    '파일:줄'이면 파일이 있고 줄이 그 안(A9-02 — 이름처럼 보이는 문자열만으로 닫지 않는다)."""
    tids = test_ids(why)
    refs = CODE_REF.findall(why)
    if not tids and not refs:
        return False
    if checked_ref_problems(why):
        return False
    if tids:
        tests = (_qa_record(qa) or {}).get("tests")
        if not isinstance(tests, dict):
            return False
        for t in tids:
            got = [v for k, v in tests.items() if test_match(t, k)]
            if not got or any(v != "ok" for v in got):
                return False
    return True


def verification_states(s, gids, cfg, design_items=()):
    """MR 섹션에서 검증·결정 상태 [(상태, 항목, 근거)]. 상태는 STATES 중 하나 — 비면 막을 것이 없다.
    값이 비었거나 자리표시(<…>)뿐인 줄은 '없음'이 아니다 — 그 줄 자체가 UNVERIFIED·POLICY-PENDING이다(A9-01)."""
    qa = re.sub(r"<!--.*?-->", "", s.get("QA 결과", ""), flags=re.S)
    risk = re.sub(r"<!--.*?-->", "", s.get("영향·위험", ""), flags=re.S)
    out = []
    m = re.search(r"^\s*[-*]?\s*미검증·생략 항목과 사유\s*:(.*)$", qa, re.M)
    accepted = []
    for did, item in re.findall(r"^\s*[-*]?\s*(?:위험 인수|사람 승인)\s*:\s*(D-\d+)\s*[—–:-]+\s*(\S.*?)\s*$", qa, re.M):
        if _decision_names(did, item, gids, cfg):
            accepted.append((item, did))
    items = _items(m.group(1)) if m else []
    if items is None:
        out.append(("UNVERIFIED", f"(값 없음: '{m.group(1).strip()[:40]}')", ""))
        items = []
    for x in items:
        hit = next((d for a, d in accepted if _same(x, a)), "")
        out.append(("ACCEPTED-RISK" if hit else "UNVERIFIED", x, hit))
    closed = [item for did, item in re.findall(r"^\s*[-*]?\s*정책 결정\s*:\s*(D-\d+)\s*[—–:-]+\s*(\S.*?)\s*$", risk, re.M)
              if _decision_names(did, item, gids, cfg)]
    # 설계 확인(Codex)이 POLICY로 낸 항목은 사람 결정으로만 닫힌다 — 구현자가 테스트 이름으로 '해소'하지 못한다(E2E S6 t4s2)
    closed += [item for item, why in re.findall(r"^\s*[-*]?\s*해소\s*:\s*(\S.*?)\s*[—–]+\s*(\S.*?)\s*$", risk, re.M)
               if _resolution_ok(why, s.get("QA 결과", "")) and not any(_same(item, d) for d in design_items)]
    for label in ("미확인", "정책 미결"):
        for line in re.findall(rf"^\s*[-*]?\s*{label}\s*:(.*)$", risk, re.M):
            got = _items(line)
            if got is None:
                out.append(("POLICY-PENDING", f"(「{label}」 값 없음: '{line.strip()[:40]}' — 없으면 정확히 '없음')", ""))
                continue
            out += [("POLICY-PENDING", x, "") for x in got if not any(_same(x, c) for c in closed)]
    return out


def unverified_problems(qa, gids, cfg, s=None):
    """merge: 「QA 결과」 '- 미검증·생략 항목과 사유:'는 필수(없으면 정확히 '없음'). 미검증은 결정으로 통과가 되지 않는다 —
    위험 인수(D-nnn, 블록이 그 항목을 적음)는 상태(ACCEPTED-RISK)로만 남고 차단은 그대로(머지는 사용자가 직접 우회).
    「영향·위험」 '- 미확인:' 항목은 '- 정책 결정: D-nnn — <항목>'(블록이 그 항목을 적음) 또는
    '- 해소: <항목> — <QA에서 ok인 테스트 이름·실재하는 파일:줄>'로 닫혀야 한다(POLICY-PENDING). 항목은 전체 일치."""
    s = s if s is not None else {"QA 결과": qa or ""}
    qa_clean = re.sub(r"<!--.*?-->", "", qa or "", flags=re.S)
    if not re.search(r"^\s*[-*]?\s*미검증·생략 항목과 사유\s*:", qa_clean, re.M):
        return ["「QA 결과」에 '- 미검증·생략 항목과 사유:' 줄 없음(없으면 '없음')"]
    miss = []
    goal = ",".join(sorted(set(gids)))
    for st, item, did in verification_states(s, gids, cfg, design_items=design_policy_items(goal, cfg)):
        if st == "UNVERIFIED":
            miss.append(f"UNVERIFIED {item} — 검증한다(미검증은 결정으로 통과되지 않는다. 배포 위험을 인수하려면 사용자 결정 "
                        "'- 위험 인수: D-nnn — <항목>' + 사용자가 직접 우회)")
        elif st == "ACCEPTED-RISK":
            miss.append(f"ACCEPTED-RISK {item} (위험 인수 {did}) — 미검증 상태 그대로. 게이트는 열리지 않는다: 머지는 사용자가 "
                        "직접 우회하고 REMAINING에 부채로")
        else:
            miss.append(f"POLICY-PENDING {item} — 「영향·위험」 '- 정책 결정: D-nnn — <항목>'(사람 결정, 블록에 그 항목) 또는 "
                        "'- 해소: <항목> — <QA에서 ok인 테스트 이름·파일:줄>'로 닫는다(위험 인수로는 닫히지 않는다)")
    return miss


def _qa_record(qa):
    """「QA 결과」 대상의 QA 기록(.vibe/qa/<tree>.json) dict — qa_run.find_record(tree 객체가 없어도 기록 이름으로). 없으면 None."""
    import qa_run
    rec = qa_run.find_record(qa_run.target(qa))[1]
    return rec if isinstance(rec, dict) else None


def red_valid(red):
    """RED 기록이 RED인가: exit≠0이고 출력에서 실패한 테스트를 찾았다(tests에 fail, 또는 통과+건너뜀 < 전체) — 명령 오류는 RED가 아니다(B-06)."""
    if not isinstance(red, dict) or red.get("exit") in (0, None) or red.get("changed_code"):
        return False   # 실행 중 코드를 바꾼 실행은 그 tree의 RED가 아니다(A11-03)
    tests = red.get("tests") if isinstance(red.get("tests"), dict) else {}
    # 실패한 테스트 이름이 하나는 있어야 한다 — 수만으로는 수집·실행 오류와 구별되지 않는다(A10-06, test_cmd는 -v로)
    return any(v == "fail" for v in tests.values())


def select_red(qa, gids=(), cfg=None):
    """merge와 export-evidence가 같이 쓰는 RED 선택(A9-06 — 로컬이 고른 RED를 그대로 커밋해 재연이 같은 것을 본다):
    이 브랜치·이 골·이 기준의 RED 기록(qa_run --red --mr) 중 red_valid이고, 증거 판이 지금 판이며, QA(GREEN)보다 먼저 돌았고
    (started), 실패한 테스트 하나 이상이 QA 기록 tests에서 ok(RED→GREEN)인 가장 최근 것. QA에 tests가 없으면 연결할 수 없어 없음. 없으면 ''."""
    import glob
    import json
    cfg = cfg or vf_git.config()
    cur = vf_git.current_branch()
    base = current_base(cfg)
    rec = _qa_record(qa) or {}
    green = rec.get("tests") if isinstance(rec.get("tests"), dict) else None
    best = ("", "")
    for p in sorted(glob.glob(os.path.join(".vibe", "qa", "red-*.json"))):
        try:
            with open(p, encoding="utf-8") as f:
                red = json.load(f)
        except (OSError, ValueError):
            continue
        if not red_valid(red) or red.get("branch") != cur or red.get("base") != base:
            continue
        if not set(str(red.get("goal") or "").split(",")) & set(gids) or _old_schema(red.get("schema")):
            continue
        if rec.get("started") and not _before(red.get("started"), rec["started"]):
            continue   # GREEN 뒤에 돌린 RED는 구현 전 실패의 증거가 아니다(A9-05)
        failed = [k for k, v in (red.get("tests") or {}).items() if v == "fail"]
        if green is None or not any(green.get(k) == "ok" for k in failed):
            continue   # RED에서 실패한 테스트가 GREEN에서 ok여야 RED→GREEN이다(GREEN에 테스트별 결과가 없으면 연결 불가)
        if str(red.get("started", "")) >= best[0]:
            best = (str(red.get("started", "")), p)
    return best[1]


def _before(a, b):
    """시각 문자열 a가 b보다 앞인가(ISO 8601, 시간대·마이크로초 포함 — 문자열이 아니라 시각으로 비교). 못 읽으면 False."""
    import datetime
    try:
        return datetime.datetime.fromisoformat(str(a)) < datetime.datetime.fromisoformat(str(b))
    except (TypeError, ValueError):
        return False


def red_evidence(qa, gids=(), cfg=None):
    """표준·강화 merge: select_red가 고른 RED 기록이 있어야 한다."""
    if select_red(qa, gids, cfg):
        return []
    if RED_ALT.search(_strip_comments(qa)):
        bad = red_alt_problems(qa, cfg, gids)
        if not bad:
            print("[state] RED-ALT — 동작 불변 변경: 바뀌지 않은 기존 테스트가 QA에서 ok(실패 재현 대신)")
        return bad
    return ["RED 증거 없음 — 구현 전 qa_run.py --red --mr <MR> (표준·강화: 이 브랜치·골·기준에서 구현 전에 실패한 테스트가 QA 기록에서 ok여야 함)"]


RED_ALT = re.compile(r"^\s*[-*]?\s*RED 대체\s*:\s*동작 불변\s*[—–:-]+\s*(\S.*)$", re.M)


def _strip_comments(t):
    return re.sub(r"<!--.*?-->", "", t or "", flags=re.S)


def changed_test_files(cfg):
    """기준 대비 지금 작업물에서 바뀐 테스트 파일 — 추가·수정·삭제·이름 변경 모두(A22-03: 지운 파일은 지금 목록에 없으므로
    경로 모양으로도 본다)."""
    base = vf_git.base_tree(cfg["base"])
    out = vf_git.git("diff", "--name-status", "-M", base, vf_git.snapshot(), check=True)
    names = [p for line in out.splitlines() for p in line.split("\t")[1:] if p]
    tests = {os.path.normpath(p) for p in _test_files()}
    return sorted({f for f in names if os.path.normpath(f) in tests or is_test_path(f)})


def is_test_path(p):
    """경로 모양만으로 테스트 파일인가(testids._test_files와 같은 기준 — 지운 파일 판별용)."""
    p = p.replace("\\", "/")
    f = p.rsplit("/", 1)[-1]
    return bool(re.search(r"(^|/)tests?/", p) or f.startswith("test") or "_test" in f or JS_TEST_FILE.search(f))


def red_alt_problems(qa, cfg, gids=()):
    """RED 대체(진단 평가 C7 — 설정·의존성·동작 불변 리팩터링은 실패 재현이 어색하다): 「QA 결과」
    '- RED 대체: 동작 불변 — <기존 테스트 이름…> (승인 D-nnn)'. 이름 하나 이상이 레포에 있고 QA 기록에서 ok,
    테스트 파일은 기준 대비 하나도 바뀌지 않아야 한다(추가·수정·삭제 — 바꾼 테스트로 동작 불변을 증명하지 않는다).
    테스트가 그대로인 것은 동작 불변의 증명이 아니다 — 설정 파일 하나로도 동작이 바뀐다(A22-01·23차). 그래서 '동작 불변'은
    사람이 승인한다: 결정 블록이 이 골 ID와 'RED 대체'를 적어야 하고, 시뮬레이션 결정이면 merge에서 막힌다(mr_decision_ids)."""
    m = RED_ALT.search(_strip_comments(qa))
    ids = test_ids(re.sub(r"[(（]\s*승인\s*D-\d+\s*[)）]", " ", m.group(1))) if m else []
    if not ids:
        return ["RED 대체: '- RED 대체: 동작 불변 — <기존 테스트 이름> (승인 D-nnn)'에 테스트 이름이 없음"]
    bad = [f"RED 대체: {t}가 레포 테스트 파일에 없음" for t in ids if not test_exists(t)]
    ok = re.search(r"[(（]\s*승인\s*(D-\d+)\s*[)）]", m.group(1))
    if not (ok and _decision_names(ok.group(1), "RED 대체", list(gids), cfg)):
        bad.append("RED 대체는 사람 승인이 있어야 한다 — 테스트가 그대로인 것은 동작 불변의 증명이 아니다. RED(qa_run.py --red --mr)를 "
                   "남기거나, 결정 블록(D-nnn)에 이 골 ID와 'RED 대체'를 적고 '- RED 대체: 동작 불변 — <테스트> (승인 D-nnn)'")
    try:
        changed = changed_test_files(cfg)
    except (RuntimeError, KeyError):
        changed = ["(기준 비교 실패)"]
    if changed:
        bad.append(f"RED 대체는 테스트 파일이 그대로일 때만 — 바뀐 테스트 {', '.join(changed[:3])}(동작이 바뀌면 RED: qa_run.py --red --mr)")
    bad += [x.replace("강화 프로필 — 회귀", "RED 대체") for x in regression_evidence(ids, qa)]
    return bad


def _old_schema(v):
    try:
        return int(v) < vf_git.EVIDENCE_SCHEMA
    except (TypeError, ValueError):
        return True


def schema_problems(goal, cfg, qa):
    """로컬 merge도 증거 판을 본다(A9-10 — 재연은 낮은 판을 LEGACY로 거른다): 이 골의 유효 설계 확인·리뷰 기록과 QA 기록의
    schema가 지금 판(EVIDENCE_SCHEMA)이어야 한다. 낮으면 같은 코드에서 다시 돌린다(review.py·qa_run.py)."""
    old = []
    for kind in ("d", "r"):
        for n, _ in valid_rounds(kind, goal, cfg):
            rec = os.path.join(REVIEW_DIR, f"{kind}{n}.{'meta' if kind == 'd' else 'tree'}")
            if _old_schema(record_fields(rec).get("schema")):
                old.append(f"{kind}{n}")
    q = _qa_record(qa)
    if q is not None and _old_schema(q.get("schema")):
        old.append("QA 기록")
    return [f"LEGACY 증거 판 < v{vf_git.EVIDENCE_SCHEMA}: {', '.join(old)} — 같은 코드에서 다시 돌린다(review.py·qa_run.py)"] if old else []


def regression_evidence(ids, qa):
    """강화 merge: '- 회귀:' 식별자마다 QA 기록(.vibe/qa/<tree>.json) 'tests'에 같은 이름(test_match)이 있고 모두 ok."""
    tests = (_qa_record(qa) or {}).get("tests")
    if not isinstance(tests, dict):
        return ["회귀 테스트 실행 증거 없음 — test_cmd를 상세 출력(-v)으로 qa_run"]
    bad = []
    for t in ids:
        got = [v for k, v in tests.items() if test_match(t, k)]
        if not got or any(v != "ok" for v in got):
            bad.append(f"{t}({'·'.join(got) or '기록 없음'})")
    return [f"강화 프로필 — 회귀 {', '.join(bad)} 실행 증거 없음(QA 기록 tests에 ok 아님) — 고치고 qa_run(-v) 다시"] if bad else []


HUMAN_REVIEW = re.compile(r"판정:\s*확정\s*[(（]\s*사람 판정\s*(D-\d+)")


def human_review(did, goal, cfg, text):
    """3라운드 뒤 사람 결정으로 재개(review-loop.md 「사람 결정 뒤 재개」): 유효 r3 + 결정 블록(골 ID) + 남은 blocker ID.
    결정 뒤 코드 변경은 리뷰 tree가 아니라 QA 대상 tree가 잡는다(QA를 지금 작업물에서 다시)."""
    rounds = valid_rounds("r", goal, cfg)
    miss = []
    if [n for n, _ in rounds] != [1, 2, 3]:   # B-05: r3 하나만 남긴 것은 3라운드를 다 쓴 것이 아니다
        miss.append(f"「리뷰 기록」 사람 판정 {did}: 유효 기록 r1·r2·r3가 모두 있어야 함(지금 "
                    f"{', '.join(f'r{n}' for n, _ in rounds) or '없음'}) — 사람 판정은 3라운드 뒤에만(그 전엔 다음 라운드)")
    why = decision_problem(did, re.findall(r"\bG-\d{3,}\b", goal), cfg)
    if why:
        miss.append(f"「리뷰 기록」 사람 판정 {did}: {why} — 결정을 D-nnn으로 기록하고 이 골 ID를 적는다")
    miss += [f"r{n}: {p} — 리뷰 재실행" for n, t in rounds for p in resolved_problems(t)]
    miss += decision_cover(did, sections(text).get("리뷰 기록", ""), ledger(rounds, GATE_SEVS), cfg, "리뷰 기록")
    # 사람이 정한 지적 ID만 '미충족'을 닫는다 — 완료 조건마다 실재하는 근거는 그대로 필요(A11 — 사람 판정 경로도 같은 검사)
    miss += checked_complete_problems(goal, cfg, text, extra_closed=human_closed_ids(text, cfg))
    old = record_fields(os.path.join(REVIEW_DIR, "r3.tree")).get("conds")
    if rounds and rounds[-1][0] == 3 and not old:
        miss.append("리뷰 기록에 완료 조건 해시 없음(r3.tree) — 리뷰 재실행")
    elif old and old != completion_hash(text):
        miss.append("리뷰 뒤 완료 조건이 바뀜(r3.tree) — 리뷰 재실행(review.py --round 1)")
    if rounds and rounds[-1][0] == 3:
        why = contract_problem(os.path.join(REVIEW_DIR, "r3.tree"), text)
        if why:
            miss.append(why)
        miss += decision_tree_problems(did, sections(text).get("리뷰 기록", ""), cfg)
    return miss


def decision_tree_problems(did, sec, cfg):
    """사람 결정은 그 결정이 본 tree(r3)에 묶인다: '- 사람 결정: D-nnn — <IDs> (tree <sha>)'. 그 tree 뒤 코드 변경은
    QA만으로 넘어가지 않고 새 사람 판정이 필요하다(review-loop.md 「사람 결정 뒤 재개」)."""
    m = re.search(rf"^\s*-\s*사람 결정:\s*{did}(?!\d).*?\(\s*tree\s+([0-9a-f]{{7,40}})\s*\)", sec, re.M)
    with open(os.path.join(REVIEW_DIR, "r3.tree"), encoding="utf-8") as f:
        r3 = f.readline().strip()
    if not m:
        return [f"「리뷰 기록」 '- 사람 결정: {did} — <ID들> (tree <sha>)'에 결정이 본 tree 없음 — r3 tree({r3[:10]})를 적는다"]
    if not r3.startswith(m.group(1)):
        return [f"「리뷰 기록」 사람 결정 {did}의 tree {m.group(1)[:10]}가 r3 tree({r3[:10]})와 다름 — 결정이 본 tree를 적는다"]
    try:
        code = changed_since(r3, cfg, record_fields(os.path.join(REVIEW_DIR, "r3.tree")).get("code_tree", ""))
    except RuntimeError:
        return [f"r3 tree를 읽을 수 없음({r3[:10]}) — 리뷰 재실행"]
    if code:
        shown = ", ".join(code[:3]) + (" …" if len(code) > 3 else "")
        return [f"사람 판정 뒤 코드 변경({shown}) — 사람 재판정 필요(새 D-nnn, 바뀐 tree 명시)"]
    return []


def review_evidence(goal, cfg, text=None):
    """「리뷰 기록」 '판정: 확정'의 근거: 최근 유효 라운드가 CONFIRM(blocker 없음)이고, 지적 장부에 열린 blocker가 없고,
    그 라운드가 본 tree 뒤로 코드(기록 파일 제외)가 바뀌지 않았어야 한다. 확정 뒤 코드 변경은 다음 라운드(부분)로,
    3라운드를 썼으면 사람에게(사람 판정 D-nnn — human_review)."""
    human = HUMAN_REVIEW.search(sections(text).get("리뷰 기록", "")) if text is not None else None
    if human:
        return human_review(human.group(1), goal, cfg, text)
    why = round_not_confirmed("r", goal, cfg)
    if why:
        return [f"「리뷰 기록」은 '판정: 확정'인데 리뷰 기록이 뒷받침하지 않음({why}) — review.py --round 1부터(지금 브랜치에서)"]
    rounds = valid_rounds("r", goal, cfg)
    nums = [n for n, _ in rounds]
    if nums != list(range(1, len(nums) + 1)):   # A9-09: 앞 라운드를 지우면 그 지적이 장부에서 사라진다
        return [f"리뷰 유효 기록이 r1부터 이어지지 않음({', '.join(f'r{n}' for n in nums)}) — 빠진 라운드의 지적을 장부가 볼 수 없다. "
                "review.py --round 1부터 다시"]
    bad = [f"r{n}: {p} — 리뷰 재실행" for n, t in rounds for p in resolved_problems(t)]
    if text is not None:
        bad += checked_complete_problems(goal, cfg, text)
    left = ledger(rounds, GATE_SEVS)
    if left:
        bad.append(f"열린 {', '.join(f'{s} {i}(r{n})' for i, (s, n) in sorted(left.items()))} — 뒤 라운드 RESOLVED에 없음"
                   "(major는 CARRY 가능). 고치고 다음 라운드에서 닫거나, 3라운드 뒤면 사람 판정")
    if bad:
        return bad
    n = latest_round("r", goal, cfg)[0]
    rec = os.path.join(REVIEW_DIR, f"r{n}.tree")
    with open(rec, encoding="utf-8") as f:
        seen = f.read().strip().splitlines()[0].strip()
    old_conds = record_fields(rec).get("conds")
    if text is not None and not old_conds:
        return [f"리뷰 기록에 완료 조건 해시 없음(r{n}.tree) — 리뷰 재실행(review.py --round 1)"]
    if text is not None and old_conds != completion_hash(text):
        return [f"리뷰 뒤 완료 조건이 바뀜(r{n}.tree) — 리뷰 재실행(review.py --round 1)"]
    if text is not None and contract_problem(rec, text):
        return [contract_problem(rec, text)]
    try:
        code = changed_since(seen, cfg, record_fields(rec).get("code_tree", ""))
    except RuntimeError:
        return [f"리뷰 기록 tree를 읽을 수 없음(r{n}.tree: {seen[:12]}) — 리뷰 재실행(review.py --round 1)"]
    if not code:
        return []
    shown = ", ".join(code[:3]) + (" …" if len(code) > 3 else "")
    if n >= 3:
        return [f"리뷰 확정 뒤 코드 변경({shown}) — 3라운드를 다 썼으므로 사람 판정 필요"]
    return [f"리뷰 확정 뒤 코드 변경({shown}) — review.py --round {n + 1} (부분, --files {' '.join(code[:5])}) 필요"]


def size_warning(cfg):
    lines, files = diff_size(cfg)
    if lines > cfg.get("max_lines", 400) or files > cfg.get("max_files", 10):
        print(f"[size] 경고: {lines}줄 · {files}파일 — 리뷰가 정확해지려면 MR을 나누는 것을 검토하세요")


def merge_checks(qa, cfg):
    miss = []
    cur = vf_git.snapshot()
    try:   # 대상 sha는 qa_run.target(안내 주석 안의 예시 sha 제외)과 같은 파서로 — 없으면 주석만 지우고 읽는다
        from qa_run import target as qa_target
    except ImportError:
        def qa_target(t):
            m = re.search(r"대상 (?:commit|tree):\s*`?([0-9a-f]{7,40})", re.sub(r"<!--.*?-->", "", t or "", flags=re.S))
            return m.group(1) if m else ""
    sha = qa_target(qa)
    try:
        import qa_run as _qr
    except ImportError:   # 검증기가 없으면 아래에서 막는다(fail closed) — 대상 tree만 직접 푼다
        _qr = None
    if _qr is not None:
        _, qrec, qtree = _qr.find_record(sha) if sha else ("", None, "")
    else:
        qrec, qtree = None, vf_git.tree_of(sha) if sha else ""
    if not sha:
        miss.append("「QA 결과」에 대상 commit/tree 없음")
    elif not qtree:
        miss.append(f"QA 대상 {sha[:10]}을 찾을 수 없음")
    elif qtree != cur and vf_git.obj_type(qtree) == "tree":
        # QA 뒤 핸드오프 기록(WORKLOG·INDEX·REMAINING)과 골 파일만 바뀐 것은 허용 — 기록은 QA 결과를 보고 쓴다
        # 기록 판정은 크기 계산과 같은 is_record — 개인 모드에서 docs/ 아래 코드가 QA 뒤에 바뀌면 재검증
        # 실수로 추적 중인 무시 대상(.pyc 등 캐시)은 테스트를 돌릴 때마다 바뀐다 — 비교에서 빼고 경고만
        code, ignored = code_diff(qtree, cur, cfg)
        if ignored:
            print(f"[mr-check] 경고: 무시 대상(산출물)인데 추적 중인 파일 {len(ignored)}개는 QA 대상 비교에서 뺐다({', '.join(sorted(ignored)[:3])}) — `git rm --cached`로 정리하는 골 후보를 쓰세요")
        if code:
            miss.append(f"QA 대상 {sha[:10]} 이후 바뀐 파일({', '.join(code[:3])}) — 재검증 필요(미커밋 포함)")
    elif qtree != cur:   # QA tree 객체가 없다(재연 — amend 전 tree) — 실행 기록의 code_tree로 같은 비교
        try:
            code = changed_since(qtree, cfg, qrec.get("code_tree", "") if isinstance(qrec, dict) else "")
        except RuntimeError:
            code = ["(QA 기록에 code_tree 없음 — 대조 불가)"]
        if code:
            miss.append(f"QA 대상 {sha[:10]} 이후 바뀐 파일({', '.join(code[:3])}) — 재검증 필요(미커밋 포함)")
    if not re.search(rf"^-\s*코드:\s*{PASS}", qa, re.M):
        miss.append("「QA 결과」 코드 단계가 '통과'가 아님")
    base = vf_git.base_tree(cfg["base"])
    files = vf_git.changed_files(base, cur)
    ui = [f for f in files if vf_git.glob_match(f, cfg["ui_globs"])]
    if ui:
        if not re.search(rf"^-\s*브라우저:\s*{PASS}", qa, re.M):
            miss.append(f"UI 파일 변경({', '.join(ui[:3])}{' …' if len(ui) > 3 else ''}) — 브라우저 단계 '통과' 필요")
        if not re.search(r"!\[|\.png|\.webp|캡처", qa):
            miss.append("브라우저 단계 증거(캡처) 없음")
    elif cfg.get("ui_unclear_needs_reason", True):
        # 글롭은 보조 신호다. 글롭에 안 걸린 코드 변경을 「UI 변경 없음」으로 자동 통과시키지 않는다 — 판단과 이유를 적게 한다
        p = vf_git.paths(cfg)
        keep = (p["handoff"] + "/", p["goals"] + "/")
        code = [f for f in files if not f.startswith(keep) and not f.endswith(".md")]
        b = re.search(r"^-\s*브라우저:\s*(.*)$", qa, re.M)
        val = b.group(1).strip() if b else ""
        if code and not (re.match(PASS, val) or re.search(r"해당 없음\s*[(（—–:-]\s*\S{2,}", val)):
            miss.append(f"UI 판정 불명확 — 바뀐 코드({', '.join(code[:3])})가 ui_globs에 안 걸림. 「QA 결과」 브라우저 줄에 "
                        "'해당 없음 — <화면에 닿지 않는 이유>'를 적거나, 화면에 닿으면 브라우저 QA(통과 + 캡처)")
    if vf_git.obj_type(cfg["base"]) == "commit" and vf_git.git("rev-parse", "--verify", "-q", "HEAD"):
        mb = vf_git.git("merge-base", cfg["base"], "HEAD")
        ns = vf_git.paths(cfg)["northstar"]
        if vf_git.git("diff", "--name-only", mb, cfg["base"], "--", ns, ns[:-3] + "-body.md"):
            miss.append("이 브랜치가 갈라진 뒤 base에서 노스스타가 바뀜 — 골을 다시 judge 받아야 함")
        if vf_git.git("rev-parse", cfg["base"]) != mb:
            miss.append(f"base({cfg['base']})에 이 브랜치에 없는 커밋이 있음 — 리베이스한 뒤 그 위에서 QA를 다시 하세요")
    try:   # QA 실행 증거(qa_run.py가 남긴 기록)와 「QA 결과」 대상 대조 — 검증기가 없으면 통과가 아니다(fail closed)
        import qa_run
    except ImportError:
        qa_run = None
    if qa_run is None or not hasattr(qa_run, "verify"):
        miss.append("QA 검증기(qa_run) 없음 — 설치 확인")
    else:
        miss += qa_run.verify(qa, cfg)
    return miss


# 단계 검사가 처음 실패하는 곳 = 지금 할 일. 그 단계를 맡는 세부 스킬
NEXT_SKILL = {"claim": "vibe-claim", "draft": "vibe-design", "build": "vibe-design", "review": "vibe-dev",
              "qa": "vibe-review", "merge": "vibe-qa"}


def next_stage(text, cfg):
    for st in STAGES:
        miss = check(text, st, cfg)
        if miss:
            return st, NEXT_SKILL[st], miss
    return "record", "vibe-record", []


def record_check():
    """HEAD의 완료 기록 검사(handoff.py check-record). (통과, 빠진 항목 줄)."""
    import subprocess
    r = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "handoff.py"),
                        "check-record"], capture_output=True, text=True, encoding="utf-8")
    out = (r.stdout or "") + (r.stderr or "")
    lines = [x.strip()[2:] for x in out.splitlines() if x.strip().startswith("- ")]
    if r.returncode and not lines:
        lines = [out.strip()[-200:] or "check-record 실패"]
    return r.returncode == 0, lines


CONTRACT = ("골", "사용자 가치", "완료 조건", "제외 범위")


def contract_parts(text, cfg):
    """MR 계약 부분의 정규화(공백·빈 줄·주석 무시, 완료 조건은 체크 상태 무시) — {이름: 해시}."""
    import hashlib
    text = vf_git.normalize_mr(text, cfg)
    s = sections(text)
    norm = {"골": s.get("골", ""), "사용자 가치": s.get("사용자 가치", ""), "제외 범위": s.get("제외 범위", ""),
            "완료 조건": "\n".join(t for _, t in completion_items(text))}
    return {k: hashlib.sha256("\n".join(" ".join(x.split()) for x in norm[k].splitlines() if x.strip())
                              .encode("utf-8")).hexdigest()[:16] for k in CONTRACT}


def mr_copy_problems(text, cfg):
    """H-04: 커밋된 MR 사본(HEAD:<핸드오프>/mr/G-###.md)의 「골」「완료 조건」「제외 범위」가 작업 MR과 같은가."""
    h = vf_git.paths(cfg)["handoff"].rstrip("/")
    miss, cur = [], contract_parts(text, cfg)
    for g in [x for x in mr_goal(text, cfg).split(",") if x and x != "G-000"]:
        p = f"{h}/mr/{g}.md"
        committed = vf_git.git("show", f"HEAD:{p}")
        if not committed:
            miss.append(f"커밋된 MR 사본 {p}가 HEAD에 없음 — 기록 커밋에 작업 MR을 복사해 넣는다")
            continue
        old = contract_parts(committed, cfg)
        diff = [k for k in CONTRACT if old[k] != cur[k]]
        if diff:
            miss.append(f"커밋된 MR 사본 {p}의 {'·'.join(f'「{k}」' for k in diff)}이 작업 MR과 다름 — "
                        "작업 MR을 다시 복사해 기록 커밋을 고친다(계약이 바뀌었으면 리뷰·QA부터)")
    return miss


def main():
    a = sys.argv[1:]
    if len(a) == 2 and a[1] == "--next":
        with open(a[0], encoding="utf-8") as f:
            text = f.read()
        st, skill, miss = next_stage(text, vf_git.config())
        if st == "record":   # merge 통과 — HEAD의 기록(check-record)과 커밋된 MR 사본까지 맞아야 끝
            ok, rec = record_check()
            if ok:
                rec = mr_copy_problems(text, vf_git.config())
                ok = not rec
            if ok:
                print("[mr-check:next] DONE — 머지 준비 완료(머지는 사용자)")
                return
            miss = rec
        print(f"[mr-check:next] 지금 단계: {st} → 세부 스킬 {skill}")
        for x in miss:
            print(" -", x)
        return
    if len(a) != 3 or a[1] != "--stage" or a[2] not in STAGES:
        sys.exit(__doc__)
    with open(a[0], encoding="utf-8") as f:
        miss = check(f.read(), a[2], vf_git.config())
    if miss:
        print(f"[mr-check:{a[2]}] 통과 못 함")
        for x in miss:
            print(" -", x)
        hints = [h for k, h in HINTS if any(k in x for x in miss)]
        if hints:
            print("[mr-check] 다음 행동:")
            for h in dict.fromkeys(hints):
                print("  →", h)
        sys.exit(1)
    print(f"[mr-check:{a[2]}] 통과")


if __name__ == "__main__":
    for st in (sys.stdout, sys.stderr):
        st.reconfigure(encoding="utf-8")
    main()
