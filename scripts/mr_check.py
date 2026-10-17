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
           base가 앞서 갔으면 리베이스 후 QA
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
    return f"goal: {goal}\nbranch: {vf_git.current_branch()}\nbase: {current_base(cfg)}\n"


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
                if not re.search(r"^status:\s*active", f.read(), re.M):
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
                if drounds[-1][0] != 2:
                    miss.append(f"「설계 확인」 사람 판정 {human.group(1)}: 2회차 유효 기록(d2) 없음 — 사람 판정은 설계 확인 2회 뒤에만")
                else:
                    miss += decision_cover(human.group(1), dc, {x["id"]: ("blocker", 2) for x in blockers(drounds[-1][1])},
                                           cfg, "설계 확인")
        if confirmed and not human:
            # MR 문구가 아니라 Codex 출력이 판정이다 — 최근 d<N>.txt가 CONFIRM이고 blocker가 없어야 한다
            why = round_not_confirmed("d", goal, cfg)
            if why:
                miss.append(f"「설계 확인」은 '판정: 확정'인데 설계 확인 기록이 뒷받침하지 않음({why}) — "
                            "review.py --design 1(또는 2)을 지금 브랜치에서 다시")
            else:   # 확인 기록은 그때의 「설계」 문구에 묶인다 — 해시 없는 예전 기록도 stale
                dn = latest_round("d", goal, cfg)[0]
                if record_fields(os.path.join(REVIEW_DIR, f"d{dn}.meta")).get("design") != design_hash(text, cfg):
                    miss.append(f"설계가 확인 뒤 바뀜(d{dn}.meta) — review.py --design 다시(남은 회차 안에서) 또는 사람 판정")
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
        miss += unverified_problems(s.get("QA 결과", ""), gids, cfg)
        if profile(s) != "경량":
            miss += red_evidence(s.get("QA 결과", ""))
        if profile(s) == "강화":
            ids = test_ids(line_value(s.get("QA 결과", ""), "회귀"))
            if not ids:
                miss.append("강화 프로필 — 「QA 결과」에 '- 회귀: <돌린 회귀 테스트 이름>' 줄 필요"
                            "(test_x · Class.test_x · tests/x.py::name)")
            gone = [t for t in ids if not test_exists(t)]
            if gone:
                miss.append(f"강화 프로필 — 「QA 결과」 '- 회귀:'의 {', '.join(gone)}가 레포 테스트 파일에 없음 — 돌린 테스트 이름을 적는다")
            if ids:
                miss += regression_evidence(ids, s.get("QA 결과", ""))
    return miss


TEST_ID = re.compile(r"(?<![\w./\\-])(?:[\w./\\-]+\.py::\w+(?:::\w+)*|(?:[\w.-]+[/\\])*tests?[/\\][\w./\\-]*\.py"
                     r"|(?:[A-Za-z_]\w*\.)*test_\w+)(?![\w./\\-])")


def test_ids(value):
    """'- 코드:'·'- 회귀:' 값의 테스트 식별자(test_x · Class.test_x · path/test_x.py::name · tests/…py)."""
    return TEST_ID.findall(value or "")


def _test_files():
    skip = {".git", ".vibe", "node_modules", ".venv", "venv", "__pycache__"}
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if d not in skip]
        in_tests = re.search(r"(^|[/\\])tests?([/\\]|$)", root)
        for f in files:
            if in_tests or f.startswith("test") or "_test" in f:
                yield os.path.join(root, f)


def test_exists(tid):
    """식별자가 레포 테스트 파일에 있는가 — 경로면 그 파일이 있어야, 이름이면 마지막 성분이 테스트 파일에 나와야 한다."""
    path, _, rest = tid.partition("::")
    if path.endswith(".py") and not os.path.isfile(path):
        return False
    name = rest.split("::")[-1] if rest else ("" if path.endswith(".py") else tid.split(".")[-1])
    if not name:
        return True
    n = re.escape(name)   # 정의만 — 주석·문자열 속 이름은 테스트가 아니다
    pat = re.compile(rf"^\s*(?:async\s+)?def\s+{n}\s*\(|^\s*(?:export\s+)?(?:async\s+)?function\s*\*?\s*{n}\s*\("
                     rf"|\b(?:it|test)(?:\.\w+)?\(\s*([\"'`]){n}\1", re.M)
    for p in ([path] if rest else _test_files()):
        try:
            with open(p, encoding="utf-8", errors="ignore") as f:
                if pat.search(f.read()):
                    return True
        except OSError:
            continue
    return False


def _last(name):
    """테스트 이름의 마지막 성분 — 'a.B.test_x' · 'p.py::test_x' · 'test_x (a.B.test_x)' → test_x."""
    parts = [x for x in re.split(r"::|[.\s()]+", name) if x]
    return parts[-1] if parts else ""


def _qual(name):
    """비교용 한정 이름 — 'test_x (a.B.test_x)'는 괄호 안, 경로 구분자·'::'는 '.', '.py'는 뺀다."""
    m = re.fullmatch(r"\s*\S+\s*\(([^()]+)\)\s*", name)
    n = (m.group(1) if m else name).strip()
    return re.sub(r"\.py(?=\.|$)", "", re.sub(r"::|[/\\]", ".", n))


def test_match(rid, recorded):
    """'- 회귀:' 식별자와 기록 이름 — 맨 이름(test_x)은 마지막 성분, 한정형(B.test_x · p.py::test_x)은 끝이 그 한정형."""
    q = _qual(rid)
    if "." not in q:
        return _last(recorded) == q
    r = _qual(recorded)
    return r == q or r.endswith("." + q)


UNVERIFIED_MSG = "미검증 항목이 남음 — 검증하거나 사람 승인(D-nnn)"


def unverified_problems(qa, gids, cfg):
    """merge: 「QA 결과」 '- 미검증·생략 항목과 사유:'는 필수 — 값이 정확히 '없음'이거나,
    항목마다 '- 사람 승인: D-nnn — <항목>'(D-nnn은 DECISIONS에 있고 이 골 ID를 적음)."""
    qa = re.sub(r"<!--.*?-->", "", qa or "", flags=re.S)
    m = re.search(r"^\s*[-*]?\s*미검증·생략 항목과 사유\s*:(.*)$", qa, re.M)
    if not m:
        return [f"「QA 결과」에 '- 미검증·생략 항목과 사유:' 줄 없음(없으면 '없음') — {UNVERIFIED_MSG}"]
    val = m.group(1).strip()
    if val == "없음":
        return []
    ok = []
    for did, item in re.findall(r"^\s*[-*]?\s*사람 승인\s*:\s*(D-\d+)\s*[—–:-]+\s*(\S.*?)\s*$", qa, re.M):
        if not decision_problem(did, gids, cfg):
            ok.append(item)
    items = [x.strip() for x in re.split(r"[,;，、]", val) if x.strip()]
    left = [x for x in items if not any(a in x or x in a for a in ok)]
    return [f"{UNVERIFIED_MSG} — {', '.join(left[:3])}"] if left or not items else []


def _qa_record(qa):
    """「QA 결과」 대상의 QA 기록(.vibe/qa/<tree>.json) dict. 없으면 None."""
    import json
    try:
        from qa_run import target as qa_target
    except ImportError:
        def qa_target(t):
            m = re.search(r"대상 (?:commit|tree):\s*`?([0-9a-f]{7,40})", re.sub(r"<!--.*?-->", "", t or "", flags=re.S))
            return m.group(1) if m else ""
    sha = qa_target(qa)
    tree = vf_git.tree_of(sha) if sha else ""
    if not tree:
        return None
    try:
        with open(os.path.join(".vibe", "qa", f"{tree}.json"), encoding="utf-8") as f:
            rec = json.load(f)
        return rec if isinstance(rec, dict) else None
    except (OSError, ValueError):
        return None


def red_evidence(qa):
    """표준·강화 merge: 이 브랜치의 RED 기록(.vibe/qa/red-<tree>.json, exit≠0)에서 실패한 테스트 하나 이상이
    QA 기록 tests에서 ok(RED→GREEN). QA 기록에 tests가 없으면 exit≠0인 RED 기록만."""
    import glob
    import json
    cur = vf_git.current_branch()
    rec = _qa_record(qa) or {}
    green = rec.get("tests") if isinstance(rec.get("tests"), dict) else None
    for p in sorted(glob.glob(os.path.join(".vibe", "qa", "red-*.json"))):
        try:
            with open(p, encoding="utf-8") as f:
                red = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(red, dict) or red.get("branch") != cur or red.get("exit") in (0, None):
            continue
        if green is None:
            return []
        failed = [k for k, v in (red.get("tests") or {}).items() if v not in ("ok", "skip", "skipped")] if isinstance(red.get("tests"), dict) else []
        if any(green.get(k) == "ok" for k in failed):
            return []
    return ["RED 증거 없음 — 구현 전 qa_run.py --red (표준·강화: 이 브랜치에서 실패한 테스트가 QA 기록에서 ok여야 함)"]


def regression_evidence(ids, qa):
    """강화 merge: '- 회귀:' 식별자마다 QA 기록(.vibe/qa/<tree>.json) 'tests'에 같은 이름(test_match)이 있고 모두 ok."""
    import json
    try:
        from qa_run import target as qa_target
    except ImportError:
        def qa_target(t):
            m = re.search(r"대상 (?:commit|tree):\s*`?([0-9a-f]{7,40})", re.sub(r"<!--.*?-->", "", t or "", flags=re.S))
            return m.group(1) if m else ""
    sha = qa_target(qa)
    tree = vf_git.tree_of(sha) if sha else ""
    tests = None
    if tree:
        try:
            with open(os.path.join(".vibe", "qa", f"{tree}.json"), encoding="utf-8") as f:
                tests = json.load(f).get("tests")
        except (OSError, ValueError, AttributeError):
            tests = None
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
    if not rounds or rounds[-1][0] != 3:
        miss.append(f"「리뷰 기록」 사람 판정 {did}: 3라운드 유효 기록(r3) 없음 — 사람 판정은 3라운드 뒤에만(그 전엔 다음 라운드)")
    why = decision_problem(did, re.findall(r"\bG-\d{3,}\b", goal), cfg)
    if why:
        miss.append(f"「리뷰 기록」 사람 판정 {did}: {why} — 결정을 D-nnn으로 기록하고 이 골 ID를 적는다")
    miss += [f"r{n}: {p} — 리뷰 재실행" for n, t in rounds for p in resolved_problems(t)]
    miss += decision_cover(did, sections(text).get("리뷰 기록", ""), ledger(rounds, GATE_SEVS), cfg, "리뷰 기록")
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
        code, _ = code_diff(r3, vf_git.snapshot(), cfg)
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
    bad = [f"r{n}: {p} — 리뷰 재실행" for n, t in rounds for p in resolved_problems(t)]
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
    unread = [f"리뷰 기록 tree를 읽을 수 없음(r{n}.tree: {seen[:12]}) — 리뷰 재실행(review.py --round 1)"]
    if not re.fullmatch(r"[0-9a-f]{7,40}", seen) or vf_git.obj_type(seen) != "tree":
        return unread
    try:
        code, _ = code_diff(seen, vf_git.snapshot(), cfg)
    except RuntimeError:
        return unread
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
    if not sha:
        miss.append("「QA 결과」에 대상 commit/tree 없음")
    elif not vf_git.tree_of(sha):
        miss.append(f"QA 대상 {sha[:10]}을 찾을 수 없음")
    elif vf_git.tree_of(sha) != cur:
        # QA 뒤 핸드오프 기록(WORKLOG·INDEX·REMAINING)과 골 파일만 바뀐 것은 허용 — 기록은 QA 결과를 보고 쓴다
        # 기록 판정은 크기 계산과 같은 is_record — 개인 모드에서 docs/ 아래 코드가 QA 뒤에 바뀌면 재검증
        # 실수로 추적 중인 무시 대상(.pyc 등 캐시)은 테스트를 돌릴 때마다 바뀐다 — 비교에서 빼고 경고만
        code, ignored = code_diff(vf_git.tree_of(sha), cur, cfg)
        if ignored:
            print(f"[mr-check] 경고: 무시 대상(산출물)인데 추적 중인 파일 {len(ignored)}개는 QA 대상 비교에서 뺐다({', '.join(sorted(ignored)[:3])}) — `git rm --cached`로 정리하는 골 후보를 쓰세요")
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
