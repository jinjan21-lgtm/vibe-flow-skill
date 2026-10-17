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
           유효 = 기록(d<N>.meta·r<N>.tree)의 골·브랜치·기준 tree가 지금과 같음
  qa     : + 「리뷰 기록」에 "판정: 확정", 라운드 3회 이하. 최근 유효 r<N>.txt가 CONFIRM·blocker 0이고,
           그 r<N>.tree 뒤로 코드(기록 파일·.vibe/ 제외)가 안 바뀌었어야 함(바뀌면 --round N+1, 3이면 사람). merge도 같다
  merge  : + 「완료 조건」 항목이 모두 '- [x]'(체크박스 없는 항목도 미체크).
           「QA 결과」의 대상(commit 또는 tree)이 지금 작업물(미커밋 포함)과 같고 코드 통과.
           UI 파일이 바뀌었으면 브라우저 통과 + 캡처. 노스스타가 기준 이후 바뀌었으면 골 재판정 필요.
           base가 앞서 갔으면 리베이스 후 QA

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
RECORD_NAME = re.compile(r"(?:PLAN(?:-[\w-]+)?|WORKLOG|REMAINING(?:-done-\d{4}-\d{2})?|LESSONS(?:-body(?:-\d+)?)?"
                         r"|DECISIONS(?:-\d{4}-\d{2}(?:-\d+)?|-INDEX-replaced)?|NORTHSTAR(?:-body)?|INDEX)\.md")
QA_RECORD = re.compile(r"G-\d{3,}-qa\.json")   # <핸드오프>/mr/G-###-qa.json: qa_run.py 실행 기록 사본(기록 커밋에 넣는다)


def is_record(f, cfg):
    """핸드오프 기록 파일만: 골 폴더, <핸드오프>/mr/, <핸드오프>/WORKLOG/ 토픽, 핸드오프 폴더 바로 아래 RECORD_NAME.
    코드 위험이 아니므로 크기·구현 여부·QA/리뷰 뒤 변경에서 뺀다.
    개인 모드는 핸드오프가 docs/라 폴더로만 가리면 docs/ 아래 코드까지 빠진다 — .md가 아니면 기록이 아니다."""
    p = vf_git.paths(cfg)
    h, goals = p["handoff"].rstrip("/"), p["goals"].rstrip("/")
    d, _, name = f.rpartition("/")
    if d == h + "/mr" and QA_RECORD.fullmatch(name):
        return True
    if not f.endswith(".md"):
        return False
    if f.startswith((goals + "/", h + "/mr/", h + "/WORKLOG/")) or f in (p["northstar"], p["northstar"][:-3] + "-body.md"):
        return True
    return d == h and bool(RECORD_NAME.fullmatch(name))


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


def code_diff(old, cur, cfg):
    """두 tree 사이 바뀐 코드 — 기록 파일(is_record)과 .vibe/(로컬 작업 상태)를 빼고,
    실수로 추적 중인 무시 대상(.pyc 등, 테스트마다 바뀜)도 뺀다. (코드 목록, 뺀 무시 대상)."""
    code = [f for f in vf_git.changed_files(old, cur) if not is_record(f, cfg) and not f.startswith(".vibe/")]
    ignored = set(vf_git.git_input(["check-ignore", "--no-index", "--stdin"], "\n".join(code)).splitlines()) if code else set()
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
        miss += design_items_missing(s.get("설계", ""))
    if i >= 2:
        dc = s.get("설계 확인", "")
        confirmed = re.search(r"판정:\s*확정", dc)
        skipped = re.search(r"생략:\s*작은 변경", dc)
        if not (confirmed or skipped):
            miss.append("「설계 확인」에 '판정: 확정'(또는 '생략: 작은 변경') 없음 — review.py --design 먼저")
        human = re.search(r"판정:\s*확정\s*[(（]\s*사람 판정\s*D-\d+", dc)
        if confirmed and not human:
            # MR 문구가 아니라 Codex 출력이 판정이다 — 최근 d<N>.txt가 CONFIRM이고 blocker가 없어야 한다
            why = round_not_confirmed("d", goal, cfg)
            if why:
                miss.append(f"「설계 확인」은 '판정: 확정'인데 설계 확인 기록이 뒷받침하지 않음({why}) — "
                            "review.py --design 1(또는 2)을 지금 브랜치에서 다시")
        if len(re.findall(r"^-\s*확인\s*\d", dc, re.M)) > 2:
            miss.append("설계 확인이 2회를 넘음 — 사람 판정 필요")
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
    if i >= 4:
        rv = s.get("리뷰 기록", "")
        if not re.search(r"판정:\s*확정", rv):
            miss.append("「리뷰 기록」에 '판정: 확정' 없음")
        if len(re.findall(r"^-\s*라운드\s*\d", rv, re.M)) > 3:
            miss.append("리뷰 라운드가 3회를 넘음 — 사람 판정 필요")
        if re.search(r"판정:\s*확정", rv):
            miss += review_evidence(goal, cfg)
    if stage == "merge":
        n = unchecked_conditions(text)
        if n:
            miss.append(f"완료 조건 미체크 {n}개 — 「완료 조건」 항목은 모두 '- [x]'여야 함('- [ ]'·체크박스 없는 항목)")
        miss += merge_checks(s.get("QA 결과", ""), cfg)
    return miss


def review_evidence(goal, cfg):
    """「리뷰 기록」 '판정: 확정'의 근거: 최근 유효 라운드가 CONFIRM(blocker 없음)이고, 그 라운드가 본 tree 뒤로
    코드(기록 파일 제외)가 바뀌지 않았어야 한다. 확정 뒤 코드 변경은 다음 라운드(부분)로, 3라운드를 썼으면 사람에게."""
    why = round_not_confirmed("r", goal, cfg)
    if why:
        return [f"「리뷰 기록」은 '판정: 확정'인데 리뷰 기록이 뒷받침하지 않음({why}) — review.py --round 1부터(지금 브랜치에서)"]
    n = latest_round("r", goal, cfg)[0]
    with open(os.path.join(REVIEW_DIR, f"r{n}.tree"), encoding="utf-8") as f:
        seen = f.read().strip().splitlines()[0].strip()
    code, _ = code_diff(seen, vf_git.snapshot(), cfg)
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
    m = re.search(r"대상 (?:commit|tree):\s*`?([0-9a-f]{7,40})", qa)
    if not m:
        miss.append("「QA 결과」에 대상 commit/tree 없음")
    elif not vf_git.tree_of(m.group(1)):
        miss.append(f"QA 대상 {m.group(1)[:10]}을 찾을 수 없음")
    elif vf_git.tree_of(m.group(1)) != cur:
        # QA 뒤 핸드오프 기록(WORKLOG·INDEX·REMAINING)과 골 파일만 바뀐 것은 허용 — 기록은 QA 결과를 보고 쓴다
        # 기록 판정은 크기 계산과 같은 is_record — 개인 모드에서 docs/ 아래 코드가 QA 뒤에 바뀌면 재검증
        # 실수로 추적 중인 무시 대상(.pyc 등 캐시)은 테스트를 돌릴 때마다 바뀐다 — 비교에서 빼고 경고만
        code, ignored = code_diff(vf_git.tree_of(m.group(1)), cur, cfg)
        if ignored:
            print(f"[mr-check] 경고: 무시 대상인데 추적 중인 파일 {len(ignored)}개는 QA 대상 비교에서 뺐다({', '.join(sorted(ignored)[:3])}) — `git rm --cached`로 정리하는 골 후보를 쓰세요")
        if code:
            miss.append(f"QA 대상 {m.group(1)[:10]} 이후 바뀐 파일({', '.join(code[:3])}) — 재검증 필요(미커밋 포함)")
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
    try:   # QA 실행 증거(qa_run.py가 남긴 기록)와 「QA 결과」 대상 대조 — 모듈이 없는 설치에서는 건너뛴다
        import qa_run
    except ImportError:
        qa_run = None
    if qa_run is not None and hasattr(qa_run, "verify"):
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


def main():
    a = sys.argv[1:]
    if len(a) == 2 and a[1] == "--next":
        with open(a[0], encoding="utf-8") as f:
            st, skill, miss = next_stage(f.read(), vf_git.config())
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
