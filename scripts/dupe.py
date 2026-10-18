"""MR을 만들기 전에 같은 골·같은 파일·비슷한 내용의 작업이 이미 있는지 찾는다.

mr_check.py --stage draft 가 부른다. 단독 실행: python dupe.py <mr-body.md>
- 같은 골 ID를 쓰는 다른 로컬 브랜치 또는 열린 원격 MR/PR → 차단 (합류하거나 골을 나눈다)
- 지금 작업물과 변경 파일이 겹치는 다른 브랜치 → 경고
- 골·사용자 가치 문장이 비슷한 열린 원격 MR/PR → 경고
원격 조회는 gh 또는 glab이 있고 원격이 설정된 경우에만 한다.
"""
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vf_git  # noqa: E402

ID_RE = re.compile(r"\bG-\d{3,}\b")


def words(text):
    return {w for w in re.findall(r"[\w가-힣]{2,}", text.lower()) if not w.startswith("g-")}


def similarity(a, b):
    a, b = words(a), words(b)
    return len(a & b) / len(a | b) if a and b else 0.0


def remote_mrs():
    """열린 원격 MR/PR 목록: [{"id", "title", "branch", "body"}]. 조회할 수 없으면 빈 목록."""
    remotes = vf_git.git("remote").split()
    if not remotes:
        return []
    # 원격 주소로 공급자를 고르고(gitlab이면 glab 먼저), 앞의 도구가 실패하면 다음 도구로 넘어간다
    url = vf_git.git("remote", "get-url", "origin" if "origin" in remotes else remotes[0]).lower()
    order = ["glab", "gh"] if "gitlab" in url else ["gh", "glab"]
    for tool in order:
        if not shutil.which(tool):
            continue
        try:
            if tool == "gh":
                r = subprocess.run(["gh", "pr", "list", "--state", "open", "--limit", "100",
                                    "--json", "number,title,headRefName,body"],
                                   capture_output=True, text=True, encoding="utf-8", timeout=60)
                if r.returncode == 0:
                    return [{"id": f"#{x['number']}", "title": x["title"], "branch": x["headRefName"],
                             "body": x.get("body") or ""} for x in json.loads(r.stdout or "[]")]
            else:
                r = subprocess.run(["glab", "mr", "list", "--output", "json"],
                                   capture_output=True, text=True, encoding="utf-8", timeout=60)
                if r.returncode == 0:
                    return [{"id": f"!{x['iid']}", "title": x["title"], "branch": x["source_branch"],
                             "body": x.get("description") or ""} for x in json.loads(r.stdout or "[]")]
        except (subprocess.SubprocessError, OSError, ValueError, KeyError):
            pass
    return []


def conflict_note(base, other):
    """지금 브랜치 HEAD와 다른 브랜치를 합치면 충돌이 나는지 git merge-tree로 미리 본다 (커밋 모드)."""
    if not vf_git.git("rev-parse", "--verify", "-q", "HEAD"):
        return ""
    r = subprocess.run(["git", "-c", "core.quotepath=off", "merge-tree", "--write-tree", "--name-only", "HEAD", other],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode == 1:
        files = [l for l in r.stdout.splitlines()[1:] if l and not l.startswith(("Auto-merging", "CONFLICT"))]
        return f" — 합치면 충돌 예상: {', '.join(files[:3])}"
    return ""


CLAIM_RE = re.compile(r"^\s*-\s*\[~\]\s*(.*?)\(착수\s*@(\S+)\s+(\d{4}-\d{2}-\d{2})\)(?:\s*→\s*(\S+))?"
                      r"(?:\s*·\s*범위:\s*([^\n]*?))?[ \t]*$", re.M)
SCOPE_RE = re.compile(r"\s*·\s*범위:.*$")


def scope_list(value):
    """'범위:' 값 → 파일·폴더 경로 목록(쉼표 구분, 공백 제거, 빈 값 제외)."""
    return [x.strip() for x in (value or "").split(",") if x.strip()]


def claim_entries(cfg):
    """REMAINING의 착수 표시 [{ids, task, who, date, branch, files, src}]. 작업 트리 + 모든 브랜치 끝을 본다.
    같은 착수(할 일·작성자·날짜·브랜치)가 여러 곳에 있으면 범위가 공지된 쪽을 쓴다 — 범위는 골 브랜치에만 먼저 올라간다."""
    rem = f"{vf_git.paths(cfg)['handoff']}/REMAINING.md"
    texts = []
    if os.path.exists(rem):
        with open(rem, encoding="utf-8") as f:
            texts.append(("작업 트리", f.read()))
    for ref in vf_git.git("for-each-ref", "--format=%(refname:short)", "refs/heads", "refs/remotes").splitlines():
        if ref.endswith("/HEAD"):
            continue
        t = vf_git.git("show", f"{ref}:{rem}")
        if t:
            texts.append((ref, t))
    got = {}
    for src, t in texts:
        for m in CLAIM_RE.finditer(t):
            key = (m.group(1).strip(), m.group(2), m.group(3), m.group(4))  # 브랜치가 다르면 다른 착수
            files = scope_list(m.group(5))
            if key in got and (got[key]["files"] or not files):
                continue
            task = m.group(1).strip() + (f" → {m.group(4)}" if m.group(4) else "") + (f" · 범위: {', '.join(files)}" if files else "")
            got[key] = {"ids": set(ID_RE.findall(m.group(1))), "task": task, "who": m.group(2), "date": m.group(3),
                        "branch": m.group(4) or "", "files": files, "src": src}
    return list(got.values())


def claims(cfg):
    """REMAINING의 착수 표시 [(골 ID 집합, 할 일, 작성자, 날짜, 출처)] — 할 일에 공지된 범위가 붙는다."""
    return [(e["ids"], e["task"], e["who"], e["date"], e["src"]) for e in claim_entries(cfg)]


def section(mr_text, name):
    return (re.search(rf"^##\s+{name}\s*\n(.*?)(?=^##\s|\Z)", mr_text or "", re.M | re.S) or [None, ""])[1]


def planned_files(mr_text):
    """MR 「설계」 '바꿀 모듈·파일:' 줄의 경로. 백틱 안 값이 있으면 그것만, 없으면 경로처럼 생긴 낱말(확장자·'/' 포함)."""
    m = re.search(r"^\s*[-*]?\s*바꿀 모듈·파일\s*:\s*(.+)$", section(mr_text, "설계"), re.M)
    if not m:
        return []
    v = m.group(1)
    found = re.findall(r"`([^`\s]+)`", v) or re.findall(r"(?<![\w./-])((?:[\w.-]+/)*[\w.-]*[\w-]\.\w{1,6}|(?:[\w.-]+/)+)(?![\w/])", v)
    out = []
    for f in found:
        f = f.strip().lstrip("./") if f.startswith("./") else f.strip()
        if f and f not in out:
            out.append(f)
    return out


def path_hit(a, b):
    """같은 파일이거나, 한쪽이 '/'로 끝나는 폴더이고 다른 쪽이 그 안에 있다."""
    return a == b or (b.endswith("/") and a.startswith(b)) or (a.endswith("/") and b.startswith(a))


def touched_files(cfg):
    """지금 작업물이 기준 대비 바꾼 파일 — 핸드오프 기록·골·.vibe/ 는 뺀다(남의 범위와 겹침을 볼 코드·문서)."""
    p = vf_git.paths(cfg)
    skip = (p["handoff"].rstrip("/") + "/", p["goals"].rstrip("/") + "/", ".vibe/")
    try:
        files = vf_git.changed_files(vf_git.base_tree(cfg["base"]), vf_git.snapshot())
    except (RuntimeError, KeyError):
        return []
    return [f for f in files if not f.startswith(skip)]


ACK_RE = re.compile(r"^\s*[-*]?\s*겹침 확인\s*:\s*(G-\d{3,})\s*[—–-]+\s*\S", re.M)


def scope_overlaps(mr_text, cfg, today=None):
    """남이 공지한 착수 범위(7일 이내, 다른 골)와 내 계획(「설계」 바꿀 파일)·실제 변경 파일이 겹치면 차단 항목.
    겹침을 알고 피하거나 조율했다는 기록 — 「영향·위험」 '- 겹침 확인: G-### — <어떻게>' — 이 있는 골은 통과."""
    import datetime
    my_ids = set(ID_RE.findall(section(mr_text, "골"))) - {"G-000"}
    mine = list(dict.fromkeys(planned_files(mr_text) + touched_files(cfg)))
    if not mine:
        return []
    acked = set(ACK_RE.findall(section(mr_text, "영향·위험")))
    today = today or datetime.date.today()
    days, me, out = cfg.get("claim_days", 7), vf_git.me(), []
    for e in claim_entries(cfg):
        if e["who"] == me or not e["files"] or e["ids"] & my_ids:
            continue
        if (today - datetime.date.fromisoformat(e["date"])).days > days:
            continue
        hit = [f for f in mine if any(path_hit(f, s) for s in e["files"])]
        gids = sorted(e["ids"] - {"G-000"}) or sorted(e["ids"])
        if not hit or (set(gids) & acked):
            continue
        g = gids[0] if gids else "G-###"
        out.append(f"@{e['who']}가 {g}에서 {', '.join(hit[:5])}을(를) 바꾸는 중({e['branch'] or e['src']}) — 피하거나 조율하고 "
                   f"「영향·위험」에 '- 겹침 확인: {g} — <어떻게 피하거나 조율할지>'")
    return out


def candidate_titles(cfg):
    d = vf_git.paths(cfg)["candidates"]
    if not os.path.isdir(d):
        return []
    out = []
    for fn in sorted(os.listdir(d)):
        with open(os.path.join(d, fn), encoding="utf-8") as f:
            out.append((fn, f.readline().lstrip("# ").strip()))
    return out


def find(mr_text, cfg, remotes=None, today=None):
    """(blocks, warnings) 를 돌려준다."""
    import datetime
    sec = lambda name: (re.search(rf"^##\s+{name}\s*\n(.*?)(?=^##\s|\Z)", mr_text, re.M | re.S) or [None, ""])[1]
    my_ids = set(ID_RE.findall(sec("골"))) - {"G-000"}
    my_text = sec("골") + " " + sec("사용자 가치")
    cur = vf_git.current_branch()
    me = vf_git.me()
    blocks, warns = [], []

    # 1) 착수 표시 (team-handoff REMAINING) — 다른 사람이 7일 안에 집은 같은 골은 차단
    today = today or datetime.date.today()
    days = cfg.get("claim_days", 7)
    stale_branches = set()   # 착수 표시가 기간을 넘긴 브랜치 — 같은 골이라도 다시 집을 수 있다
    for ids, task, who, date, src in claims(cfg):
        age = (today - datetime.date.fromisoformat(date)).days
        if who != me and age > days:
            m = re.search(r"→\s*(\S+)\s*$", task) or re.search(r"\s([\w.-]+/G-\d{3,}[\w.-]*)", task)
            if m:
                stale_branches.add(m.group(1))
            stale_branches.add(src.split("/", 1)[1] if "/" in src and src.startswith("origin/") else src)
        if who == me:
            if ids & my_ids and src not in ("작업 트리", cur) and not src.endswith("/" + cur):
                warns.append(f"내가 다른 브랜치({src})에서도 같은 골을 착수함: {task}")
            continue
        if age > days:
            if ids & my_ids:
                warns.append(f"@{who}의 착수 표시가 {age}일 지남 — 다시 집으려면 착수 줄을 교체하고 WORKLOG에 사유: {task}")
            continue
        if ids & my_ids:
            blocks.append(f"@{who}가 {date}에 같은 골을 착수함({src}): {task} — 합류하거나 골을 나누세요")
        elif similarity(my_text, task) >= 0.35:
            warns.append(f"@{who}가 착수한 비슷한 일({src}): {task} — 중복인지 확인하세요")

    # 2) 비슷한 골 후보
    for fn, title in candidate_titles(cfg):
        if similarity(my_text, title) >= 0.35:
            warns.append(f"비슷한 골 후보 {fn}: {title}")

    # 3) 같은 골 브랜치 (로컬 + 원격), 파일 겹침·충돌 예측
    base = cfg["base"]
    mine = set(vf_git.changed_files(vf_git.base_tree(base), vf_git.snapshot()))
    refs = vf_git.git("for-each-ref", "--format=%(refname:short)", "refs/heads", "refs/remotes").splitlines()
    for b in refs:
        short = b.split("/", 1)[1] if b.startswith(tuple(r + "/" for r in vf_git.git("remote").split())) else b
        if b.endswith("/HEAD") or short in (cur, base) or b == base:
            continue
        same = my_ids & set(ID_RE.findall(b))
        if same and short in stale_branches:
            warns.append(f"브랜치 {b}는 같은 골이지만 착수 표시가 기간을 넘김 — 다시 집을 수 있음")
        elif same:
            blocks.append(f"브랜치 {b}가 같은 골 {', '.join(sorted(same))}을 작업 중 — 그 작업에 합류하거나 골을 나누세요")
        mb = vf_git.git("merge-base", base, b) if vf_git.obj_type(base) == "commit" else ""
        theirs = set(vf_git.git("diff", "--name-only", mb, b).splitlines()) if mb else set()
        both = sorted(mine & theirs)
        if both:
            warns.append(f"브랜치 {b}와 변경 파일 겹침: {', '.join(both[:5])}{' …' if len(both) > 5 else ''}"
                         + conflict_note(base, b))

    for mr in (remote_mrs() if remotes is None else remotes):
        if mr["branch"] == cur:
            continue
        same = my_ids & set(ID_RE.findall(mr["title"] + " " + mr["branch"] + " " + mr["body"]))
        if same:
            blocks.append(f"열린 MR {mr['id']} \"{mr['title']}\"가 같은 골 {', '.join(sorted(same))} — 합류하거나 골을 나누세요")
        elif similarity(my_text, mr["title"] + " " + mr["body"][:500]) >= 0.35:
            warns.append(f"비슷한 열린 MR {mr['id']} \"{mr['title']}\" — 중복인지 확인하고 「계획 vs 실제」에 판단을 적으세요")
    return blocks, warns


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    with open(sys.argv[1], encoding="utf-8") as f:
        b, w = find(f.read(), vf_git.config())
    for x in b:
        print("[dupe] 차단:", x)
    for x in w:
        print("[dupe] 경고:", x)
    if not b and not w:
        print("[dupe] 겹치는 작업 없음")
    sys.exit(1 if b else 0)
