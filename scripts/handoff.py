#!/usr/bin/env python3
"""vibe-flow ↔ 핸드오프 스킬(team-handoff / session-handoff) 연결. 레포 루트에서 실행.

  python handoff.py detect                         모드(team/personal)·핸드오프 폴더·읽을 순서
  python handoff.py precheck                       세션 시작 사전체크 (읽을 순서, 다른 참여자 변경, 착수 표시, 결정 대기, 후보)
  python handoff.py claim G-### "<할 일>" <브랜치> [--no-push]
                                                   선점: fetch → 중복 검사 → 브랜치 → REMAINING 착수 줄 커밋 → push
  python handoff.py check-record [--commit <sha>]  완료 기록 검사: 그 커밋(기본 HEAD)에 작업 + WORKLOG·INDEX·REMAINING
                                                   + MR 본문(<핸드오프>/mr/G-###.md)·QA 실행 기록(G-###-qa.json: tree·cmd·
                                                   exit 0, tree = MR 「QA 결과」 대상)·리뷰 원문(G-###-review.md, VERDICT 줄)이
                                                   함께 있어야 한다. 골 작업은 QA 뒤 기록을 마지막 작업 커밋에 amend로 합친다
  python handoff.py export-evidence G-###          .vibe/mr-G-###.md·.vibe/qa/<QA 대상 tree>.json·이 골의 .vibe/review/
                                                   d*·r*.txt → <핸드오프>/mr/G-###.md·-qa.json·-review.md (기록 전에)
  원격이 없거나 .vibe-flow.json "remote": false면 로컬 모드 — claim은 로컬 커밋만 한다

인덱스 구조(docs/structure.md 「인덱스 계층」 — 대형 프로젝트):
  python handoff.py migrate                        예전 구조 → 진입 INDEX + 문서별 INDEX + 본문(원본 스냅숏 .vibe/migrate/<시각>/)
  python handoff.py verify-migration <스냅숏 폴더> [--base <ref>]
                                                   무손실 검증 + 읽기량 이전/이후. --base: 원본이 커밋된 곳(기본 HEAD)
  python handoff.py archive [--dry]                완료 항목·오래된 INDEX 줄·임계값 넘은 본문 이동(링크 유지)
  python handoff.py lint                           INDEX↔본문 불일치·끊긴 링크·임계값·완료 잔존 (오류면 종료코드 1)
  python handoff.py next-id D|L [--scan-only]      결정·교훈 번호 발급(전 브랜치 스캔 + 원격 원자 예약). --scan-only는 사용자 직접 우회

형식은 docs/structure.md. 팀 모드는 작성자(@git user.name)가 필수다.
"""
import datetime
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vf_git  # noqa: E402
import hindex  # noqa: E402
import qa_run  # noqa: E402

ID_RE = re.compile(r"\bG-\d{3,}\b")
TODAY = datetime.date.today().isoformat()
READ_ORDER = {"team": ["PLAN.md", "REMAINING.md", "DECISIONS.md", "LESSONS.md", "WORKLOG/INDEX.md"],
              "personal": ["PLAN.md", "REMAINING.md", "LESSONS.md", "WORKLOG/INDEX.md", "WORKLOG.md"]}


def die(msg, code=1):
    print(msg, file=sys.stderr)
    sys.exit(code)


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def write(p, text):
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def has_id(gid, text):
    """골 ID 경계 일치 (G-123이 G-1234·G-123abc에 걸리지 않게. proto/G-123-x는 일치)."""
    return re.search(rf"\b{re.escape(gid)}(?![0-9A-Za-z])", text) is not None


def goal_file_names(goals, gid):
    return [fn for fn in os.listdir(goals) if re.match(rf"{re.escape(gid)}(?![0-9A-Za-z])", fn)]


def has_remote(cfg=None):
    """원격 모드인가: origin이 있고 .vibe-flow.json "remote"가 false가 아니다. 아니면 로컬 모드(push 안 함)."""
    if (cfg or {}).get("remote", True) is False:
        return False
    return "origin" in vf_git.git("remote").split()


# ---------- detect ----------
def detect(cfg):
    mode, hdir = vf_git.handoff_mode(cfg)
    if hindex.is_indexed(cfg):  # 인덱스 구조: INDEX만 읽는다
        return mode, hdir, hindex.start_set(cfg)
    order = [f"{hdir}/{x}" for x in READ_ORDER[mode] if os.path.exists(f"{hdir}/{x}")]
    return mode, hdir, order


# ---------- precheck ----------
def last_own_record(hdir, me):
    """내가 마지막으로 핸드오프 폴더를 바꾼 시각 (epoch, 없으면 None).
    날짜만 쓰면 git이 '그날 지금 시각'으로 해석해 오늘 앞선 다른 사람 변경을 놓친다."""
    out = vf_git.git("log", "-1", "--all", f"--author={me}", "--format=%ct", "--", hdir)
    return out or None


def precheck(cfg):
    import dupe
    mode, hdir, order = detect(cfg)
    me = vf_git.me()
    print(f"[precheck] 모드: {mode} · 원격: {'있음 — git pull 먼저' if has_remote(cfg) else '없음(로컬 모드 — pull 생략)'} · 폴더: {hdir} · 나: @{me}")
    if mode == "team" and has_remote(cfg):
        vf_git.git("fetch", "-q", "origin")
        behind = vf_git.git("rev-list", "--count", f"HEAD..origin/{cfg['base']}")
        if behind and behind != "0":
            print(f"[precheck] origin/{cfg['base']}보다 {behind}커밋 뒤 — git pull --rebase 먼저")
    print("[precheck] 읽을 순서:", " → ".join(order) or "(핸드오프 문서 없음 — 초기화 필요)")
    total = hindex.chars(order)
    if hindex.is_indexed(cfg):
        budget = hindex.icfg(cfg)["start_budget"]
        print(f"[precheck] 시작 읽기량 {total}자 / 목표 {budget}자" + (" — 넘음: handoff.py archive" if total > budget else "")
              + "".join(f"\n  {len(hindex.rd(p)):>6}자 {p}" for p in order))
        print("[precheck] 본문은 INDEX에서 고른 것만. 결정은 탐색 단계에서 작업이 닿는 태그로: grep \"#<화면ID>\" " + f"{hdir}/DECISIONS.md")
    else:
        print(f"[precheck] 시작 읽기량 {total}자 (예전 구조 — 큰 프로젝트면 handoff.py migrate)")
    since = last_own_record(hdir, me)
    if mode == "team":
        args = ["log", "--format=%an|%ad|%s", "--date=format:%Y-%m-%d %H:%M"]
        if since:
            args.append(f"--since=@{since}")
        args += ["--all", "--", hdir]
        others = {}
        for line in vf_git.git(*args).splitlines():
            who, date, subj = (line.split("|", 2) + ["", ""])[:3]
            if who != me:
                others.setdefault(who, []).append(f"{date} {subj}")
        when = datetime.datetime.fromtimestamp(int(since)).strftime("%Y-%m-%d %H:%M") if since else "처음"
        print(f"[precheck] 내 마지막 기록({when}) 이후 다른 참여자 변경:" + ("" if others else " 없음"))
        for who, items in others.items():
            print(f"  @{who}: {len(items)}건 — 최근: {items[0]}")
    today = datetime.date.today()
    days = cfg.get("claim_days", 7)
    cl = dupe.claims(cfg)
    active = [c for c in cl if (today - datetime.date.fromisoformat(c[3])).days <= days]
    stale = [c for c in cl if c not in active]
    print(f"[precheck] 착수 중 ({days}일 이내): " + ("없음" if not active else ""))
    for ids, task, who, date, src in active:
        print(f"  [~] {task} @{who} {date} ({src})")
    for ids, task, who, date, src in stale:
        print(f"  [~ 만료] {task} @{who} {date} — 다시 집을 수 있음")
    rem = f"{hdir}/REMAINING.md"
    if os.path.exists(rem):
        pend = [l.strip() for l in read(rem).splitlines() if re.match(r"^\s*-\s*\[ \]\s*결정", l)]
        held = [l.strip() for l in read(rem).splitlines() if "보류" in l and re.match(r"^\s*-\s*\[[ ~]\]", l)]
        print(f"[precheck] 결정 대기 {len(pend)}건" + "".join(f"\n  {x[:120]}" for x in pend[:5]))
        if held:
            print(f"[precheck] 보류 {len(held)}건" + "".join(f"\n  {x[:120]}" for x in held[:5]))
    cands = dupe.candidate_titles(cfg)
    print(f"[precheck] 열린 골 후보 {len(cands)}건" + "".join(f"\n  {fn}: {t}" for fn, t in cands[:5]))
    ns = vf_git.paths(cfg)["northstar"]
    if not os.path.exists(ns):
        print(f"[precheck] 노스스타 없음 ({ns}) — 골을 만들 수 없음")
    elif vf_git.northstar_status(ns) == "draft":
        print(f"[precheck] 노스스타가 초안 — 사용자 확정 전에는 골 판정 불가")


# ---------- claim ----------
def claim_line(gid, task, me, branch):
    return f"- [~] {gid} {task} (착수 @{me} {TODAY}) → {branch}"


def add_claim(rem_path, gid, task, me, branch):
    text = read(rem_path) if os.path.exists(rem_path) else "# 남은 업무\n"
    lines = text.splitlines()
    pat = re.compile(rf"^(\s*)-\s*\[ \]\s*(.*\b{re.escape(gid)}\b.*)$")
    for i, l in enumerate(lines):
        m = pat.match(l)
        if m:  # 이미 있는 할 일을 착수로 바꾼다 (다른 참여자 항목 내용은 그대로, 표시만 변경)
            lines[i] = f"{m.group(1)}- [~] {m.group(2)} (착수 @{me} {TODAY}) → {branch}"
            write(rem_path, "\n".join(lines) + "\n")
            return "changed"
    if "## 착수 중" not in text:
        text = text.rstrip("\n") + "\n\n## 착수 중\n"
    text = text.rstrip("\n") + "\n" + claim_line(gid, task, me, branch) + "\n"
    write(rem_path, text)
    return "added"


def claim(cfg, gid, task, branch, push=True):
    import dupe
    mode, hdir, _ = detect(cfg)
    me = vf_git.me()
    if not ID_RE.fullmatch(gid):
        die(f"[claim] 골 ID 형식이 아님: {gid}")
    if not has_id(gid, branch):
        die(f"[claim] 브랜치 이름에 골 ID가 없음: {branch}")
    pre = cfg.get("branch_prefixes") or []
    if pre and branch.split("/")[0] not in pre:
        die(f"[claim] 브랜치 접두사 규칙 위반: {branch} (허용: {'|'.join(pre)})")
    goals = vf_git.paths(cfg)["goals"]
    gfs = goal_file_names(goals, gid) if os.path.isdir(goals) else []
    if not gfs:
        die(f"[claim] {gid} 골 파일이 {goals}에 없음 — candidate → judge 먼저")
    st = hindex.field(read(f"{goals}/{gfs[0]}"), "status")  # goal_gate.field()와 같은 규칙: 파일 어디든 첫 'status:' 줄
    if st != "active":
        die(f"[claim] {gid} 골 상태가 active가 아님 ({st or '?'})")
    local = not has_remote(cfg)   # 로컬 모드: 원격이 없거나 "remote": false — push 대상이 없다
    remote = not local and push   # 원격이 있으면 push 필수. 건너뛰는 것은 사용자가 준 --no-push뿐
    for attempt in range(2):
        if remote:
            vf_git.git("fetch", "-q", "origin")
            if vf_git.git("rev-parse", "--verify", "-q", f"origin/{branch}"):
                die(f"[claim] 원격에 같은 브랜치 {branch}가 이미 있음 — 다른 사람이 선점함")
        body = f"## 골\n{gid}\n## 사용자 가치\n{task}\n"
        blocks, warns = dupe.find(body, cfg)
        for w in warns:
            print("[claim] 경고:", w)
        if blocks:
            die("[claim] 중복으로 선점 중단:\n  " + "\n  ".join(blocks))
        if attempt == 0:
            start = f"origin/{cfg['base']}" if remote else cfg["base"]
            if vf_git.current_branch() != branch:
                r = vf_git.git("checkout", "-q", "-b", branch, start)
                if vf_git.current_branch() != branch:
                    die(f"[claim] 브랜치를 만들지 못함: {branch} {r}")
            rem = f"{hdir}/REMAINING.md"
            add_claim(rem, gid, task, me, branch)
            # judge가 방금 만든 골 파일(아직 커밋 안 됨)도 함께 올려야 다른 참여자가 이 골을 본다
            own = [rem] + [f"{goals}/{fn}" for fn in goal_file_names(goals, gid)]
            vf_git.git("add", "--", *own)
            # 경로를 지정해 커밋: 미리 staged된 다른 변경은 섞지 않고 staged 그대로 둔다
            c = subprocess.run(["git", "commit", "-q", "-m", f"{gid} 착수: {task}", "--", *own],
                               capture_output=True, text=True, encoding="utf-8")
            if c.returncode:
                die(f"[claim] 선점 커밋 실패 (훅 거부 등) — push하지 않음:\n{(c.stdout + c.stderr).strip()}")
        if not remote:
            at = f"{branch}@{vf_git.git('rev-parse', '--short', 'HEAD')}"
            print(f"[claim] 선점(로컬 모드 — 원격 없음): {at}" if local
                  else f"[claim] 선점 커밋 완료 (--no-push — 사용자 지시, push 안 함): {at}")
            return
        r = vf_git.git("push", "-q", "-u", "origin", branch)
        if vf_git.git("rev-parse", "--verify", "-q", f"origin/{branch}"):
            vf_git.git("fetch", "-q", "origin")
            if vf_git.git("rev-parse", f"origin/{branch}") == vf_git.git("rev-parse", "HEAD"):
                print(f"[claim] 선점 완료 — push 확인됨: origin/{branch}. 이제 탐색을 시작해도 된다")
                return
        print("[claim] push 거부 — 최신으로 갱신하고 중복을 다시 검사합니다")
        vf_git.git("pull", "-q", "--rebase", "origin", cfg["base"])
    die("[claim] push가 두 번 실패 — 사용자에게 보고하세요")


# ---------- check-record ----------
MR_SECTIONS = ("리뷰 기록", "QA 결과")


def mr_file_missing(hdir, gids, files, hi):
    """검증 증거: 기록 커밋에 <핸드오프>/mr/G-###.md(MR 본문)가 있어야 한다 — .vibe/는 추적 안 되어 제3자가 못 본다.
    핸드오프 폴더 안이라 QA 대상 비교(mr_check)와 작업 파일 판정에서 기록으로 빠진다."""
    miss = []
    for g in gids:
        if g == "G-000":  # 동작 불변 변경(오타·규칙 문서 한 줄)은 골 MR·리뷰·QA 기록이 없다
            continue
        p = f"{hdir}/mr/{g}.md"
        if p not in files:
            miss.append(f"MR 본문 {p}가 이 커밋에 없음 — .vibe/mr-{g}.md를 복사해 기록과 같은 커밋에 넣는다")
            continue
        t = vf_git.git("show", f"{hi}:{p}")
        if not has_id(g, t):
            miss.append(f"{p}에 골 ID {g} 없음")
        for name in MR_SECTIONS:
            m = re.search(rf"^##\s+{name}\s*$(.*?)(?=^##\s|\Z)", t, re.M | re.S)
            body = re.sub(r"<!--.*?-->|\(진행 전\)|<[^>\n]+>", "", m.group(1), flags=re.S) if m else ""
            if not re.search(r"\w", body):
                miss.append(f"{p}의 「{name}」이 없거나 비어 있음")
        miss += qa_record_missing(hdir, g, files, hi, t)
        miss += review_record_missing(hdir, g, files, hi)
    return miss


def qa_target(mr_text):
    """MR 「QA 결과」의 대상 commit/tree sha(없으면 '')."""
    m = re.search(r"^##\s+QA 결과\s*$(.*?)(?=^##\s|\Z)", mr_text, re.M | re.S)
    t = re.search(qa_run.TARGET, m.group(1)) if m else None
    return t.group(1) if t else ""


def review_record_missing(hdir, g, files, hi):
    """리뷰 원문: .vibe/review/는 추적 안 된다 — 기록 커밋에 <핸드오프>/mr/G-###-review.md(VERDICT 줄 포함)."""
    q = f"{hdir}/mr/{g}-review.md"
    if q not in files:
        return [f"리뷰 원문 {q}가 이 커밋에 없음 — python handoff.py export-evidence {g}"]
    if not re.search(r"^VERDICT:", vf_git.git("show", f"{hi}:{q}"), re.M):
        return [f"{q}에 VERDICT: 줄 없음 — 설계 확인·리뷰 원문이 아님(export-evidence {g})"]
    return []


def qa_record_missing(hdir, g, files, hi, mr_text=""):
    """QA 실행 기록: 기록 커밋에 <핸드오프>/mr/G-###-qa.json(qa_run.py가 만든 .vibe/qa/<tree>.json 사본)이 exit 0으로,
    tree가 커밋된 MR 「QA 결과」의 대상 tree(대상 commit이면 그 tree)와 같아야 한다."""
    q = f"{hdir}/mr/{g}-qa.json"
    if q not in files:
        return [f"QA 실행 기록 {q}가 이 커밋에 없음 — qa_run.py가 남긴 .vibe/qa/<tree>.json을 복사해 같은 커밋에 넣는다"]
    try:
        rec = json.loads(vf_git.git("show", f"{hi}:{q}"))
    except ValueError:
        return [f"{q}가 JSON이 아님 — .vibe/qa/<tree>.json을 그대로 복사한다"]
    if not isinstance(rec, dict) or any(k not in rec for k in ("tree", "cmd", "exit")):
        return [f"{q}에 tree·cmd·exit 없음 — qa_run.py 기록이 아님(export-evidence {g})"]
    if rec["exit"] != 0:
        return [f"{q}는 exit {rec['exit']} — 통과한 QA 실행 기록이 아님"]
    tgt = qa_target(mr_text)
    if not tgt:
        return [f"{hdir}/mr/{g}.md 「QA 결과」에 대상 commit/tree 없음 — {q}와 대조할 수 없음"]
    rt = str(rec["tree"])
    if not any(c and len(c) >= 7 and rt.startswith(c) for c in (tgt, vf_git.tree_of(tgt))):
        return [f"{q}의 tree({rt[:12]})가 MR 「QA 결과」 대상({tgt[:12]})과 다름 — 다른 작업물의 실행 기록"]
    return []


def export_evidence(cfg, g):
    """기록 커밋에 넣을 검증 증거를 .vibe/에서 <핸드오프>/mr/로 옮긴다: MR 본문, QA 실행 기록, 이 골의 리뷰 원문."""
    if not re.fullmatch(r"G-\d{3,}", g):
        die(f"[export-evidence] 골 ID가 아님: {g}")
    _, hdir, _ = detect(cfg)
    mr_src = os.path.join(".vibe", f"mr-{g}.md")
    if not os.path.exists(mr_src):
        die(f"[export-evidence] MR 본문 {mr_src} 없음")
    mr = read(mr_src)
    tgt = qa_target(mr)
    tree = vf_git.tree_of(tgt) if tgt else ""
    tree = tree or tgt
    qa_src = qa_run.record_path(tree) if tree else ""
    if not qa_src or not os.path.exists(qa_src):
        cands = [f for f in os.listdir(qa_run.QA_DIR) if f.startswith(tree) and f.endswith(".json")] \
            if tree and os.path.isdir(qa_run.QA_DIR) else []
        if len(cands) != 1:
            die(f"[export-evidence] QA 실행 기록 {qa_src or '.vibe/qa/<tree>.json'} 없음 — 「QA 결과」 대상 확인, python qa_run.py --mr {mr_src}")
        qa_src = os.path.join(qa_run.QA_DIR, cands[0])
    d = os.path.join(".vibe", "review")
    parts = []
    names = sorted(os.listdir(d)) if os.path.isdir(d) else []
    for kind, stamp in (("d", ".meta"), ("r", ".tree")):
        for n in sorted((x for x in names if re.fullmatch(rf"{kind}\d+\.txt", x)), key=lambda x: int(x[1:-4])):
            sp = os.path.join(d, n[:-4] + stamp)
            goal = re.search(r"^goal:\s*(G-\d+)\s*$", read(sp), re.M) if os.path.exists(sp) else None
            if goal and goal.group(1) == g:
                head = f"## {n} ({'설계 확인' if kind == 'd' else '코드 리뷰'})"
                parts.append(f"{head}\n\n````text\n{read(os.path.join(d, n)).rstrip()}\n````\n")
    if not parts:
        die(f"[export-evidence] .vibe/review/에 {g}의 d*·r*.txt 기록 없음 — review.py로 받은 원문이 있어야 한다")
    os.makedirs(f"{hdir}/mr", exist_ok=True)
    write(f"{hdir}/mr/{g}.md", mr)
    write(f"{hdir}/mr/{g}-qa.json", read(qa_src))
    write(f"{hdir}/mr/{g}-review.md", f"# {g} 리뷰 원문 (.vibe/review/ 사본, export-evidence)\n\n" + "\n".join(parts))
    print(f"[export-evidence] {hdir}/mr/{g}.md · {g}-qa.json (← {qa_src}) · {g}-review.md ({len(parts)}개 원문) — 기록 커밋에 넣는다")


def check_record(cfg, commit=None):
    """기록 검사: 한 커밋(기본 HEAD)에 작업 변경과 핸드오프 기록이 함께 있어야 한다.
    골 작업은 QA 결과를 보고 기록하므로, QA 뒤 기록을 마지막 작업 커밋에 합친다(git commit --amend).
    --commit <sha>면 골 ID는 그 커밋 메시지에서만 — 지금 브랜치 이름은 그 커밋과 무관할 수 있다."""
    branch = "" if commit else vf_git.current_branch()
    commit = commit or "HEAD"
    mode, hdir, _ = detect(cfg)
    me = vf_git.me()
    goals_dir = vf_git.paths(cfg)["goals"]
    lo, hi, label = f"{commit}^", commit, vf_git.git("rev-parse", "--short", commit)
    msg = vf_git.git("log", "-1", "--format=%s%n%b", commit)
    files = vf_git.git("diff", "--name-only", lo, hi).splitlines()
    gids = sorted(set(ID_RE.findall(msg)) | set(ID_RE.findall(branch)))
    miss = []
    work = [f for f in files if not f.startswith(hdir + "/") and not f.startswith(goals_dir + "/")]
    if not work:
        miss.append(f"{label}에 작업 파일 변경이 없음 — 기록은 작업과 같은 커밋에 넣는다(골 작업은 QA 뒤 git commit --amend로 합친다)")
    if not gids:
        miss.append("커밋 메시지·브랜치에 골 ID 없음" if branch else "커밋 메시지에 골 ID 없음")

    def added(path):
        diff = vf_git.git("diff", lo, hi, "--", path)
        return [l[1:] for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]

    if mode == "team":
        topic = [f for f in files if f.startswith(f"{hdir}/WORKLOG/") and not f.endswith("INDEX.md")]
        heads = [l for f in topic for l in added(f) if l.startswith("## ")]
        if not heads:
            miss.append(f"WORKLOG 토픽 파일({hdir}/WORKLOG/<topic>.md)에 새 항목 없음")
        else:
            h = heads[-1]
            if f"@{me}" not in h:
                miss.append(f"WORKLOG 항목 제목에 @{me} 없음")
            if not re.search(rf"\{{#[^}}]*-{re.escape(me)}\}}", h):
                miss.append(f"WORKLOG anchor가 -{me}로 끝나지 않음")
            if gids and not any(has_id(g, h) for g in gids):
                miss.append("WORKLOG 항목 제목에 골 ID 없음")
        idx = [l for l in added(f"{hdir}/WORKLOG/INDEX.md") if l.startswith("- ")]
        if not idx:
            miss.append("WORKLOG/INDEX.md에 한 줄 추가 없음")
        elif not (f"@{me}" in idx[-1] and any(has_id(g, idx[-1]) for g in gids)):
            miss.append(f"INDEX 줄에 @{me}와 골 ID가 함께 있어야 함")
    else:
        wl = [f for f in files if f.startswith(f"{hdir}/WORKLOG")]
        if not wl:
            miss.append(f"{hdir}/WORKLOG 기록 없음")
    rem_added = added(f"{hdir}/REMAINING.md")
    done = [l for l in rem_added if re.match(r"^\s*-\s*\[x\]", l) and any(has_id(g, l) for g in gids)]
    if not done:
        miss.append("REMAINING에 이 골의 [x] 완료 줄 없음")
    elif mode == "team" and f"@{me}" not in done[-1]:
        miss.append(f"REMAINING 완료 줄에 (@{me} 날짜) 없음")
    rem_now = vf_git.git("show", f"{hi}:{hdir}/REMAINING.md")
    left = [l for l in rem_now.splitlines() if re.match(r"^\s*-\s*\[~\]", l) and any(has_id(g, l) for g in gids)
            and f"@{me}" in l]
    if left:
        miss.append("내 착수 표시 [~]가 아직 남아 있음 — [x]로 바꿔야 함")
    miss += mr_file_missing(hdir, gids, files, hi)
    if hindex.is_indexed(cfg):
        miss += hindex.missing_index_lines(cfg, files, added, lo, hi)
    if miss:
        print("[check-record] 통과 못 함")
        for x in miss:
            print(" -", x)
        sys.exit(1)
    print(f"[check-record] 통과 — {label}: 작업 {len(work)}개 파일 + 핸드오프 기록")


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    a = sys.argv[1:]
    cfg = vf_git.config()
    if a[:1] == ["detect"]:
        m, d, o = detect(cfg)
        print(f"mode={m} dir={d}\nread: {' → '.join(o)}")
    elif a[:1] == ["precheck"]:
        precheck(cfg)
    elif a[:1] == ["claim"] and len(a) >= 4:
        claim(cfg, a[1], a[2], a[3], push="--no-push" not in a)
    elif a[:1] == ["check-record"]:
        check_record(cfg, a[2] if len(a) > 2 and a[1] == "--commit" else None)
    elif a[:1] == ["export-evidence"] and len(a) == 2:
        export_evidence(cfg, a[1])
    elif a[:1] == ["migrate"]:
        snap, made = hindex.migrate(cfg)
        print(f"[migrate] 완료 — 스냅숏 {snap}\n  " + "\n  ".join(made))
        print(f"[migrate] 다음: python handoff.py verify-migration {snap}")
    elif a[:1] == ["verify-migration"] and len(a) in (2, 4):
        ok, rep = hindex.verify(a[1], a[3] if len(a) == 4 and a[2] == "--base" else "HEAD")
        print("\n".join(rep))
        before, after = hindex.before_after(a[1], cfg)
        print(f"[verify] 세션 시작 읽기량: 이전 {before}자 → 이후 {after}자")
        print("[verify] " + ("무손실 — 통과" if ok else "불일치 있음"))
        sys.exit(0 if ok else 1)
    elif a[:1] == ["archive"]:
        acts = hindex.archive(cfg, dry="--dry" in a)
        print("[archive] " + ("할 일 없음" if not acts else ("(--dry) " if "--dry" in a else "") + "\n  ".join([""] + acts)))
    elif a[:1] == ["lint"]:
        err, warn = hindex.lint(cfg)
        for x in err:
            print("오류:", x)
        for x in warn:
            print("경고:", x)
        print(f"[lint] 오류 {len(err)} · 경고 {len(warn)}")
        sys.exit(1 if err else 0)
    elif a[:1] == ["next-id"] and len(a) >= 2 and a[1] in ("D", "L"):
        ident, hint = hindex.next_id(a[1], cfg, scan_only="--scan-only" in a)
        print(ident)
        print(f"[next-id] {hint}", file=sys.stderr)
    else:
        die(__doc__)
