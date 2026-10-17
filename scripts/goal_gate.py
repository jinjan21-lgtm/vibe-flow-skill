#!/usr/bin/env python3
"""골 게이트: 골 ID 없는 커밋을 막고, 새 골은 바깥눈(Codex)이 노스스타와 대조해 판정한다.

  python goal_gate.py install-hook               현재 레포에 commit-msg 훅 설치
  python goal_gate.py check-commit <msg-file>    (훅이 호출) 커밋 메시지·브랜치에 활성 골 ID가 있는지 검사
  python goal_gate.py candidate "<제목>"         골 후보 파일 생성 -> docs/goals/candidates/
  python goal_gate.py judge <후보.md> [--apply]  Codex가 판정. --apply면 결과대로 골 생성/거절 반영
  python goal_gate.py list                       골 목록과 상태
  python goal_gate.py reserve-id                 다음 골 ID 예약 (judge가 내부에서 씀. 병행 작업에서도 중복 없음)
  python goal_gate.py overlap                    다른 브랜치와 변경 파일이 겹치는지 경고

레포 루트에서 실행한다. 표준 라이브러리만 쓴다.
"""
import datetime
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vf_git  # noqa: E402

_P = vf_git.paths()  # 팀: docs/handoff/…, 개인: docs/… (.vibe-flow.json으로 덮어쓰기)
GOALS = _P["goals"]
CANDS = _P["candidates"]
REJECTED = _P["rejected"]
NORTHSTAR = _P["northstar"]
ID_RE = re.compile(r"\bG-\d{3,}\b")
TODAY = datetime.date.today().isoformat()

GOAL_TEMPLATE = """# {id} {title}
<!--
id: {id}
status: active
created: {date}
judge: {judge}
-->

{body}
"""

CANDIDATE_TEMPLATE = """# {title}
<!--
status: candidate
found-in: {found_in}
created: {date}
-->

## 왜 필요한가 (노스스타의 어느 문장과 연결되는가)

## 완료 조건 (관찰 가능한 결과)

## 하지 않을 것

## 발견 경위
"""

JUDGE_PROMPT = """당신은 이 레포의 골 심사자(바깥눈)입니다. 작업 중인 에이전트가 올린 골 후보를 노스스타와 대조해 판정합니다.
작업 에이전트는 자기가 만들고 싶은 골에 관대합니다. 당신은 노스스타의 "하지 않을 것"과 기존 골 중복을 엄격히 봅니다.

[노스스타 — 원문 전체]
{northstar}

[활성 골 목록]
{goals}

[골 후보 — 원문 전체]
{candidate}

[판정 기준]
1. 노스스타의 목적 문장 중 하나에 직접 연결되는가. 연결 문장을 인용하라.
2. 노스스타의 "하지 않을 것"에 걸리는가. 걸리면 REJECT.
3. 기존 활성 골과 같은 결과를 내는가. 그렇다면 MERGE.
4. 완료 조건이 관찰 가능한가. 아니면 REJECT하고 무엇을 고쳐야 하는지 적어라.

[출력 형식 — 첫 줄은 반드시 셋 중 하나]
VERDICT: CREATE
VERDICT: REJECT
VERDICT: MERGE G-###
REASON: (2~4문장. 근거가 된 노스스타 문장 또는 하지 않을 것 인용)
"""


def die(msg, code=1):
    print(msg, file=sys.stderr)
    sys.exit(code)


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def field(text, name):
    m = re.search(rf"^{name}:\s*(.+)$", text, re.M)
    return m.group(1).strip() if m else ""


def goal_files():
    if not os.path.isdir(GOALS):
        return {}
    out = {}
    for fn in sorted(os.listdir(GOALS)):
        m = re.match(r"(G-\d{3,})", fn)
        if m and fn.endswith(".md"):
            out[m.group(1)] = os.path.join(GOALS, fn)
    return out


def git(*args):
    return subprocess.run(["git", "-c", "core.quotepath=off", *args], capture_output=True, text=True, encoding="utf-8").stdout.strip()


def common_dir():
    """worktree들이 함께 쓰는 .git 공통 폴더 아래 vibe-flow 상태 폴더."""
    d = os.path.join(os.path.abspath(git("rev-parse", "--git-common-dir") or ".git"), "vibe-flow")
    os.makedirs(d, exist_ok=True)
    return d


def all_known_ids():
    """작업 트리 + 모든 로컬·원격 브랜치의 docs/goals + 예약 장부에 있는 골 번호."""
    nums = {int(g[2:]) for g in goal_files()}
    for ref in git("for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes").splitlines():
        for path in git("ls-tree", "-r", "--name-only", ref, "--", GOALS).splitlines():
            m = re.search(r"G-(\d{3,})", path.split("/")[-1])
            if m:
                nums.add(int(m.group(1)))
    ledger = os.path.join(common_dir(), "goal-ids.txt")
    if os.path.exists(ledger):
        nums |= {int(x[2:]) for x in read(ledger).split() if x.startswith("G-")}
    return nums


def reserve_id():
    """잠금을 잡고 다음 번호를 장부에 적는다. 동시에 두 세션이 불러도 같은 번호가 나오지 않는다."""
    lock = os.path.join(common_dir(), "goal-ids.lock")
    for _ in range(100):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.time() - os.path.getmtime(lock) > 60:  # 죽은 잠금
                os.remove(lock)
            time.sleep(0.1)
    else:
        die("[goal-gate] 골 ID 잠금을 얻지 못했습니다.")
    try:
        import hindex  # D-/L-와 같은 원격 원자 예약(refs/vibe-ids/G-###) — push 안 한 다른 복제본과도 겹치지 않게
        cfg = vf_git.config()   # "remote": false(로컬 모드)면 claim·next_id처럼 원격 예약을 하지 않는다
        remote = ("origin" in git("remote").split() and cfg.get("remote", True) is not False
                  and hindex.icfg(cfg)["id_reserve"] == "remote")
        if remote:
            git("fetch", "-q", "origin")
        nums = all_known_ids() | (hindex.remote_reserved("G") if remote else set())
        n = max(nums | {0}) + 1
        if remote:
            empty = hindex.run_git(["hash-object", "-t", "tree", "-w", "--stdin"], "")
            for _ in range(20):
                c = git("commit-tree", empty, "-m", f"reserve G-{n:03d} by {vf_git.me()} {time.time()}")
                r = hindex.subprocess_push(c, f"G-{n:03d}")
                if r == "ok":
                    break
                if r != "taken":
                    die(f"[goal-gate] 원격 골 ID 예약 실패({r}) — 번호를 내주지 않습니다. 네트워크·권한을 확인하세요.\n"
                        "  원격 예약을 끄려면 .vibe-flow.json \"index\": {\"id_reserve\": \"scan\"}")
                n += 1
            else:
                die("[goal-gate] 원격 골 ID 예약 20회 충돌")
        gid = f"G-{n:03d}"
        with open(os.path.join(common_dir(), "goal-ids.txt"), "a", encoding="utf-8") as f:
            f.write(gid + "\n")
        return gid
    finally:
        os.close(fd)
        os.remove(lock)


def overlap():
    """지금 작업물과 다른 브랜치의 변경 파일이 겹치면 경고 (exit 0)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import vf_git
    cfg = vf_git.config()
    base = cfg["base"]
    mine = set(vf_git.changed_files(vf_git.base_tree(base), vf_git.snapshot()))
    cur = vf_git.current_branch()
    hits = 0
    for b in git("for-each-ref", "--format=%(refname:short)", "refs/heads").splitlines():
        if b in (cur, base):
            continue
        mb = git("merge-base", base, b)
        theirs = set(git("diff", "--name-only", mb, b).splitlines()) if mb else set()
        both = sorted(mine & theirs)
        if both:
            hits += 1
            print(f"[overlap] {b}: {', '.join(both[:5])}{' …' if len(both) > 5 else ''}")
    if not hits:
        print("[overlap] 겹치는 브랜치 없음")


def reverted_tree(sha):
    """HEAD에 <sha>의 정확한 역 패치를 적용한 트리. 임시 인덱스에서만 하고, 실패(루트 커밋·충돌·빈 diff)면 ""."""
    def run(args, env=None, inp=None):
        return subprocess.run(["git", *args], input=inp, capture_output=True, env=env)
    d = run(["-c", "diff.noprefix=false", "diff", "--binary", "--full-index", "--no-color", "--no-ext-diff",
             "--no-textconv", "--no-relative", sha, sha + "^"])   # 공백 무시 없음 — 바이트 그대로의 역
    if d.returncode or not d.stdout.strip():
        return ""
    tmp = tempfile.mkdtemp(prefix="vf-revert-")
    try:
        env = dict(os.environ, GIT_INDEX_FILE=os.path.join(tmp, "index"))
        if run(["read-tree", "HEAD"], env).returncode:
            return ""
        if run(["apply", "--cached", "--whitespace=nowarn", "-p1"], env, d.stdout).returncode:
            return ""
        t = run(["write-tree"], env)
        return t.stdout.decode().strip() if not t.returncode else ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def real_merge_or_revert(msg):
    """진짜 머지(훅 시점에 MERGE_HEAD 있음) 또는 진짜 되돌리기만 면제. 제목·본문 형식만으로는 안 된다.
    되돌리기 = 스테이징된 트리가 HEAD에 본문이 가리키는 커밋의 정확한 역을 적용한 트리와 같음.
    patch-id는 공백을 무시해(파이썬 들여쓰기) 쓰지 않는다. 루트 커밋·적용 실패는 면제 없음."""
    if os.path.exists(git("rev-parse", "--git-path", "MERGE_HEAD") or ".git/MERGE_HEAD"):
        return True
    m = re.search(r"^This reverts commit ([0-9a-f]{7,40})\b", msg, re.M)
    if not m or subprocess.run(["git", "cat-file", "-e", m.group(1) + "^{commit}"], capture_output=True).returncode:
        return False
    head = git("rev-parse", "-q", "--verify", "HEAD^{tree}")
    staged = subprocess.run(["git", "write-tree"], capture_output=True, text=True)   # 훅이 받은 GIT_INDEX_FILE 그대로
    expected = reverted_tree(m.group(1))
    return (bool(head) and not staged.returncode and bool(expected)
            and expected != head and staged.stdout.strip() == expected)


def check_commit(msg_file):
    msg = read(msg_file)
    if real_merge_or_revert(msg):
        return
    branch = git("symbolic-ref", "--short", "-q", "HEAD") or git("rev-parse", "--abbrev-ref", "HEAD")
    ids = set(ID_RE.findall(msg)) | set(ID_RE.findall(branch))
    goals = goal_files()
    staged = [f for f in git("diff", "--cached", "--name-only").splitlines() if f]
    if ids and staged and all(f.startswith(GOALS + "/") for f in staged):
        return  # 골 파일만 바꾸는 커밋(머지 뒤 base에서 status done 등)은 그 골이 비활성이어도 허용
    if not ids:
        die("[goal-gate] 골 ID(G-###)가 커밋 메시지나 브랜치에 없습니다.\n"
            "  이 변경이 어느 골의 일인지 정하세요. 맞는 골이 없으면:\n"
            "  1) python goal_gate.py candidate \"<제목>\" 로 후보를 쓰고\n"
            "  2) python goal_gate.py judge <후보.md> --apply 로 바깥눈 판정을 받으세요.\n"
            "  판정 전에는 커밋할 수 없습니다.")
    bad = []
    for gid in sorted(ids):
        p = goals.get(gid)
        if not p:
            bad.append(f"{gid}: 골 파일 없음")
        elif field(read(p), "status") != "active":
            bad.append(f"{gid}: 상태가 active가 아님 ({field(read(p), 'status') or '?'})")
    if bad:
        die("[goal-gate] " + "; ".join(bad))


HOOK_MARK = "# vibe-flow goal_gate hook v1"   # 우리 생성기만 쓰는 줄. 이 줄이 있어야 우리 훅
OLD_HOOKS = (  # 표식 이전에 생성하던 정확한 본문(업그레이드용). 스크립트 경로만 다를 수 있다
    re.compile(r'#!/bin/sh\nexec python "[^"\n]*goal_gate\.py" check-commit "\$1"\n'),
    re.compile(r'#!/bin/sh\nL="\$\(dirname "\$0"\)/commit-msg\.local"\n'
               r'if \[ -[xf] "\$L" \]; then "\$L" "\$@" \|\| exit \$\?; fi\n'
               r'exec python "[^"\n]*goal_gate\.py" check-commit "\$1"\n'),
)


def ours(text):
    """goal_gate.py라는 글자만으로는 안 된다 — 표식 줄이 있거나 예전 생성 본문과 정확히 같아야 우리 훅."""
    return HOOK_MARK in text.splitlines() or any(r.fullmatch(text) for r in OLD_HOOKS)


def install_hook():
    hooks = git("rev-parse", "--git-path", "hooks")
    if not hooks:
        die("git 레포가 아닙니다.")
    os.makedirs(hooks, exist_ok=True)
    script = os.path.abspath(__file__).replace("\\", "/")
    path = os.path.join(hooks, "commit-msg")
    local = path + ".local"
    if os.path.exists(path) and not ours(read(path)):  # 남의 훅: 지우지 않고 .local로 옮겨 먼저 실행
        if os.path.exists(local):
            die(f"[goal-gate] {path}와 {local}가 모두 있습니다. 덮어쓰지 않습니다 — 하나로 합친 뒤 다시 실행하세요.")
        live = os.name == "nt" or os.access(path, os.X_OK)   # Windows git은 실행 비트를 안 본다
        os.replace(path, local)
        print(f"기존 훅 보존: {local} " + ("(골 게이트보다 먼저 실행)" if live else
              "(실행 권한 없음 — git이 실행하지 않던 훅이라 연결하지 않음. chmod +x 하면 연결됨)"))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write('#!/bin/sh\n'
                f'{HOOK_MARK}\n'
                'L="$(dirname "$0")/commit-msg.local"\n'
                'if [ -x "$L" ]; then "$L" "$@" || exit $?; fi\n'   # git이 실행했을 훅만 (실행 권한 없는 건 건너뜀)
                f'exec python "{script}" check-commit "$1"\n')
    os.chmod(path, 0o755)
    print(path)


def slug(title):
    s = re.sub(r"[^\w가-힣-]+", "-", title).strip("-").lower()
    return s[:40] or "goal"


def candidate(title, found_in):
    os.makedirs(CANDS, exist_ok=True)
    p = os.path.join(CANDS, f"C-{TODAY.replace('-', '')}-{slug(title)}.md")
    if os.path.exists(p):
        die(f"이미 있음: {p}")
    with open(p, "w", encoding="utf-8") as f:
        f.write(CANDIDATE_TEMPLATE.format(title=title, found_in=found_in, date=TODAY))
    print(p)


def run_codex(prompt):
    with tempfile.TemporaryDirectory() as d:
        pf, of = os.path.join(d, "p.txt"), os.path.join(d, "o.txt")
        with open(pf, "w", encoding="utf-8") as f:
            f.write(prompt)
        with open(pf, encoding="utf-8") as stdin:
            r = subprocess.run(vf_git.codex_cmd(of), stdin=stdin,
                               capture_output=True, timeout=900, shell=(os.name == "nt"))
        if r.returncode != 0:   # 실패한 실행이 남긴 VERDICT는 판정으로 쓰지 않는다
            return ""
        return read(of) if os.path.exists(of) else ""


def active_goals_everywhere():
    """작업 트리 + 모든 로컬·원격 브랜치의 활성 골 {gid: (제목, 처음 본 브랜치 또는 '')}.
    다른 사람이 착수하며 올린 골도 판정 목록에 들어가야 같은 일이 새 골로 생기지 않는다."""
    out = {}
    for gid, p in goal_files().items():
        t = read(p)
        if field(t, "status") == "active":
            out[gid] = (t.splitlines()[0].lstrip("# "), "")
    for ref in git("for-each-ref", "--format=%(refname:short)", "refs/heads", "refs/remotes").splitlines():
        if ref.endswith("/HEAD"):
            continue
        for path in git("ls-tree", "--name-only", ref, GOALS + "/").splitlines():
            m = re.match(r"(G-\d{3,})", path.split("/")[-1])
            if not m or m.group(1) in out:
                continue
            t = git("show", f"{ref}:{path}")
            if field(t, "status") == "active":
                out[m.group(1)] = (t.splitlines()[0].lstrip("# "), ref)
    return dict(sorted(out.items()))


def add_goal_index_line(goal_path):
    """인덱스 구조(goals/INDEX.md에 vibe-index 표식)면 새 골 한 줄을 붙인다 — 골 파일과 같은 커밋에 들어간다."""
    idx = os.path.join(GOALS, "INDEX.md")
    if os.path.exists(idx) and "vibe-index: GOALS" in read(idx)[:300]:
        import hindex
        with open(idx, "a", encoding="utf-8", newline="\n") as f:
            f.write(hindex.goal_line(goal_path.replace("\\", "/")))


def judge(cand_path, apply):
    if not os.path.exists(NORTHSTAR):
        die(f"{NORTHSTAR}가 없습니다. 노스스타부터 작성하세요.")
    if vf_git.northstar_status(NORTHSTAR) == "draft":
        die(f"[goal-gate] {NORTHSTAR}가 초안(status: draft)입니다. 사용자가 확정(status: confirmed)해야 골을 판정할 수 있습니다.", 3)
    cand = read(cand_path)
    goals = goal_files()
    listing = "\n".join(f"- {gid}: {title}" + (f" (브랜치 {where}에서 진행 중)" if where else "")
                        for gid, (title, where) in active_goals_everywhere().items()) or "(없음)"
    prompt = JUDGE_PROMPT.format(northstar=vf_git.northstar_text(NORTHSTAR), goals=listing, candidate=cand)
    out = ""
    for _ in range(2):  # 판정 형식이 안 맞으면 1회만 재시도
        out = run_codex(prompt)
        if re.search(r"^VERDICT:\s*(CREATE|REJECT|MERGE\s+G-\d{3,})", out, re.M):
            break
    m = re.search(r"^VERDICT:\s*(CREATE|REJECT|MERGE\s+(G-\d{3,}))", out, re.M)
    reason = " ".join(re.findall(r"^REASON:\s*(.+)$", out, re.M)) or out.strip()[-400:]
    if not m:
        die("[goal-gate] 바깥눈 판정 불가 (2회). 후보는 candidate 상태로 두고 사용자에게 보고하세요.\n" + out[-800:], 2)
    verdict = m.group(1).split()[0]
    print(f"VERDICT: {m.group(1)}\nREASON: {reason}")
    if not apply:
        return
    title = cand.splitlines()[0].lstrip("# ").strip()
    body = cand.split("-->", 1)[1].strip() if "-->" in cand else cand
    if verdict == "CREATE":
        gid = reserve_id()
        p = os.path.join(GOALS, f"{gid}-{slug(title)}.md")
        with open(p, "w", encoding="utf-8") as f:
            f.write(GOAL_TEMPLATE.format(id=gid, title=title, date=TODAY,
                                         judge=f"codex {TODAY} CREATE — {reason}", body=body))
        os.remove(cand_path)
        add_goal_index_line(p)
        print(p)
    elif verdict == "REJECT":
        os.makedirs(REJECTED, exist_ok=True)
        dst = os.path.join(REJECTED, os.path.basename(cand_path))
        with open(dst, "w", encoding="utf-8") as f:
            f.write(cand.replace("status: candidate", f"status: rejected\njudge: codex {TODAY} REJECT — {reason}"))
        os.remove(cand_path)
        print(dst)
    else:  # MERGE: 기존 골의 완료 조건을 바꾸는 일은 범위 변경이라 자동 반영하지 않는다
        with open(cand_path, "w", encoding="utf-8") as f:
            f.write(cand.replace("status: candidate", f"status: merge-suggested {m.group(2)}\njudge: codex {TODAY} — {reason}"))
        print(f"{cand_path} (병합 제안: 사용자 확인 필요)")


def list_goals():
    for gid, p in goal_files().items():
        t = read(p)
        print(f"{gid}\t{field(t, 'status')}\t{t.splitlines()[0].lstrip('# ')}")
    if os.path.isdir(CANDS):
        for fn in sorted(os.listdir(CANDS)):
            t = read(os.path.join(CANDS, fn))
            print(f"후보\t{field(t, 'status')}\t{fn}")


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    a = sys.argv[1:]
    if any(x in ("-h", "--help") for x in a):   # 도움말 요청이 후보 제목·골 ID로 들어가지 않게
        print(__doc__)
        sys.exit(0)
    if a[:1] == ["install-hook"]:
        install_hook()
    elif a[:1] == ["check-commit"] and len(a) == 2:
        check_commit(a[1])
    elif a[:1] == ["candidate"] and len(a) >= 2:
        candidate(a[1], a[2] if len(a) > 2 else (git("symbolic-ref", "--short", "-q", "HEAD") or "?"))
    elif a[:1] == ["judge"] and len(a) >= 2:
        judge(a[1], "--apply" in a)
    elif a[:1] == ["list"]:
        list_goals()
    elif a[:1] == ["reserve-id"]:
        print(reserve_id())
    elif a[:1] == ["overlap"]:
        overlap()
    else:
        die(__doc__)
