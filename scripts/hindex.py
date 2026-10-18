"""핸드오프 인덱스 구조 (docs/structure.md 「인덱스 계층」). handoff.py가 부른다.

진입 인덱스(INDEX.md) → 문서별 INDEX → 본문. 본문 텍스트는 이동만 하고 고치지 않는다.
"""
import collections
import datetime
import glob
import hashlib
import json
import os
import re
import shutil
import time
from urllib.parse import unquote

import vf_git

MARK_RE = re.compile(r"<!--\s*vibe-index:\s*([\w-]+)\s*-->")
DEFAULTS = {"start_budget": 12000, "decisions_per_file": 50, "body_max_chars": 20000,
            "topic_max_chars": 30000, "worklog_index_lines": 30, "decisions_index_lines": 200,
            "remaining_active_lines": 80, "id_reserve": "remote"}
SCREEN_RE = re.compile(r"\b[A-Z]{2,4}-\d{2}\b")
DEC_HEAD_RE = re.compile(r"^## (D-\d{3,})\b ?(.*)$", re.M)
DONE_RE = re.compile(r"^(\s*)-\s*\[x\]", re.I)
OPEN_RE = re.compile(r"^\s*-\s*\[[ ~]\]")
DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-\d{2}\b")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
TODAY = datetime.date.today()


def icfg(cfg):
    d = dict(DEFAULTS)
    d.update((cfg or {}).get("index", {}))
    return d


# ---------- 파일: 바이트 그대로 ----------
def rd(p):
    with open(p, "rb") as f:
        return f.read().decode("utf-8")


def wr(p, text):
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "wb") as f:
        f.write(text.encode("utf-8"))


def sha(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def lines_keep(text):
    """줄바꿈을 붙인 채로 나눈다 — 다시 붙이면 원문과 바이트가 같다."""
    return text.splitlines(keepends=True)


def marker(name):
    return f"<!-- vibe-index: {name} -->\n"


def index_kind(path):
    if not os.path.exists(path):
        return None
    head = rd(path)[:300]
    m = MARK_RE.search(head)
    return m.group(1) if m else None


# ---------- 앵커·링크 ----------
def slug(heading):
    """GitHub 방식 앵커: 소문자, 글자·숫자·_·-·공백만 남기고 공백은 -."""
    s = heading.strip().lower()
    s = re.sub(r"[^\w\- ]", "", s)
    return s.replace(" ", "-")


def anchors_of(text):
    out, seen = set(), {}
    for m in re.finditer(r"^#{1,6} (.+?)\s*$", text, re.M):
        h = re.sub(r"\{#[^}]+\}", "", m.group(1)).strip()
        s = slug(h)
        n = seen.get(s, 0)
        seen[s] = n + 1
        out.add(s if n == 0 else f"{s}-{n}")
    out |= set(re.findall(r"\{#([^}\s]+)\}", text))
    out |= set(re.findall(r"<a\s+(?:id|name)=\"([^\"]+)\"", text))
    return out


def links_of(text):
    # 코드 블록·인라인 코드 안의 예시 링크는 뺀다
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`[^`\n]*`", "", text)
    for m in LINK_RE.finditer(text):
        t = m.group(1)
        if re.match(r"^(https?:|mailto:|#)", t) or "<" in t:
            continue
        if not re.search(r"[./]", t.partition("#")[0]):   # `inv["discount"](합계)` 같은 문장 — 경로가 아니다
            continue
        yield t


# ---------- 위치 ----------
def layout(cfg):
    p = vf_git.paths(cfg)
    h = p["handoff"]
    return {"hdir": h, "entry": f"{h}/INDEX.md", "plan": f"{h}/PLAN.md", "remaining": f"{h}/REMAINING.md",
            "decisions": f"{h}/DECISIONS.md", "lessons": f"{h}/LESSONS.md", "northstar": p["northstar"],
            "goals": p["goals"], "goals_index": f"{p['goals']}/INDEX.md", "worklog": f"{h}/WORKLOG",
            "worklog_index": f"{h}/WORKLOG/INDEX.md"}


def is_indexed(cfg):
    return index_kind(layout(cfg)["entry"]) == "ENTRY"


def start_set(cfg):
    L = layout(cfg)
    return [x for x in (L["entry"], L["remaining"], L["goals_index"], L["worklog_index"], L["lessons"],
                        L["northstar"], L["plan"]) if os.path.exists(x)]


def chars(paths):
    return sum(len(rd(p)) for p in paths if os.path.exists(p))


BODY_RE = re.compile(r"DECISIONS-(\d{4}-\d{2})(?:-(\d+))?\.md$")


def body_key(p):
    """DECISIONS-YYYY-MM.md(1부) · DECISIONS-YYYY-MM-2.md(2부) … 를 (달, 부) 순으로."""
    m = BODY_RE.search(p.replace("\\", "/"))
    return (m.group(1), int(m.group(2) or 1)) if m else ("", 0)


def body_name(hdir, month, part):
    return f"{hdir}/DECISIONS-{month}.md" if part == 1 else f"{hdir}/DECISIONS-{month}-{part}.md"


def decision_bodies(L):
    """결정 본문 파일 — 결정 날짜의 달마다 한 파일, 넘치면 같은 달 -2, -3 (논의 F15)."""
    return sorted((p.replace("\\", "/") for p in glob.glob(f"{L['hdir']}/DECISIONS-[0-9]*.md") if BODY_RE.search(p)),
                  key=body_key)


ARCHIVED_TOPIC_RE = re.compile(r"^(.+)-\d{4}-\d{2}(?:-\d+)?\.md$")


def topic_files(L, archived_too=False):
    """활성 토픽 파일(archive·크기 경고용). archive_topic이 만든 보관 파일(<topic>-YYYY-MM[-n].md, <topic>.md가 있을 때)은 뺀다.
    archived_too=True면 보관 파일도 — lint의 INDEX 대조·링크 무결성은 보관 파일까지 본다."""
    def archived(p):
        m = ARCHIVED_TOPIC_RE.match(os.path.basename(p))
        return bool(m) and os.path.exists(os.path.join(os.path.dirname(p), m.group(1) + ".md"))
    return sorted(p.replace("\\", "/") for p in glob.glob(f"{L['worklog']}/*.md")
                  if not os.path.basename(p).startswith("INDEX") and (archived_too or not archived(p)))


def goal_files(L):
    return sorted(p.replace("\\", "/") for p in glob.glob(f"{L['goals']}/G-*.md"))


def field(text, name):
    m = re.search(rf"^{name}:\s*(.+)$", text, re.M)
    return m.group(1).strip() if m else ""


# ---------- INDEX 줄 만들기 ----------
def decision_blocks(text):
    """[(D-nnn, 제목, 블록 텍스트)]"""
    heads = list(DEC_HEAD_RE.finditer(text))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        out.append((m.group(1), m.group(2).strip(), text[m.start():end]))
    return out


def decision_month(block):
    """결정 블록의 「날짜」 줄의 달. 없으면 블록 안 첫 날짜, 그것도 없으면 이번 달."""
    m = re.search(r"날짜 (\d{4})-(\d{2})-\d{2}", block) or DATE_RE.search(block)
    return f"{m.group(1)}-{m.group(2)}" if m else TODAY.strftime("%Y-%m")


def decision_line(did, title, block, body_file):
    date = (re.search(r"날짜 (\d{4}-\d{2}-\d{2})", block) or re.search(r"(\d{4}-\d{2}-\d{2})", block))
    who = re.search(r"결정자 @([\w.-]+)", block)
    st = re.search(r"상태 (유효|대체됨\s*→\s*D-\d{3,})", block)
    status = re.sub(r"\s+", "", st.group(1)) if st else "유효"
    repl = sorted(set(re.findall(r"\b(D-\d{3,}) 대체", block)) - {did})
    tags, seen = [], set()
    # 화면 ID + 「영향」 줄의 코드 이름(`core.js`, `calc.util`) — 모듈 단위 작업(리팩터링·테스트 보강)도 태그로 찾게
    impact = " ".join(l for l in block.splitlines() if l.startswith("- 영향"))
    code = [c for c in re.findall(r"`([\w.\-/]+)`", impact) if len(c) <= 30]
    for t in SCREEN_RE.findall(block) + code:
        if t not in seen and not t.startswith("D-"):
            seen.add(t)
            tags.append(t)
    head_text = block.splitlines()[0][3:]
    parts = [did, title[:70], date.group(1) if date else "", f"@{who.group(1)}" if who else "", status]
    if repl:
        parts.append("대체 " + "·".join(repl))
    tag = " ".join(f"#{t}" for t in tags[:8])
    return (f"- {' · '.join(p for p in parts if p)}" + (f" · {tag}" if tag else "")
            + f" → [본문]({os.path.basename(body_file)}#{slug(head_text)})\n")


def section_lines(body_text, body_name):
    out = []
    for m in re.finditer(r"^## (.+?)\s*$", body_text, re.M):
        rest = body_text[m.end():].lstrip("\n").splitlines()
        first = next((x.strip() for x in rest if x.strip() and not x.startswith(("#", "|", "<!--"))), "")
        first = re.sub(r"\s+", " ", re.sub(r"\*\*|`", "", first).lstrip("-> *"))[:70]
        out.append(f"- [{m.group(1)}]({body_name}#{slug(m.group(1))})" + (f" — {first}" if first else "") + "\n")
    return out


def lesson_lines(body_text, body_name, start=1):
    out, n = [], start
    for l in body_text.splitlines():
        if not l.startswith("- "):
            continue
        lid = re.search(r"\bL-\d{3,}\b", l)
        cnt = re.search(r"\((\d+)회\)", l)
        txt = re.sub(r"\*\*|`", "", l[2:])
        txt = re.sub(r"\s+", " ", txt).strip()[:70]
        key = lid.group(0) if lid else f"L-{n:03d}"
        out.append(f"- {key} {txt}" + (f" ({cnt.group(1)}회)" if cnt else "") + f" → [본문]({body_name})\n")
        n += 1
    return out


def goal_line(path):
    t = rd(path)
    gid = re.match(r"(G-\d{3,})", os.path.basename(path)).group(1)
    title = t.splitlines()[0].lstrip("# ").strip() if t else gid
    title = title[len(gid):].strip() if title.startswith(gid) else title
    return f"- {gid} {title} · {field(t, 'status') or '?'} → [{os.path.basename(path)}]({os.path.basename(path)})\n"


# ---------- 블록 이동(REMAINING·WORKLOG INDEX) ----------
def done_blocks(lines):
    """[x] 줄과 그보다 깊게 들여쓴 하위 줄을 한 블록으로. 하위에 미완료가 있으면 옮기지 않는다.
    반환: [(시작, 끝, 소제목들)]"""
    out, heads, i = [], [], 0
    while i < len(lines):
        l = lines[i]
        hm = re.match(r"^(#{1,6}) ", l)
        if hm:
            lvl = len(hm.group(1))
            heads = [h for h in heads if len(re.match(r"^#+", h).group(0)) < lvl] + [l]
            i += 1
            continue
        m = DONE_RE.match(l)
        if m:
            ind = len(m.group(1).expandtabs())
            j = i + 1
            while j < len(lines) and lines[j].strip() and len(lines[j]) - len(lines[j].lstrip()) > ind:
                j += 1
            if not any(OPEN_RE.match(x) for x in lines[i + 1:j]):
                out.append((i, j, list(heads)))
            i = j
            continue
        i += 1
    return out


def block_month(text):
    ds = DATE_RE.findall(text)
    return f"{ds[-1][0]}-{ds[-1][1]}" if ds else TODAY.strftime("%Y-%m")


def append_with_context(path, title, groups):
    """groups: [(소제목들, 줄들)]. 소제목이 바뀔 때만 원래 소제목 줄을 그대로 복사해 적는다."""
    text = rd(path) if os.path.exists(path) else title
    last = None
    for heads, ls in groups:
        h = heads[-1] if heads else None
        if h and h != last and not text.rstrip("\n").endswith(h.rstrip("\n")):
            text = text.rstrip("\n") + "\n\n" + h if text.strip() else h
            if not text.endswith("\n"):
                text += "\n"
        last = h
        if not text.endswith("\n"):
            text += "\n"
        text += "".join(x if x.endswith("\n") else x + "\n" for x in ls)
    wr(path, text)


def split_decisions(t, h, ic):
    """DECISIONS.md 원문 → ([(본문 파일, 텍스트)], {달: [INDEX 줄]}). 이어 붙이면 원문과 바이트가 같다."""
    blocks = decision_blocks(t)
    first = DEC_HEAD_RE.search(t)
    header = t[:first.start()] if first else t
    per, cap = ic["decisions_per_file"], ic["body_max_chars"]
    out, idx_lines, parts = [], {}, {}
    cur, cur_text, cur_n = None, header, 0
    for did, title, blk in blocks:
        mon = decision_month(blk)
        if cur is None or mon != cur[0] or cur_n >= per or (cur_n and len(cur_text) + len(blk) > cap):
            if cur is not None:
                out.append((cur[1], cur_text))
                cur_text = ""
            parts[mon] = parts.get(mon, 0) + 1
            cur, cur_n = (mon, body_name(h, mon, parts[mon])), 0
        cur_text += blk
        cur_n += 1
        idx_lines.setdefault(mon, []).append(decision_line(did, title, blk, cur[1]))
    if cur is not None:
        out.append((cur[1], cur_text))
    elif header:  # 결정이 없어도 머리말(제목·정책)은 본문 파일로 옮긴다
        out.append((body_name(h, TODAY.strftime("%Y-%m"), 1), header))
    return out, idx_lines


def migrate_targets(L, ic):
    """migrate가 새로 만들 파일(덮어쓰거나 이어 쓰면 원본이 사라지거나 섞인다)."""
    h, out = L["hdir"], []
    if os.path.exists(L["decisions"]):
        out += [n for n, _ in split_decisions(rd(L["decisions"]), h, ic)[0]]
    out += [L[k][:-3] + "-body.md" for k in ("plan", "northstar", "lessons") if os.path.exists(L[k])]
    if os.path.exists(L["remaining"]):
        ls = lines_keep(rd(L["remaining"]))
        out += sorted({f"{h}/REMAINING-done-{block_month(''.join(ls[s:e]))}.md" for s, e, _ in done_blocks(ls)})
    if os.path.exists(L["worklog_index"]):
        ls = lines_keep(rd(L["worklog_index"]))
        items = [i for i, l in enumerate(ls) if re.match(r"^- \d{4}-\d{2}-\d{2}", l)]
        cur = TODAY.strftime("%Y-%m")
        move = set(items[ic["worklog_index_lines"]:]) | {i for i in items if ls[i][2:9] < cur}
        out += sorted({f"{L['worklog']}/INDEX-{ls[i][2:9]}.md" for i in move})
    if os.path.isdir(L["goals"]):
        out += [L["goals_index"], f"{L['goals']}/INDEX-done.md"]
    out.append(L["entry"])
    return out


# ---------- migrate ----------
def migrate(cfg):
    L = layout(cfg)
    ic = icfg(cfg)
    if is_indexed(cfg):
        raise SystemExit(f"[migrate] 이미 인덱스 구조입니다 ({L['entry']})")
    clash = [p for p in migrate_targets(L, ic) if os.path.exists(p)]
    if clash:  # 하나라도 겹치면 아무것도 바꾸지 않는다(스냅숏도 만들지 않음)
        raise SystemExit("[migrate] 중단 — 만들 파일이 이미 있음(덮어쓰면 원본이 사라진다). 옮기거나 이름을 바꾼 뒤 다시:\n  "
                         + "\n  ".join(clash))
    ts = time.strftime("%Y%m%d-%H%M%S")
    snap = f".vibe/migrate/{ts}"
    manifest = {"hdir": L["hdir"], "files": {}, "line_moves": {}, "added": {}, "moves": {}}
    for p in glob.glob(f"{L['hdir']}/**/*.md", recursive=True):
        p = p.replace("\\", "/")
        dst = f"{snap}/{p}"
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(p, dst)
        manifest["files"][p] = sha(p)
    h = L["hdir"]
    made = []

    # DECISIONS: 결정 날짜의 달마다 본문 파일(논의 F15). 한 달이 50건·20,000자를 넘으면 같은 달 -2, -3.
    # 원래 순서대로 이어 가며 나누므로, 만든 순서대로 이어 붙이면 원문(머리말 포함)과 바이트가 같다.
    if os.path.exists(L["decisions"]):
        t = rd(L["decisions"])
        parts_txt, idx_lines = split_decisions(t, h, ic)
        bodies = [n for n, _ in parts_txt]
        for n, txt in parts_txt:
            wr(n, txt)
        manifest["moves"][L["decisions"]] = bodies
        out = marker("DECISIONS") + "# 결정 INDEX\n\n"
        out += ("> 한 줄 = 결정 하나. 본문은 링크로 연다. **새 결정**: `handoff.py next-id D`로 번호를 받고, 안내된 본문 파일 끝에 "
                "`## D-nnn 제목` 블록을 붙이고, 같은 커밋에 이 INDEX 끝에 한 줄을 붙인다(줄은 고치지 않고 추가만). "
                "뒤집을 때는 새 결정 줄에 `대체 D-kkk`를 적는다 — 그 결정은 그때부터 대체됨. "
                "`#태그`는 화면·모듈 ID다. 지금 작업이 닿는 태그의 줄만 연다(`grep \"#HOME-01\" DECISIONS.md`).\n>\n"
                "> 본문: " + " · ".join(f"[{os.path.basename(b)}]({os.path.basename(b)})" for b in bodies) + "\n")
        for mon in sorted(idx_lines):
            out += f"\n## {mon}\n" + "".join(idx_lines[mon])
        wr(L["decisions"], out)
        made.append(L["decisions"])

    # PLAN · NORTHSTAR · LESSONS: 본문 파일로 통째 이동 + INDEX
    for key, kind, title in (("plan", "PLAN", "# PLAN INDEX"), ("northstar", "NORTHSTAR", "# 노스스타 INDEX"),
                             ("lessons", "LESSONS", "# 교훈 INDEX")):
        p = L[key]
        if not os.path.exists(p):
            continue
        t = rd(p)
        body = p[:-3] + "-body.md"
        wr(body, t)
        manifest["moves"][p] = [body]
        bn = os.path.basename(body)
        rows = lesson_lines(t, bn) if kind == "LESSONS" else section_lines(t, bn)
        intro = {"PLAN": "> 기획 요약의 목차. 본문: [{b}]({b}). 기획을 바꾸면 본문의 변경 이력에 적고, 새 `##` 섹션이면 여기도 한 줄.\n",
                 "NORTHSTAR": "> 노스스타 본문: [{b}]({b}) — 상태(draft·confirmed) 주석은 본문 첫머리에 있다. 골 판정 전에는 본문 전체를 읽는다.\n",
                 "LESSONS": "> 한 줄 = 교훈 하나. 본문: [{b}]({b}). 새 교훈은 본문 끝에 `- … (L-nnn, @작성자, 날짜)`로, 같은 커밋에 여기 한 줄(`handoff.py next-id L`). 2회 이상 반복된 교훈은 **굵게**. 지우지 않는다 — 절차에 반영되면 줄 끝에 `· 반영: <문서>`.\n"}[kind]
        wr(p, marker(kind) + title + "\n\n" + intro.format(b=bn) + "\n" + "".join(rows))
        made.append(p)

    # REMAINING: [x] 블록을 완료 월 파일로
    if os.path.exists(L["remaining"]):
        t = rd(L["remaining"])
        ls = lines_keep(t)
        blocks = done_blocks(ls)
        moved_idx, to = set(), {}
        groups = {}
        for s, e, heads in blocks:
            mon = block_month("".join(ls[s:e]))
            name = f"{h}/REMAINING-done-{mon}.md"
            to.setdefault(name, []).extend(range(s, e))
            groups.setdefault(name, []).append((heads, ls[s:e]))
            moved_idx.update(range(s, e))
        for name, gs in groups.items():
            append_with_context(name, f"# 완료한 일 — {name[-10:-3]}\n\n> REMAINING.md에서 옮긴 완료 항목(원문 그대로). 원래 소제목을 함께 적었다.\n", gs)
        kept = [i for i in range(len(ls)) if i not in moved_idx]
        add_top = marker("REMAINING")
        add_ptr = ("> 완료 항목은 " + " · ".join(f"[{os.path.basename(n)}]({os.path.basename(n)})" for n in sorted(groups))
                   + "로 옮겼다(`handoff.py archive`).\n") if groups else ""
        body = [ls[i] for i in kept]
        # 제목 줄 바로 뒤에 안내 한 줄
        if add_ptr and body and body[0].startswith("# "):
            body = [body[0], add_ptr] + body[1:]
        elif add_ptr:
            body = [add_ptr] + body
        wr(L["remaining"], add_top + "".join(body))
        manifest["line_moves"][L["remaining"]] = {"kept": kept, "to": to}
        manifest["added"][L["remaining"]] = [add_top] + ([add_ptr] if add_ptr else [])
        made.append(L["remaining"])

    # WORKLOG INDEX: 최근 N줄만 남기고 나머지는 그 달 INDEX-YYYY-MM.md로
    if os.path.exists(L["worklog_index"]):
        r = archive_worklog_index(L, ic, manifest)
        if r:
            made.append(L["worklog_index"])
        else:
            t = rd(L["worklog_index"])
            if not index_kind(L["worklog_index"]):
                wr(L["worklog_index"], marker("WORKLOG") + t)
                manifest["line_moves"][L["worklog_index"]] = {"kept": list(range(len(lines_keep(t)))), "to": {}}
                manifest["added"][L["worklog_index"]] = [marker("WORKLOG")]

    # 토픽 파일 임계값
    for tp in topic_files(L):
        archive_topic(tp, ic, manifest)

    # 골 INDEX
    if os.path.isdir(L["goals"]):
        rows = [goal_line(p) for p in goal_files(L)]
        active = [r for r in rows if "· active" in r]
        rest = [r for r in rows if r not in active]
        wr(L["goals_index"], marker("GOALS") + "# 골 INDEX\n\n> 한 줄 = 골 하나. 상태의 원천은 골 파일의 `status:` — 이 줄은 표시다(lint가 대조). 골을 만들면(judge --apply) 한 줄이 붙는다. 끝난 골은 [INDEX-done.md](INDEX-done.md)로(`handoff.py archive`).\n\n" + "".join(active))
        wr(f"{L['goals']}/INDEX-done.md", marker("GOALS-DONE") + "# 끝난 골\n\n" + "".join(rest))
        made.append(L["goals_index"])

    write_entry(cfg)
    made.append(L["entry"])
    add_gitattributes(L)
    wr(f"{snap}/manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    return snap, made


def write_entry(cfg):
    L = layout(cfg)
    rel = lambda p: os.path.relpath(p, L["hdir"]).replace("\\", "/")
    rows = [
        ("REMAINING", L["remaining"], "남은 일·착수·결정 대기(활성만)", "항상 — 일을 집기 전", "전부"),
        ("골", L["goals_index"], "활성 골(G-###) 한 줄씩", "골 확인·후보 작성 때 골 파일", "INDEX"),
        ("WORKLOG", L["worklog_index"], "최근 작업 30줄", "이어서 할 작업의 앵커만", "INDEX"),
        ("LESSONS", L["lessons"], "교훈 한 줄씩(횟수)", "같은 실수가 보일 때 본문", "INDEX"),
        ("NORTHSTAR", L["northstar"], "목적·하지 않을 것 목차", "골 판정·후보 작성 때 본문 전체", "INDEX"),
        ("PLAN", L["plan"], "기획 요약 목차", "범위·마일스톤이 걸릴 때 해당 섹션", "INDEX"),
        ("DECISIONS", L["decisions"], "결정 한 줄씩(상태·대체·#화면 태그)", "탐색 단계: 작업이 닿는 #태그 줄만 grep → 본문", "아니오"),
    ]
    out = marker("ENTRY") + "# 핸드오프 진입 인덱스\n\n"
    out += ("> 세션 시작에는 「시작 때」가 전부·INDEX인 파일만 읽는다(목표 12,000자, `handoff.py precheck`가 자 수를 보여 준다). "
            "본문은 골이 정해진 뒤 INDEX에서 고른 것만 연다. 형식·임계값: vibe-flow `docs/structure.md` 「인덱스 계층」.\n\n")
    out += "| 문서 | INDEX | 무엇이 있나 | 언제 본문을 여나 | 시작 때 |\n|---|---|---|---|---|\n"
    for name, p, what, when, start in rows:
        if os.path.exists(p):
            out += f"| {name} | [{rel(p)}]({rel(p)}) | {what} | {when} | {start} |\n"
    wr(L["entry"], out)


def add_gitattributes(L):
    h = L["hdir"]
    g = L["goals"]
    want = [f"{h}/REMAINING.md merge=union", f"{h}/LESSONS.md merge=union", f"{h}/DECISIONS.md merge=union",
            f"{h}/WORKLOG/INDEX.md merge=union", f"{h}/WORKLOG/*.md merge=union",
            f"{h}/INDEX.md merge=union", f"{g}/INDEX.md merge=union", f"{g}/INDEX-done.md merge=union",
            f"{h}/WORKLOG/INDEX-*.md merge=union", f"{h}/DECISIONS-[0-9]*.md merge=union",
            f"{h}/LESSONS-body*.md merge=union", f"{h}/REMAINING-done-*.md merge=union"]
    t = rd(".gitattributes") if os.path.exists(".gitattributes") else ""
    add = [w for w in want if w not in t]
    if add:
        t = t.rstrip("\n") + ("\n" if t else "") + "# 인덱스 구조(vibe-flow structure.md): 같은 파일 끝에 동시에 줄을 붙여도 충돌하지 않게\n" + "\n".join(add) + "\n"
        wr(".gitattributes", t)


def archive_worklog_index(L, ic, manifest=None):
    p = L["worklog_index"]
    t = rd(p)
    ls = lines_keep(t)
    items = [i for i, l in enumerate(ls) if re.match(r"^- \d{4}-\d{2}-\d{2}", l)]
    keep_n = ic["worklog_index_lines"]
    cur = TODAY.strftime("%Y-%m")
    # 최근 N줄을 넘는 줄 + 지난달 줄(개수와 상관없이)
    move = sorted(set(items[keep_n:]) | {i for i in items if ls[i][2:9] < cur})
    if not move:
        return False
    to = {}
    for i in move:
        to.setdefault(f"{L['worklog']}/INDEX-{ls[i][2:9]}.md", []).append(i)
    for name, idxs in to.items():
        old = rd(name) if os.path.exists(name) else marker("WORKLOG-ARCHIVE") + f"# WORKLOG INDEX — {name[-10:-3]}\n\n> INDEX.md에서 옮긴 지난 줄(원문 그대로, 최신이 위).\n\n"
        head, body = old, ""
        m = re.search(r"^- \d{4}-\d{2}-\d{2}", old, re.M)
        if m:
            head, body = old[:m.start()], old[m.start():]
        wr(name, head + "".join(ls[i] for i in idxs) + body)  # 옮기는 줄이 기존 보관 줄보다 새것
    kept = [i for i in range(len(ls)) if i not in set(move)]
    added = []
    body = [ls[i] for i in kept]
    if not index_kind(p):
        added.append(marker("WORKLOG"))
    ptr = "> 지난 줄: " + " · ".join(f"[{os.path.basename(n)}]({os.path.basename(n)})" for n in sorted(
        set(to) | {x.replace('\\', '/') for x in glob.glob(f"{L['worklog']}/INDEX-*.md")})) + "\n"
    old_ptr = [i for i, l in enumerate(body) if l.startswith("> 지난 줄: ")]
    if old_ptr:
        body[old_ptr[0]] = ptr
    else:
        added.append(ptr)
        pos = next((k + 1 for k, l in enumerate(body) if l.startswith("# ")), 0)
        body.insert(pos, ptr)
    wr(p, (marker("WORKLOG") if not index_kind(p) else "") + "".join(body))
    if manifest is not None:
        manifest["line_moves"][p] = {"kept": kept, "to": to}
        manifest["added"][p] = added
    return True


def archive_topic(tp, ic, manifest=None):
    """토픽 파일이 임계값을 넘으면 <topic>-YYYY-MM.md로 옮기고, 새 토픽 파일에 넘김 앵커를 남긴다(옛 링크 유지)."""
    t = rd(tp)
    if len(t) <= ic["topic_max_chars"]:
        return None
    ds = DATE_RE.findall(t)
    mon = max(f"{y}-{m}" for y, m in ds) if ds else TODAY.strftime("%Y-%m")  # 가장 최근 항목의 달
    dst = tp[:-3] + f"-{mon}.md"
    n = 2
    while os.path.exists(dst):
        dst = tp[:-3] + f"-{mon}-{n}.md"
        n += 1
    wr(dst, t)
    m = re.search(r"^(<!--|## )", t, re.M)
    header = t[:m.start()] if m else ""
    bn = os.path.basename(dst)
    stubs = "".join(f"- <a id=\"{a}\"></a>[{a}]({bn}#{a})\n" for a in re.findall(r"\{#([^}\s]+)\}", t))
    wr(tp, header.rstrip("\n") + f"\n\n> 이전 항목은 [{bn}]({bn})로 옮겼다(임계값 {ic['topic_max_chars']}자). 아래는 옛 링크를 위한 넘김 앵커.\n\n" + stubs)
    if manifest is not None:
        manifest["moves"][tp] = [dst]
    return dst


# ---------- verify-migration ----------
def verify(snap, base="HEAD"):
    man = json.loads(rd(f"{snap}/manifest.json"))
    ok, rep = True, []

    def orig(p):
        return rd(f"{snap}/{p}")

    # 스냅숏 자체가 원본인지: 원본이 커밋된 기준(기본 HEAD — migrate 직전 커밋)의 같은 파일과 바이트 비교
    import subprocess
    nbad = 0
    for p in man["files"]:
        if vf_git.git("ls-tree", "--name-only", base, "--", p):
            blob = subprocess.run(["git", "show", f"{base}:{p}"], capture_output=True).stdout
            with open(f"{snap}/{p}", "rb") as f:
                if f.read().replace(b"\r\n", b"\n") != blob.replace(b"\r\n", b"\n"):
                    ok, nbad = False, nbad + 1
                    rep.append(f"BAD 스냅숏 {p}가 {base}의 원본과 다름")
    rep.append(f"스냅숏 = {base} 원본 대조: 파일 {len(man['files'])}개 중 다름 {nbad}개")

    for p, h in man["files"].items():
        if p in man["moves"]:
            got = "".join(rd(x) for x in man["moves"][p])
            same = got == orig(p)
            ok &= same
            rep.append(f"{'OK ' if same else 'BAD'} {p} → {' + '.join(os.path.basename(x) for x in man['moves'][p])} (이어 붙이면 원문과 {'같음' if same else '다름'})")
        elif p in man["line_moves"]:
            lm = man["line_moves"][p]
            ol = lines_keep(orig(p))
            kept = [ol[i] for i in lm["kept"]]
            now = lines_keep(rd(p))
            added = list(man["added"].get(p, []))
            rest = []
            for l in now:
                if l in added:
                    added.remove(l)
                else:
                    rest.append(l)
            same_kept = rest == kept
            moved_ok = True
            for name, idxs in lm["to"].items():
                want = [ol[i] for i in idxs]
                have = [l for l in lines_keep(rd(name)) if not l.startswith(("#", ">", "<!--")) and l.strip()]
                want_ne = [l for l in want if l.strip()]
                # 보관 파일에는 이전 보관분이 더 있을 수 있다 — 옮긴 줄이 순서대로 연속해 들어 있어야 한다
                s = "".join(have)
                moved_ok &= "".join(want_ne) in s
            all_idx = sorted(lm["kept"] + [i for v in lm["to"].values() for i in v])
            cover = all_idx == list(range(len(ol)))
            good = same_kept and moved_ok and cover
            ok &= good
            nmove = sum(len(v) for v in lm["to"].values())
            rep.append(f"{'OK ' if good else 'BAD'} {p}: 원문 {len(ol)}줄 = 남김 {len(lm['kept'])} + 옮김 {nmove}"
                       f" (남긴 줄 순서 {'같음' if same_kept else '다름'}, 옮긴 줄 {'원문 순서대로 있음' if moved_ok else '불일치'}, 누락 {'없음' if cover else '있음'})")
        else:
            same = os.path.exists(p) and sha(p) == h
            ok &= same
            heads = len(re.findall(r"^## ", orig(p), re.M))
            rep.append(f"{'OK ' if same else 'BAD'} {p}: 그대로 ({len(lines_keep(orig(p)))}줄, ## 항목 {heads}개)"
                       if same else f"BAD {p}: 바뀜 또는 없음")
    # 줄 수 합: 옮긴 문서마다 원문 줄 = 새 위치 줄
    for p, dsts in man["moves"].items():
        n_o = len(lines_keep(orig(p)))
        n_n = sum(len(lines_keep(rd(x))) for x in dsts if os.path.exists(x))
        rep.append(f"줄 수 {os.path.basename(p)}: 원문 {n_o} · 옮긴 곳 합 {n_n}")
    # 수치
    dec = man["moves"].get(f"{man['hdir']}/DECISIONS.md")
    if dec:
        n_orig = len(DEC_HEAD_RE.findall(orig(f"{man['hdir']}/DECISIONS.md")))
        n_now = sum(len(DEC_HEAD_RE.findall(rd(x))) for x in dec)
        rep.append(f"결정: 원문 {n_orig}건 · 본문 파일 합 {n_now}건")
        ok &= n_orig == n_now
    return ok, rep


def before_after(snap, cfg):
    man = json.loads(rd(f"{snap}/manifest.json"))
    h = man["hdir"]
    old = [f"{h}/{x}" for x in ("PLAN.md", "REMAINING.md", "DECISIONS.md", "LESSONS.md", "WORKLOG/INDEX.md")]
    before = sum(len(rd(f"{snap}/{p}")) for p in old if os.path.exists(f"{snap}/{p}"))
    after = chars(start_set(cfg))
    return before, after


# ---------- archive ----------
def archive(cfg, dry=False):
    L = layout(cfg)
    ic = icfg(cfg)
    acts = []
    if os.path.exists(L["remaining"]):
        ls = lines_keep(rd(L["remaining"]))
        fresh = fresh_done_lines(L["remaining"])   # 이번 골의 방금 쓴 [x]는 남긴다 — 기록 전·후 어느 쪽에 돌려도 같은 커밋에 합칠 수 있게
        blocks = [b for b in done_blocks(ls) if ls[b[0]] not in fresh]
        if fresh:
            acts.append(f"REMAINING 이번 골 완료 {len(fresh)}건은 남김(check-record가 이 커밋에서 찾는다)")
        if blocks:
            acts.append(f"REMAINING 완료 {len(blocks)}건 → REMAINING-done-YYYY-MM.md")
            if not dry:
                groups = {}
                for s, e, heads in blocks:
                    mon = block_month("".join(ls[s:e]))
                    groups.setdefault(f"{L['hdir']}/REMAINING-done-{mon}.md", []).append((heads, ls[s:e]))
                for name, gs in groups.items():
                    append_with_context(name, f"# 완료한 일 — {name[-10:-3]}\n\n> REMAINING.md에서 옮긴 완료 항목(원문 그대로). 원래 소제목을 함께 적었다.\n", gs)
                drop = {i for s, e, _ in blocks for i in range(s, e)}
                keep = [l for i, l in enumerate(ls) if i not in drop]
                names = sorted(os.path.basename(x) for x in glob.glob(f"{L['hdir']}/REMAINING-done-*.md"))
                ptr = "> 완료 항목은 " + " · ".join(f"[{n}]({n})" for n in names) + "로 옮겼다(`handoff.py archive`).\n"
                pi = [i for i, l in enumerate(keep) if l.startswith("> 완료 항목은 ")]
                if pi:
                    keep[pi[0]] = ptr
                else:
                    pos = next((k + 1 for k, l in enumerate(keep) if l.startswith("# ")), 0)
                    keep.insert(pos, ptr)
                wr(L["remaining"], "".join(keep))
    if os.path.exists(L["worklog_index"]):
        ls = lines_keep(rd(L["worklog_index"]))
        items = [l for l in ls if re.match(r"^- \d{4}-\d{2}-\d{2}", l)]
        cur = TODAY.strftime("%Y-%m")
        n = max(len(items) - ic["worklog_index_lines"], 0) + sum(1 for l in items[:ic["worklog_index_lines"]] if l[2:9] < cur)
        if n:
            acts.append(f"WORKLOG INDEX 오래된 줄 {n}개 → WORKLOG/INDEX-YYYY-MM.md")
            if not dry:
                archive_worklog_index(L, ic)
    for tp in topic_files(L):
        if len(rd(tp)) > ic["topic_max_chars"]:
            acts.append(f"토픽 {os.path.basename(tp)} 임계값 초과 → 옮기고 넘김 앵커")
            if not dry:
                archive_topic(tp, ic)
    if index_kind(L["goals_index"]):
        ls = lines_keep(rd(L["goals_index"]))
        files = {re.match(r"(G-\d{3,})", os.path.basename(p)).group(1): p for p in goal_files(L)}
        mv = []
        for l in ls:
            m = re.match(r"^- (G-\d{3,})", l)
            if m and m.group(1) in files and field(rd(files[m.group(1)]), "status") in ("done", "dropped"):
                mv.append(l)
        if mv:
            acts.append(f"끝난 골 {len(mv)}개 → goals/INDEX-done.md")
            if not dry:
                done = f"{L['goals']}/INDEX-done.md"
                old = rd(done) if os.path.exists(done) else marker("GOALS-DONE") + "# 끝난 골\n\n"
                fixed = [re.sub(r"· active", "· " + field(rd(files[re.match(r'^- (G-\d{3,})', l).group(1)]), "status"), l) for l in mv]
                wr(done, old + "".join(fixed))
                wr(L["goals_index"], "".join(l for l in ls if l not in mv))
    if index_kind(L["decisions"]):
        ls = lines_keep(rd(L["decisions"]))
        rows = [l for l in ls if re.match(r"^- D-\d{3,}", l)]
        if len(rows) > ic["decisions_index_lines"]:
            repl = replaced_set(rows)
            mv = [l for l in rows if re.match(r"^- (D-\d{3,})", l).group(1) in repl]
            if mv:
                acts.append(f"대체된 결정 줄 {len(mv)}개 → DECISIONS-INDEX-replaced.md")
                if not dry:
                    dst = f"{L['hdir']}/DECISIONS-INDEX-replaced.md"
                    old = rd(dst) if os.path.exists(dst) else marker("DECISIONS-REPLACED") + "# 대체된 결정 INDEX\n\n"
                    wr(dst, old + "".join(mv))
                    wr(L["decisions"], "".join(l for l in ls if l not in mv))
    return acts


def replaced_set(rows):
    out = set()
    for l in rows:
        for grp in re.findall(r"대체 (D-\d{3,}(?:·D-\d{3,})*)", l):
            out |= set(grp.split("·"))
        m = re.search(r"대체됨→(D-\d{3,})", l)
        if m:
            out.add(re.match(r"^- (D-\d{3,})", l).group(1))
    return out


# ---------- lint ----------
# archive는 이동만 담은 커밋을 만들지 않는다 — 다음 작업 커밋에 함께(check-record는 작업 파일 없는 커밋을 막는다)
ARCHIVE_HINT = "다음 작업 커밋에서 handoff.py archive (이동만 담은 커밋은 만들지 않는다)"


def fresh_done_lines(rem):
    """방금 쓴 완료 줄: HEAD^의 REMAINING에 없고(이번 기록 커밋이나 amend 전 작업 트리에서 추가)
    줄의 골 ID가 HEAD 메시지나 지금 브랜치에 있다. archive는 다음 작업 커밋에서 기록 쓰기 전에 하므로 경고하지 않고, archive도 옮기지 않는다."""
    ids = set(re.findall(r"\bG-\d{3,}\b", vf_git.git("log", "-1", "--format=%s%n%b") + " " + vf_git.current_branch()))
    if not ids or not os.path.exists(rem):
        return set()
    old = {x.rstrip() for x in vf_git.git("show", f"HEAD^:{rem}").splitlines()}
    return {l for l in lines_keep(rd(rem)) if DONE_RE.match(l) and l.rstrip() not in old
            and any(re.search(rf"\b{re.escape(g)}(?![0-9A-Za-z])", l) for g in ids)}


def lint(cfg):
    L = layout(cfg)
    ic = icfg(cfg)
    err, warn = [], []
    h = L["hdir"]

    def idx_text(*paths):
        return "".join(rd(p) for p in paths if os.path.exists(p))

    # 결정
    if index_kind(L["decisions"]):
        it = idx_text(L["decisions"], f"{h}/DECISIONS-INDEX-replaced.md")
        keys = re.findall(r"^- (D-\d{3,})", it, re.M)
        body_keys = []
        for b in decision_bodies(L):
            for did, title, blk in decision_blocks(rd(b)):
                body_keys.append(did)
                if did not in keys:
                    err.append(f"결정 {did}: 본문({os.path.basename(b)})에 있는데 INDEX에 없음 → DECISIONS.md 끝에 붙일 줄:\n    "
                               + decision_line(did, title, blk, b).rstrip())
        for k in sorted(set(x for x in body_keys if body_keys.count(x) > 1)):
            err.append(f"결정 번호 {k}가 본문에 두 번 — 뒤에 온 쪽 번호를 handoff.py next-id D로 다시 받는다")
        for k in sorted(set(x for x in keys if keys.count(x) > 1)):
            err.append(f"결정 INDEX에 {k} 줄이 두 개(union 병합 흔적) — 하나만 남긴다")
        for k in sorted(set(keys) - set(body_keys)):
            err.append(f"결정 INDEX의 {k}에 해당하는 본문 없음")
        repl = replaced_set(re.findall(r"^- D-.*$", it, re.M))
        for b in decision_bodies(L):
            for did, _, blk in decision_blocks(rd(b)):
                if did in repl and re.search(r"상태 유효", blk):
                    warn.append(f"결정 {did}: INDEX상 대체됨인데 본문 상태가 유효 — 본문 상태 줄을 「대체됨 → D-nnn」으로(팀 규칙)")
        bs = decision_bodies(L)
        if bs:
            last = rd(bs[-1])
            if len(DEC_HEAD_RE.findall(last)) > ic["decisions_per_file"] or len(last) > ic["body_max_chars"]:
                warn.append(f"{os.path.basename(bs[-1])}가 임계값({ic['decisions_per_file']}건·{ic['body_max_chars']}자) 초과 — 다음 결정은 새 본문 파일(next-id가 안내)")
        if len(keys) > ic["decisions_index_lines"]:
            warn.append(f"결정 INDEX {len(keys)}줄 > {ic['decisions_index_lines']} → " + ARCHIVE_HINT + " — 대체된 줄 이동")
    # 섹션형(PLAN·NORTHSTAR)
    for key in ("plan", "northstar"):
        p = L[key]
        if index_kind(p):
            it = rd(p)
            for body in sorted(x.replace("\\", "/") for x in glob.glob(p[:-3] + "-*.md")):
                bt = rd(body)
                for m in re.finditer(r"^## (.+?)\s*$", bt, re.M):
                    if f"{os.path.basename(body)}#{slug(m.group(1))})" not in it:
                        err.append(f"{os.path.basename(body)}의 섹션 「{m.group(1)}」이 {os.path.basename(p)} INDEX에 없음 → 붙일 줄: "
                                   + section_lines(f"## {m.group(1)}\n", os.path.basename(body))[0].rstrip())
                if len(bt) > ic["body_max_chars"]:
                    warn.append(f"{os.path.basename(body)} {len(bt)}자 > {ic['body_max_chars']} — 섹션별 파일로 나눌 것")
    # 교훈
    if index_kind(L["lessons"]):
        it = rd(L["lessons"])
        ik = re.findall(r"^- (L-\d{3,})", it, re.M)
        bodies = sorted(glob.glob(f"{h}/LESSONS-body*.md"))
        nb = 0
        for b in bodies:
            for l in rd(b).splitlines():
                if l.startswith("- "):
                    nb += 1
                    m = re.search(r"\bL-\d{3,}\b", l)
                    if m and m.group(0) not in ik:
                        err.append(f"교훈 {m.group(0)}가 LESSONS.md INDEX에 없음")
        if nb > len(ik):
            err.append(f"교훈 본문 {nb}개 > INDEX {len(ik)}줄 — 새 교훈의 INDEX 줄 누락(L-nnn)")
        for k in sorted(set(x for x in ik if ik.count(x) > 1)):
            err.append(f"교훈 INDEX에 {k} 줄이 두 개 — 하나만 남긴다")
    # WORKLOG
    if os.path.isdir(L["worklog"]):
        it = idx_text(*glob.glob(f"{L['worklog']}/INDEX*.md"))
        active = set(topic_files(L))
        for tp in topic_files(L, archived_too=True):  # INDEX 대조는 보관 파일까지, 크기 경고는 활성 파일만
            for m in re.finditer(r"^## .*\{#([^}\s]+)\}", rd(tp), re.M):
                if f"#{m.group(1)})" not in it and f"#{m.group(1)}]" not in it:
                    err.append(f"WORKLOG {os.path.basename(tp)}#{m.group(1)}가 INDEX에 없음")
            if tp in active and len(rd(tp)) > ic["topic_max_chars"]:
                warn.append(f"WORKLOG {os.path.basename(tp)} {len(rd(tp))}자 > {ic['topic_max_chars']} → " + ARCHIVE_HINT)
        if os.path.exists(L["worklog_index"]):
            items = re.findall(r"^- (\d{4}-\d{2})-\d{2}", rd(L["worklog_index"]), re.M)
            if len(items) > ic["worklog_index_lines"]:
                warn.append(f"WORKLOG INDEX {len(items)}줄 > {ic['worklog_index_lines']} → " + ARCHIVE_HINT)
            old = [x for x in items if x < TODAY.strftime("%Y-%m")]
            if old:
                warn.append(f"WORKLOG INDEX에 지난달 줄 {len(old)}개 → " + ARCHIVE_HINT)
    # 골
    if index_kind(L["goals_index"]):
        it = idx_text(L["goals_index"], f"{L['goals']}/INDEX-done.md")
        rows = {m.group(1): m.group(0) for m in re.finditer(r"^- (G-\d{3,}).*$", it, re.M)}
        ks = re.findall(r"^- (G-\d{3,})", it, re.M)
        for k in sorted(set(x for x in ks if ks.count(x) > 1)):
            err.append(f"골 INDEX에 {k} 줄이 두 개 — 하나만 남긴다")
        for p in goal_files(L):
            gid = re.match(r"(G-\d{3,})", os.path.basename(p)).group(1)
            st = field(rd(p), "status")
            if gid not in rows:
                err.append(f"골 {gid}가 goals/INDEX.md에 없음 → 붙일 줄: {goal_line(p).rstrip()}")
            elif f"· {st}" not in rows[gid]:
                err.append(f"골 {gid}: 파일 status={st}인데 INDEX 줄은 「{rows[gid][:60]}」 — INDEX 줄 상태를 맞춘다(원천은 골 파일)")
    # REMAINING
    if os.path.exists(L["remaining"]):
        ls = lines_keep(rd(L["remaining"]))
        fresh = fresh_done_lines(L["remaining"])
        nd = sum(1 for s, _, _ in done_blocks(ls) if ls[s] not in fresh)
        if nd:
            warn.append(f"REMAINING에 완료 항목 {nd}건 잔존 → " + ARCHIVE_HINT)
        act = sum(1 for l in ls if OPEN_RE.match(l))
        if act > ic["remaining_active_lines"]:
            warn.append(f"REMAINING 활성 {act}줄 > {ic['remaining_active_lines']} — 큰 묶음은 별도 문서로 빼고 링크")
    # 링크
    for p in glob.glob(f"{h}/**/*.md", recursive=True):
        p = p.replace("\\", "/")
        if p.startswith(f"{h}/mr/"):  # MR 본문 사본: 캡처 링크가 추적 안 하는 .vibe/를 가리킬 수 있다
            continue
        base = os.path.dirname(p)
        for t in links_of(rd(p)):
            path, _, anc = t.partition("#")
            tgt = os.path.normpath(os.path.join(base, path)) if path else p
            tgt = unquote(tgt)
            if not os.path.exists(tgt):
                err.append(f"끊긴 링크: {p} → {t}")
            elif anc and tgt.endswith(".md") and unquote(anc) not in anchors_of(rd(tgt)):
                err.append(f"없는 앵커: {p} → {t}")
    # 시작 읽기량
    tot = chars(start_set(cfg))
    if tot > ic["start_budget"]:
        warn.append(f"세션 시작 읽기량 {tot}자 > 목표 {ic['start_budget']} → " + ARCHIVE_HINT + ", 또는 활성 목록을 줄인다")
    return err, warn


# ---------- check-record 보강 ----------
def missing_index_lines(cfg, files, added, lo="HEAD^", hi="HEAD"):
    """added(path) -> 그 커밋에서 추가된 줄. 본문에 새로 쓴 항목마다 INDEX 줄이 같은 커밋에 있어야 한다."""
    L = layout(cfg)
    miss = []
    h = L["hdir"]

    # '이동'은 새 항목이 아니다(migrate·archive·섹션 분리 커밋). 같은 커밋에서 **같은 문서군**
    # (DECISIONS.md·DECISIONS-*.md, PLAN.md·PLAN-*.md …)의 파일에서 지워진 줄과 짝이 맞는 추가 줄만 이동으로 친다.
    # 다른 문서에 같은 문자열이 있어도, 지워지지 않았으면 새 항목이다.
    def family(path):
        d, base = os.path.dirname(path), os.path.basename(path)
        for stem in ("DECISIONS", "LESSONS", "PLAN", "NORTHSTAR"):
            if d == h and (base == f"{stem}.md" or base.startswith(f"{stem}-")):
                return stem
        return path

    removed = {}
    for f in files:
        for l in vf_git.git("diff", lo, hi, "--", f).splitlines():
            if l.startswith("-") and not l.startswith(("--- a/", "--- /dev/null")):
                removed.setdefault(family(f), collections.Counter())[l[1:]] += 1
    cache, _added = {}, added

    def added(p):  # noqa: F811 — 이동 줄을 뺀 추가 줄(파일마다 한 번만 계산해 짝을 소모)
        if p not in cache:
            c = removed.get(family(p), collections.Counter())
            out = []
            for l in _added(p):
                if c[l] > 0:
                    c[l] -= 1
                else:
                    out.append(l)
            cache[p] = out
        return cache[p]
    if index_kind(L["decisions"]):
        idx = "".join(added(L["decisions"]))
        for f in files:
            if f.startswith(h + "/") and BODY_RE.search(f) and "/" not in f[len(h) + 1:]:
                for l in added(f):
                    m = re.match(r"^## (D-\d{3,})", l)
                    if m and m.group(1) not in idx:
                        miss.append(f"{m.group(1)} 본문을 썼는데 DECISIONS.md INDEX 줄이 이 커밋에 없음")
    if index_kind(L["lessons"]):
        idx = "".join(added(L["lessons"]))
        for f in files:
            if re.match(rf"^{re.escape(h)}/LESSONS-body.*\.md$", f):
                for l in added(f):
                    if l.startswith("- "):
                        m = re.search(r"\bL-\d{3,}\b", l)
                        if not m:
                            miss.append("새 교훈 줄에 번호(L-nnn) 없음 — handoff.py next-id L")
                        elif m.group(0) not in idx:
                            miss.append(f"{m.group(0)} 교훈을 썼는데 LESSONS.md INDEX 줄이 이 커밋에 없음")
    for key in ("plan", "northstar"):
        p = L[key]
        if index_kind(p):
            idx = "".join(added(p))
            # 본문은 PLAN-body.md에서 시작해, 넘치면 섹션별 PLAN-<slug>.md로 나뉜다 — 모든 본문 파일을 본다
            for body in (f for f in files if f.startswith(p[:-3] + "-") and f.endswith(".md")):
                for l in added(body):
                    m = re.match(r"^## (.+?)\s*$", l)
                    if m and f"#{slug(m.group(1))})" not in idx:
                        miss.append(f"{os.path.basename(body)}에 새 섹션 「{m.group(1)}」 — {os.path.basename(p)} INDEX 줄이 이 커밋에 없음")
    if index_kind(L["goals_index"]):
        idx = "".join(added(L["goals_index"]))
        for f in files:
            m = re.match(rf"^{re.escape(L['goals'])}/(G-\d{{3,}})[^/]*\.md$", f)
            new = m and vf_git.git("ls-tree", "--name-only", lo, "--", f) == ""
            if new and m.group(1) not in idx:
                miss.append(f"새 골 {m.group(1)} — goals/INDEX.md 줄이 이 커밋에 없음")
    return miss


# ---------- 번호 발급 ----------
def known_ids(kind, cfg):
    L = layout(cfg)
    h = L["hdir"]
    pat = rf"\b{kind}-[0-9]{{3,}}\b"
    spec = {"D": [f"{h}/DECISIONS*.md"], "L": [f"{h}/LESSONS*.md"]}[kind]
    nums = set()
    for g in spec:
        for p in glob.glob(g):
            nums |= {int(x[2:]) for x in re.findall(pat, rd(p))}
    for ref in vf_git.git("for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes").splitlines():
        out = vf_git.git("grep", "-h", "-o", "-E", f"{kind}-[0-9]{{3,}}", ref, "--", *spec)
        nums |= {int(x.split("-")[1]) for x in out.split() if re.fullmatch(rf"{kind}-\d{{3,}}", x)}
    return nums


def common_dir():
    d = os.path.join(os.path.abspath(vf_git.git("rev-parse", "--git-common-dir") or ".git"), "vibe-flow")
    os.makedirs(d, exist_ok=True)
    return d


def remote_reserved(kind):
    out = vf_git.git("ls-remote", "origin", f"refs/vibe-ids/{kind}-*")
    return {int(m.group(1)) for m in re.finditer(rf"refs/vibe-ids/{kind}-(\d+)", out)}


def next_id(kind, cfg, scan_only=False):
    """반환: (ID, 안내 문자열). 원격 예약 실패 시 SystemExit."""
    ic = icfg(cfg)
    remote = ("origin" in vf_git.git("remote").split() and ic["id_reserve"] == "remote" and not scan_only
              and (cfg or {}).get("remote", True) is not False)
    lock = os.path.join(common_dir(), f"ids-{kind}.lock")
    for _ in range(100):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.time() - os.path.getmtime(lock) > 60:
                os.remove(lock)
            time.sleep(0.1)
    else:
        raise SystemExit("[next-id] 잠금을 얻지 못함")
    try:
        if remote:
            vf_git.git("fetch", "-q", "origin")
        ledger = os.path.join(common_dir(), f"ids-{kind}.txt")
        nums = known_ids(kind, cfg)
        if os.path.exists(ledger):
            nums |= {int(x[2:]) for x in rd(ledger).split() if x.startswith(f"{kind}-")}
        if remote:
            nums |= remote_reserved(kind)
        n = max(nums | {0}) + 1
        if remote:
            empty = run_git(["hash-object", "-t", "tree", "-w", "--stdin"], "")
            for _ in range(20):
                ident = f"{kind}-{n:03d}"
                c = vf_git.git("commit-tree", empty, "-m", f"reserve {ident} by {vf_git.me()} {time.time()}")
                r = subprocess_push(c, ident)
                if r == "ok":
                    break
                if r == "taken":
                    n += 1
                    continue
                raise SystemExit(f"[next-id] 원격 예약 실패({r}) — 번호를 내주지 않습니다. 네트워크·권한을 확인하세요.\n"
                                 f"  원격 없이 발급하는 우회는 사용자가 직접: python handoff.py next-id {kind} --scan-only")
            else:
                raise SystemExit("[next-id] 원격 예약 20회 충돌")
        ident = f"{kind}-{n:03d}"
        with open(ledger, "a", encoding="utf-8") as f:
            f.write(ident + "\n")
    finally:
        os.close(fd)
        os.remove(lock)
    hint = ""
    if kind == "D":
        target, new = decision_target(cfg)
        if index_kind(layout(cfg)["decisions"]):
            hint = (f"{target} 끝에 `## {ident} 제목` 블록" + (" (새 파일 — DECISIONS.md 머리말 「본문:」에도 추가)" if new else "")
                    + ", DECISIONS.md 끝에 INDEX 한 줄")
        else:
            hint = f"{target} 끝에 `## {ident} 제목` 블록" + (" (새 파일)" if new else "")
    elif kind == "L":
        hint = "LESSONS-body.md 끝에 `- … (" + ident + ", @작성자, 날짜)`, LESSONS.md 끝에 INDEX 한 줄"
    return ident, hint + (" · 원격 예약 refs/vibe-ids/" + ident if remote else " · 원격 예약 없음(스캔·장부만)")


def run_git(args, stdin):
    import subprocess
    return subprocess.run(["git", *args], input=stdin, capture_output=True, text=True, encoding="utf-8").stdout.strip()


def decision_target(cfg):
    """새 결정을 붙일 본문 파일: 이번 달 마지막 부, 넘쳤으면 다음 부, 이번 달 파일이 없으면 새 달 파일. (경로, 새 파일인가)"""
    L = layout(cfg)
    ic = icfg(cfg)
    if not index_kind(L["decisions"]):  # 인덱스 모드가 아니면 결정은 DECISIONS.md 한 파일에
        return L["decisions"], not os.path.exists(L["decisions"])
    mon = TODAY.strftime("%Y-%m")
    mine = [p for p in decision_bodies(L) if body_key(p)[0] == mon]
    if not mine:
        return body_name(L["hdir"], mon, 1), True
    last = rd(mine[-1])
    if len(DEC_HEAD_RE.findall(last)) >= ic["decisions_per_file"] or len(last) >= ic["body_max_chars"]:
        return body_name(L["hdir"], mon, body_key(mine[-1])[1] + 1), True
    return mine[-1], False


def subprocess_push(commit, ident):
    import subprocess
    r = subprocess.run(["git", "push", "-q", f"--force-with-lease=refs/vibe-ids/{ident}:", "origin",
                        f"{commit}:refs/vibe-ids/{ident}"], capture_output=True, text=True, encoding="utf-8")
    if r.returncode == 0:
        return "ok"
    msg = (r.stderr or "") + (r.stdout or "")
    if re.search(r"stale info|already exists|non-fast-forward|fetch first|! \[rejected\]", msg):
        return "taken"
    return msg.strip()[:200] or "unknown"
