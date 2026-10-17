#!/usr/bin/env python3
"""vibe-flow ↔ 핸드오프 스킬(team-handoff / session-handoff) 연결. 레포 루트에서 실행.

  python handoff.py detect                         모드(team/personal)·핸드오프 폴더·읽을 순서
  python handoff.py precheck [--run-tests]         세션 시작 사전체크 (읽을 순서, 다른 참여자 변경, 착수 표시, 결정 대기, 후보)
                                                   + 착수 가능성(git·python(python·python3·py)·codex PATH, test_cmd — --run-tests면 실행).
                                                   git·python·codex·test_cmd가 없거나 추적 파일에 커밋 안 된 변경이 있으면 '착수 불가', 종료코드 1
  python handoff.py claim G-### "<할 일>" <브랜치> [--no-push]
                                                   선점: fetch → 중복 검사 → 브랜치 → REMAINING 착수 줄 커밋 → push
  python handoff.py check-record [--commit <sha>]  완료 기록 검사: 그 커밋(기본 HEAD)에 작업 + WORKLOG·INDEX·REMAINING
                                                   + MR 본문(<핸드오프>/mr/G-###.md)·QA 실행 기록(G-###-qa.json: tree·cmd·
                                                   exit 0, tree = MR 「QA 결과」 대상)·리뷰 원문(G-###-review.md, VERDICT 줄)이
                                                   함께 있어야 한다. 골 작업은 QA 뒤 기록을 마지막 작업 커밋에 amend로 합친다
  python handoff.py export-evidence G-###          .vibe/mr-G-###.md·.vibe/qa/<QA 대상 tree>.json·이 골의 .vibe/review/
                                                   d*·r*.txt → <핸드오프>/mr/G-###.md·-qa.json·-review.md (기록 전에).
                                                   「골」이 여럿이면 골마다 쓴다. 리뷰 원문은 도장(goal·branch·base)이
                                                   이 MR 골·지금 브랜치·지금 기준과 같은 회차만
  python handoff.py verify-evidence [G-###] [--commit <sha>]
                                                   새 clone 재검증: 그 커밋(기본 HEAD)의 추적 파일만으로(.vibe/ 안 씀)
                                                   MR 사본·리뷰 원문(전 회차 지적 장부)·QA 기록·QA 뒤 코드 변경을 PASS/FAIL로.
                                                   QA tree 객체가 없으면(amend 전 tree) 커밋에서 재구성해 비교. 실패면 1
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
import posixpath
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


def readiness(cfg, run_tests=False):
    """착수 가능성: git·python·codex가 PATH에 있는가, test_cmd가 있는가(--run-tests면 실제로 돌린다).
    git·python(스크립트)·codex(골 판정·설계 확인·리뷰 — 면제 없음)·test_cmd(QA)가 없거나, 추적 파일에 커밋 안 된 변경이 있으면
    (QA tree·리뷰 대상이 섞인다) 끝까지 갈 수 없다 — 착수 불가, 종료코드 1."""
    import shutil
    tools = {"git": shutil.which("git"), "python": shutil.which("python") or shutil.which("python3") or shutil.which("py"),
             "codex": shutil.which("codex")}
    cmd = (cfg.get("test_cmd") or "").strip()
    print("[precheck] 착수 가능성: " + " · ".join(f"{k} {'있음' if v else '없음'}" for k, v in tools.items())
          + f" · test_cmd {'있음' if cmd else '없음'}")
    head = tools["git"] and vf_git.git("rev-parse", "--verify", "-q", "HEAD")
    dirty = [f for f in vf_git.git("diff", "--name-only", "HEAD").splitlines() if f] if head else []   # 스테이지 포함, 미추적 제외
    block = [f"커밋 안 된 변경 {len(dirty)}개({', '.join(dirty[:5])}{' …' if len(dirty) > 5 else ''}) — 커밋하거나 stash 먼저"
             ] if dirty else []
    block += [f"{k} 없음(PATH)" for k in ("git", "python", "codex") if not tools[k]]
    if not cmd:
        block.append("test_cmd 없음(.vibe-flow.json — 자동 테스트가 없으면 syntax_check.py)")
    if cmd and not run_tests:
        print("[precheck] 기준 테스트: 미실행 (--run-tests로 돌린다)")
    elif cmd:
        r = subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[precheck] 기준 테스트: {'통과' if r.returncode == 0 else '실패'} (exit {r.returncode})")
        if r.returncode:
            block.append(f"기준 테스트가 이미 실패(exit {r.returncode}) — 시작 전에 사용자에게 알린다")
    if block:
        print("[precheck] 착수 불가: " + " · ".join(block))
        return 1
    return 0


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
    return qa_run.target(m.group(1)) if m else ""   # 안내 주석 안의 예시 sha는 대상이 아니다


def review_record_missing(hdir, g, files, hi):
    """리뷰 원문: .vibe/review/는 추적 안 된다 — 기록 커밋에 <핸드오프>/mr/G-###-review.md(VERDICT 줄 포함)."""
    q = f"{hdir}/mr/{g}-review.md"
    if q not in files:
        return [f"리뷰 원문 {q}가 이 커밋에 없음 — python handoff.py export-evidence {g}"]
    if not re.search(r"^VERDICT:", vf_git.git("show", f"{hi}:{q}"), re.M):
        return [f"{q}에 VERDICT: 줄 없음 — 설계 확인·리뷰 원문이 아님(export-evidence {g})"]
    return []


def qa_ok(rec):
    """통과한 QA 기록인가(qa_run.ok): exit 0, ok false 아님, 전부 건너뜀 아님."""
    return qa_run.ok(rec)


QA_SEC = re.compile(r"^(##\s+QA 결과\s*\n)(.*?)(?=^##\s|\Z)", re.M | re.S)


def export_captures(mr, g, hdir):
    """「QA 결과」의 로컬 이미지·영상 링크(레포 루트 기준)를 <hdir>/mr/<g>-evidence/<이름>으로 복사하고 사본 MR 폴더 기준
    상대 경로로 바꾼 본문. .vibe/qa/는 추적 안 된다 — 새 clone에서도 캡처가 남게. (바꾼 본문, 복사한 수, 못 찾은 경로)."""
    import shutil
    sec = QA_SEC.search(mr)
    if not sec:
        return mr, 0, []
    names, miss = {}, []

    def sub(m):
        if m.group(0).startswith("<!--"):
            return m.group(0)
        src = qa_run.local_link(m)
        if not src or not qa_run.is_media(src) or src.startswith(f"{g}-evidence/"):
            return m.group(0)
        if not os.path.isfile(src):
            miss.append(src)
            return m.group(0)
        base, key = os.path.basename(src), os.path.normcase(os.path.abspath(src))
        while base in names and names[base] != key:   # 다른 폴더의 같은 이름
            base = "_" + base
        names[base] = key
        os.makedirs(f"{hdir}/mr/{g}-evidence", exist_ok=True)
        shutil.copyfile(src, f"{hdir}/mr/{g}-evidence/{base}")
        new = f"{g}-evidence/{base}"
        i = 1 if m.group(1) is not None else 2
        if i == 2 and " " in new:
            new = f"<{new}>"
        t = m.group(0)
        return t[:m.start(i) - m.start(0)] + new + t[m.end(i) - m.start(0):]

    body = re.sub(r"<!--.*?-->|" + qa_run.LINK_RE.pattern, sub, sec.group(2), flags=re.S)
    return mr[:sec.start(2)] + body + mr[sec.end(2):], len(names), miss


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
    if not qa_ok(rec):
        return [f"{q}는 통과가 아님(전부 건너뜀·ok false) — 건너뛰지 않고 돌아가게 고쳐 qa_run.py"]
    try:   # 테스트 명령은 그 커밋의 .vibe-flow.json으로 — 다른 명령의 통과 기록은 증거가 아니다(verify-evidence와 같다)
        ccfg = json.loads(vf_git.git("show", f"{hi}:.vibe-flow.json")) if vf_git.obj_type(f"{hi}:.vibe-flow.json") == "blob" else {}
    except ValueError:
        return [f"{hi}의 .vibe-flow.json이 JSON이 아님 — {q}의 cmd와 대조할 수 없음"]
    want = (ccfg.get("test_cmd") or "").strip() if isinstance(ccfg, dict) else ""
    if not want and isinstance(ccfg, dict) and vf_git.obj_type(f"{hi}:.vibe-flow.json") == "blob":
        return [f"커밋된 설정에 test_cmd 없음 — {q}의 cmd를 대조할 수 없음(.vibe-flow.json에 test_cmd를 두고 qa_run.py)"]
    if want and rec["cmd"] != want:
        return [f"{q}의 cmd '{str(rec['cmd'])[:60]}' ≠ 커밋된 test_cmd '{want[:60]}' — qa_run.py로 다시 돌린다"]
    tgt = qa_target(mr_text)
    if not tgt:
        return [f"{hdir}/mr/{g}.md 「QA 결과」에 대상 commit/tree 없음 — {q}와 대조할 수 없음"]
    rt = str(rec["tree"])
    if not any(c and len(c) >= 7 and rt.startswith(c) for c in (tgt, vf_git.tree_of(tgt))):
        return [f"{q}의 tree({rt[:12]})가 MR 「QA 결과」 대상({tgt[:12]})과 다름 — 다른 작업물의 실행 기록"]
    return []


def export_evidence(cfg, g):
    """기록 커밋에 넣을 검증 증거를 .vibe/에서 <핸드오프>/mr/로 옮긴다: MR 본문, QA 실행 기록, 이 MR의 리뷰 원문.
    MR 「골」에 골이 여럿이면(G-001, G-002) 골마다 G-###.md·-qa.json·-review.md를 같은 내용으로 쓴다 — check-record는
    커밋의 골 ID마다 사본을 찾는다. 리뷰 원문은 기록 도장(goal·branch·base)이 이 MR의 골 목록·지금 브랜치·지금 기준과
    같은 회차만(mr_check.record_problem — 다른 브랜치·리베이스 전 기준의 원문은 이 작업물의 근거가 아니다)."""
    import mr_check
    if not re.fullmatch(r"G-\d{3,}", g):
        die(f"[export-evidence] 골 ID가 아님: {g}")
    _, hdir, _ = detect(cfg)
    mr_src = os.path.join(".vibe", f"mr-{g}.md")
    if not os.path.exists(mr_src):   # 여러 골 MR은 한 골 이름으로 둔다 — 「골」에 이 골을 적은 MR이 하나면 그것
        hits = [os.path.join(".vibe", f) for f in sorted(os.listdir(".vibe")) if re.fullmatch(r"mr-G-\d{3,}\.md", f)
                and g in mr_check.mr_goal(read(os.path.join(".vibe", f)), cfg).split(",")] if os.path.isdir(".vibe") else []
        if len(hits) != 1:
            die(f"[export-evidence] MR 본문 {mr_src} 없음" + (f" (「골」에 {g}를 적은 MR이 여럿: {', '.join(hits)})" if hits else ""))
        mr_src = hits[0]
    mr = read(mr_src)
    goals = mr_check.mr_goal(mr, cfg)
    if g not in goals.split(","):
        die(f"[export-evidence] {mr_src}의 「골」에 {g} 없음 ({goals or '골 ID 없음'})")
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
    parts, skipped = [], []
    names = sorted(os.listdir(d)) if os.path.isdir(d) else []
    for kind, stamp in (("d", ".meta"), ("r", ".tree")):
        for n in sorted((x for x in names if re.fullmatch(rf"{kind}\d+\.txt", x)), key=lambda x: int(x[1:-4])):
            sp = os.path.join(d, n[:-4] + stamp)
            why = mr_check.record_problem(sp, goals, cfg)
            if why:
                skipped.append(why)
                continue
            head = f"## {n} ({'설계 확인' if kind == 'd' else '코드 리뷰'})"
            parts.append(f"{head}\n{review_stamp(sp, cfg)}\n````text\n{read(os.path.join(d, n)).rstrip()}\n````\n")
    if not parts:
        die(f"[export-evidence] .vibe/review/에 이 MR({goals})·지금 브랜치·기준의 d*·r*.txt 기록 없음 — review.py로 받은 원문이 있어야 한다"
            + "".join(f"\n  제외: {x}" for x in skipped))
    red_src = latest_red(vf_git.current_branch())
    os.makedirs(f"{hdir}/mr", exist_ok=True)
    gl = goals.split(",")
    caps = []
    for x in gl:
        mr_x, n_cap, miss_cap = export_captures(mr, x, hdir)
        caps = [n_cap, miss_cap]
        write(f"{hdir}/mr/{x}.md", mr_x)
        write(f"{hdir}/mr/{x}-qa.json", read(qa_src))
        if red_src:
            write(f"{hdir}/mr/{x}-red.json", read(red_src))
        write(f"{hdir}/mr/{x}-review.md", f"# {goals.replace(',', ' · ')} 리뷰 원문 (.vibe/review/ 사본, export-evidence)\n\n"
              + "\n".join(parts))
    print(f"[export-evidence] {' · '.join(gl)}: {hdir}/mr/<골>.md · -qa.json (← {qa_src}) · -review.md ({len(parts)}개 원문"
          + (f", 다른 맥락 {len(skipped)}개 제외" if skipped else "") + ")"
          + (f" · -red.json (← {red_src})" if red_src else " · RED 기록 없음(qa_run.py --red — 필수 아님)")
          + (f" · 캡처 {caps[0]}개 → <골>-evidence/" if caps and caps[0] else "") + " — 기록 커밋에 넣는다")
    if caps and caps[1]:
        print(f"[export-evidence] 경고: 「QA 결과」의 캡처 파일 없음 — {', '.join(caps[1][:5])}", file=sys.stderr)


def review_stamp(path, cfg):
    """회차 기록(r<N>.tree·d<N>.meta)을 사본 제목 밑 '<!-- stamp … -->' 블록으로 — tree·goal·branch·base·conds·contract
    (+ 그 tree의 code_tree: 새 clone에는 리뷰 tree 객체가 없을 수 있다). verify-evidence가 커밋된 MR·QA와 대조한다."""
    lines = read(path).splitlines()
    out = []
    if lines and re.fullmatch(r"[0-9a-f]{40}", lines[0].strip()):
        t = lines[0].strip()
        out.append(f"tree: {t}")
        lines = lines[1:]
        if vf_git.obj_type(t) == "tree":
            try:
                out.append(f"code_tree: {qa_run.code_tree(t, cfg)}")
            except RuntimeError:
                pass
    out += [l for l in lines if re.match(r"^\w+:", l) and not l.startswith(("tree:", "code_tree:"))]
    return "<!-- stamp\n" + "\n".join(out) + "\n-->\n"


def parse_stamp(sec):
    """리뷰 사본 회차의 도장 {키: 값}. 없으면 {}."""
    m = re.search(r"<!-- stamp\n(.*?)-->", sec, re.S)
    return {k: v.strip() for k, v in re.findall(r"^(\w+):[ \t]*(.*)$", m.group(1), re.M)} if m else {}


def latest_red(branch):
    """.vibe/qa/red-*.json 중 branch가 같은 가장 최근(started) 기록 경로. 없으면 ''."""
    best = ("", "")
    d = qa_run.QA_DIR
    for f in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not re.fullmatch(r"red-[0-9a-f]{7,40}\.json", f):
            continue
        try:
            rec = json.loads(read(os.path.join(d, f)))
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("branch") == branch and str(rec.get("started", "")) >= best[0]:
            best = (str(rec.get("started", "")), os.path.join(d, f))
    return best[1]


def review_sections(review_md):
    """G-###-review.md의 코드 리뷰 회차 [(n, 원문)] 순서대로 — '## rN.txt' 제목 단위만(dN 설계 확인은 코드 리뷰가 아니다)."""
    secs = [s for s in re.split(r"^(?=##\s)", review_md, flags=re.M) if re.search(r"^VERDICT:", s, re.M)]
    return list(enumerate([s for s in secs if re.match(r"##\s+r\d+\.txt\b", s)], 1))


def reconstructed_qa_tree(sha, cfg, hdir):
    """커밋 sha에서 QA 대상 tree를 다시 만든다: 첫 부모와 다른 경로 중 기록 파일(mr_check.is_record, <핸드오프>/mr/ 전부)을
    부모 판으로 되돌린(부모에 없으면 뺀) tree. QA 뒤 기록만 amend했다면 qa_run이 잡은 tree와 같다 — 새 clone에는
    amend 전 tree 객체가 없으므로(어느 커밋에서도 닿지 않음) 객체 대신 이것과 비교한다. (tree sha, 되돌린 기록, 남은 변경)."""
    import mr_check
    import tempfile
    parent = vf_git.git("rev-parse", "--verify", "-q", f"{sha}^1")
    empty = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"   # 빈 tree(부모 없는 첫 커밋)
    names = vf_git.git("diff", "--name-only", "--no-renames", parent or empty, sha, check=True).splitlines()
    rec = [f for f in names if f and (f.startswith(hdir + "/mr/") or mr_check.is_record(f, cfg))]
    rest = [f for f in names if f and f not in rec]
    fd, idx = tempfile.mkstemp(prefix="vf-qa-index-")
    os.close(fd)
    os.remove(idx)
    env = {"GIT_INDEX_FILE": idx}
    try:
        vf_git.git("read-tree", sha, env=env, check=True)
        for f in rec:
            ent = vf_git.git("ls-tree", parent, "--", f) if parent else ""
            if ent:   # '<mode> blob <sha>\t<path>'
                mode, _, rest_ = ent.partition(" ")
                obj = rest_.split()[1]
                vf_git.git("update-index", "--add", "--cacheinfo", f"{mode},{obj},{f}", env=env, check=True)
            else:
                vf_git.git("rm", "--cached", "-q", "--", f, env=env, check=True)
        return vf_git.git("write-tree", env=env, check=True), rec, rest
    finally:
        if os.path.exists(idx):
            os.remove(idx)


def last_round(review_md):
    """G-###-review.md의 마지막 VERDICT 줄이 든 코드 리뷰 회차('## rN.txt') 원문과 그 VERDICT. 없으면 ('', '')."""
    secs = [s for s in re.split(r"^(?=##\s)", review_md, flags=re.M) if re.match(r"##\s+r\d+\.txt\b", s)]
    for s in reversed(secs):
        v = re.findall(r"^VERDICT:\s*(CONFIRM|CHANGES)", s, re.M)
        if v:
            return s, v[-1]
    return "", ""


def verify_evidence(g=None, commit=None):
    """새 clone에서 재검증: 그 커밋(기본 HEAD)에 커밋된 파일만(git show) 본다 — .vibe/는 쓰지 않는다.
    골마다 MR 사본(완료 조건 모두 [x], 「리뷰 기록」 판정 확정 — 사람 판정 D-nnn이면 커밋된 DECISIONS에 그 블록),
    리뷰 원문(마지막 VERDICT CONFIRM, 그 회차에 blocker 없음, 전 회차 장부에 열린 blocker·major 없음 — 사람 판정이면 결정 블록이 다룸), QA 기록(exit 0, cmd = 커밋된 test_cmd, tree = MR QA 대상),
    커밋 tree와 QA tree의 차이가 기록 파일뿐인지(QA tree 객체가 clone에 없으면 reconstructed_qa_tree로). PASS/FAIL 목록, 모두 통과면 0."""
    import mr_check
    commit = commit or "HEAD"
    sha = vf_git.git("rev-parse", "--verify", "-q", f"{commit}^{{commit}}")
    if not sha:
        die(f"[verify-evidence] 커밋을 찾을 수 없음: {commit}")

    def show(p):
        return vf_git.git("show", f"{sha}:{p}") if vf_git.obj_type(f"{sha}:{p}") == "blob" else None

    cfg = dict(vf_git.DEFAULT_CFG)
    try:
        cfg.update(json.loads(show(".vibe-flow.json") or "{}"))
    except ValueError:
        die("[verify-evidence] 커밋된 .vibe-flow.json이 JSON이 아님")
    if not cfg.get("handoff_dir"):   # 핸드오프 위치도 그 커밋의 tree로 정한다
        cfg["handoff_dir"] = "docs/handoff" if vf_git.obj_type(f"{sha}:docs/handoff") == "tree" else "docs"
    hdir = cfg["handoff_dir"].rstrip("/")
    gids = [g] if g else sorted(set(ID_RE.findall(vf_git.git("log", "-1", "--format=%s%n%b", sha))) - {"G-000"})
    if not gids:
        die("[verify-evidence] 골 ID 없음 — verify-evidence G-### 또는 커밋 메시지에 골 ID")
    res = []

    def ok(cond, name, why=""):
        res.append((bool(cond), name if cond else f"{name} — {why}"))
        return cond

    tree = vf_git.tree_of(sha)
    plan = show(f"{hdir}/PLAN.md") or ""   # PLAN 링크 규칙도 커밋의 PLAN.md로(작업 트리 아님)
    memo = {}

    def code_of(t):
        """t(tree)의 코드 tree(기록 파일을 뺀 tree, 커밋의 PLAN.md 기준). 읽을 수 없으면 ''."""
        if t not in memo:
            try:
                memo[t] = qa_run.code_tree(t, cfg, plan=plan) if vf_git.obj_type(t) == "tree" else ""
            except RuntimeError:
                memo[t] = ""
        return memo[t]

    for gid in gids:
        p = f"{hdir}/mr/{gid}.md"
        mr_raw = show(p)
        if not ok(mr_raw is not None, f"{gid} MR 사본 {p}", "커밋에 없음"):
            continue
        mr = vf_git.normalize_mr(mr_raw, cfg)
        goals = mr_check.mr_goal(mr, cfg)
        ok(gid in goals.split(","), f"{gid}가 MR 사본 「골」에 있음", f"「골」: {goals or '골 ID 없음'} — {gid} 없음")
        qa_sec = re.sub(r"<!--.*?-->", "", mr_check.sections(mr).get("QA 결과", ""), flags=re.S)
        if re.search(rf"^\s*-\s*브라우저:\s*{qa_run.PASS}", qa_sec, re.M):   # 캡처는 사본 폴더 기준(또는 레포 루트 기준)
            caps = [c for c in qa_run.evidence_paths(qa_sec) if qa_run.is_media(c)]
            gone = [c for c in caps if not any(vf_git.obj_type(f"{sha}:{x}") == "blob" for x in
                                               (posixpath.normpath(f"{hdir}/mr/{c}"), posixpath.normpath(c)))]
            ok(caps and not gone, f"{gid} 캡처 증거 {len(caps)}개가 커밋에 있음 (브라우저: 통과)",
               "캡처 증거 없음(새 clone): " + (", ".join(gone[:5]) if caps else "이미지·영상 링크 없음")
               + f" — python handoff.py export-evidence {gid}로 {hdir}/mr/{gid}-evidence/에 넣어 같은 커밋에")
        items = mr_check.completion_items(mr)
        empty = [str(i) for i, (_, t) in enumerate(items, 1) if not t.strip()]
        ok(items and all(c for c, _ in items) and not empty, f"{gid} 완료 조건 {len(items)}개 모두 [x]",
           (f"빈 항목 {', '.join(empty)}번" if empty else f"미체크 {sum(1 for c, _ in items if not c)}개")
           if items else "항목 없음")
        stamp = None   # 판정 근거 회차(CONFIRM 회차 또는 사람 판정의 r3)의 도장
        rv = mr_check.sections(mr).get("리뷰 기록", "")
        human = re.search(r"판정:\s*확정\s*[(（]\s*사람 판정\s*(D-\d+)", rv)
        ok(re.search(r"판정:\s*확정", rv), f"{gid} 「리뷰 기록」 판정: 확정", "없음")
        if human:
            did = human.group(1)
            blocks = [show(f) for f in vf_git.git("ls-tree", "--name-only", sha, f"{hdir}/").splitlines()
                      if re.fullmatch(rf"{re.escape(hdir)}/DECISIONS[^/]*\.md", f)]
            hit = [m.group(0) for b in blocks if b for m in [re.search(rf"^##\s+{did}(?!\d).*?(?=^##\s|\Z)", b, re.M | re.S)] if m]
            ok(hit and has_id(gid, hit[0]), f"{gid} 사람 판정 {did}가 커밋된 DECISIONS에 이 골 ID와 함께 있음",
               "블록에 골 ID 없음" if hit else f"{hdir}/DECISIONS*.md에 '## {did}' 없음")
        q = f"{hdir}/mr/{gid}-review.md"
        rtext = show(q)
        secs = review_sections(rtext) if rtext is not None else []
        if ok(rtext is not None, f"{gid} 리뷰 원문 {q}", "커밋에 없음") and \
                ok(secs, f"{gid} 리뷰 원문에 코드 리뷰 회차(## rN.txt)", "rN.txt 회차 없음 — 설계 확인(dN)은 코드 리뷰가 아니다"):
            sec, v = last_round(rtext)
            # 지적 장부: 전 회차를 차례로 — blocker·major는 FINDING으로 열고 RESOLVED(major는 CARRY도)로 닫는다(mr_check.ledger)
            left = mr_check.ledger(secs, sevs=("blocker", "major"))
            shown = ", ".join(f"{i}({s} r{n})" for i, (s, n) in sorted(left.items()))
            if human:   # 사람이 판정했으면 Codex 원문은 기록으로만(마지막이 CHANGES일 수 있다) — 열린 지적은 결정 블록이 다룬다
                did = human.group(1)
                last_n = re.match(r"##\s+r(\d+)", secs[-1][1]).group(1)
                nums = [re.match(r"##\s+r(\d+)", s_).group(1) for _, s_ in secs]
                ok(nums == ["1", "2", "3"], f"{gid} 사람 판정 {did}은 r1·r2·r3 연속 회차 뒤",
                   f"코드 리뷰 회차 {', '.join('r' + n for n in nums) or '없음'} — VERDICT 있는 r1·r2·r3가 모두 있어야 한다")
                ok(v and last_n == "3" and secs[-1][1] == sec, f"{gid} 사람 판정 {did}은 유효한 r3 뒤",
                   f"마지막 코드 리뷰 회차 r{last_n}{'' if v else '(VERDICT 없음)'} — 사람 판정은 3라운드 뒤에만(r3 필요)")
                blk = hit[0] if hit else ""
                lack = sorted(i for i in left if not mr_check.has_fid(i, blk))
                ok(not lack, f"{gid} 열린 지적을 사람 판정 {did} 블록이 모두 다룸",
                   f"블록에 없는 열린 지적 {', '.join(lack)}")
                cover = mr_check.decision_cover(did, rv, left, cfg, "리뷰 기록", blk=blk)
                ok(not cover, f"{gid} 「리뷰 기록」 '- 사람 결정: {did} — <ID들>'이 열린 지적을 모두 적음", "; ".join(cover))
                stamp = parse_stamp(sec)
                tm = re.search(rf"^\s*-\s*사람 결정:\s*{did}(?!\d).*?\(\s*tree\s+([0-9a-f]{{7,40}})\s*\)", rv, re.M)
                ok(tm and stamp.get("tree", "").startswith(tm.group(1)), f"{gid} 사람 결정 {did}의 tree = r3 리뷰 tree",
                   "결정 줄에 (tree <sha>) 없음" if not tm else
                   f"결정 tree {tm.group(1)[:10]} ≠ r3 tree {stamp.get('tree', '없음')[:10]}")
            elif ok(v == "CONFIRM", f"{gid} 리뷰 원문 마지막 VERDICT: CONFIRM", f"마지막 VERDICT: {v or '없음'}"):
                bl = [x for x in mr_check.findings(sec) if x["sev"].lower() == "blocker"]
                ok(not bl, f"{gid} 마지막 회차에 blocker FINDING 없음", ", ".join(x["id"] for x in bl))
                ok(not left, f"{gid} 전 회차 지적 장부에 열린 blocker·major 없음",
                   f"열린 지적 {shown} — 뒤 회차 RESOLVED(major는 CARRY)에 없음")
                stamp = parse_stamp(sec)
            if stamp is not None and ok(stamp.get("tree") and stamp.get("conds") and stamp.get("contract"),
                                        f"{gid} 판정 회차 도장(tree·conds·contract)", "도장 없음 — export-evidence로 다시"):
                sg = [x for x in re.split(r"[,\s]+", stamp.get("goal", "")) if x]   # branch·base는 새 clone에서 대조 불가
                ok(gid in sg, f"{gid} 판정 회차 도장 goal에 {gid}",
                   f"도장 goal: {', '.join(sg) or '없음'} — 다른 골의 리뷰 회차(review.py로 이 MR을 다시 리뷰)")
                ok(stamp["conds"] == mr_check.completion_hash(mr_raw), f"{gid} 리뷰 뒤 완료 조건 그대로(conds)",
                   "리뷰 뒤 완료 조건이 바뀜 — 리뷰 재실행(review.py --round 1)")
                ok(stamp["contract"] == mr_check.contract_hash(mr_raw, cfg), f"{gid} 리뷰 뒤 계약 그대로(contract)",
                   f"리뷰 뒤 계약(「{'」「'.join(mr_check.REVIEW_CONTRACT)}」)이 바뀜 — 리뷰 재실행")
            else:
                stamp = None
        q = f"{hdir}/mr/{gid}-qa.json"
        raw = show(q)
        if not ok(raw is not None, f"{gid} QA 기록 {q}", "커밋에 없음"):
            continue
        try:
            rec = json.loads(raw)
        except ValueError:
            rec = None
        if not ok(isinstance(rec, dict) and all(k in rec for k in ("tree", "cmd", "exit")), f"{gid} QA 기록 형식",
                  "JSON tree·cmd·exit 아님"):
            continue
        ok(rec["exit"] == 0, f"{gid} QA exit 0", f"exit {rec['exit']}")
        ok(qa_ok(rec), f"{gid} QA 통과(전부 건너뜀 아님·ok)",
           f"passed {rec.get('passed', '?')}/{rec.get('total', '?')}, ok {rec.get('ok', '없음')} — 통과한 실행이 아님")
        want = (cfg.get("test_cmd") or "").strip()
        ok(want and rec["cmd"] == want, f"{gid} QA cmd = 커밋된 test_cmd",
           f"기록 '{str(rec['cmd'])[:60]}' ≠ test_cmd '{want[:60] or '없음'}'")
        tgt = qa_target(mr)
        ttree = vf_git.tree_of(tgt) if tgt else ""
        rt = str(rec["tree"])
        cur = code_of(tree)
        if stamp:   # 리뷰가 본 tree의 코드 = QA 코드(= 커밋 코드, 아래에서 대조) — 리뷰 뒤 코드 변경은 증거가 아니다
            st_t = stamp["tree"]
            seen = st_t == rt or (stamp.get("code_tree") or code_of(st_t)) in (rec.get("code_tree") or "\0", cur or "\0")
            try:
                why = ", ".join(mr_check.code_diff(st_t, tree, cfg)[0][:5]) if not seen and vf_git.obj_type(st_t) == "tree" else ""
            except RuntimeError:
                why = ""
            ok(seen, f"{gid} 리뷰가 본 tree의 코드 = QA 코드",
               f"리뷰 tree {st_t[:12]} 뒤 바뀐 코드: {why or '(이 clone에 리뷰 tree 없음 — 대조 불가)'}")
        if "code_tree" in rec:   # 기록 파일을 뺀 코드 tree — QA 전·후 기록 변경과 무관하게 커밋에서 다시 만든다
            ok(tgt and (rt.startswith(tgt) or rt == ttree), f"{gid} QA tree = MR 「QA 결과」 대상",
               "MR에 대상 없음" if not tgt else f"기록 {rt[:12]} · 대상 {tgt[:12]}")
            ok(cur and cur == rec["code_tree"], f"{gid} 커밋 코드 tree = QA 코드 tree (기록 파일을 뺀 tree, 재구성 일치)",
               f"커밋 {cur[:12] or '계산 실패'} ≠ QA {str(rec['code_tree'])[:12]} — QA 뒤 코드가 바뀜")
            continue
        if tgt and not ttree and re.fullmatch(r"[0-9a-f]{40}", rt) and rt.startswith(tgt):
            # 이 clone에 QA tree 객체가 없다(amend 전 tree는 어느 커밋에서도 닿지 않아 clone되지 않음) — 커밋에서 재구성
            try:
                rebuilt, back, rest = reconstructed_qa_tree(sha, cfg, hdir)
            except RuntimeError as e:
                ok(False, f"{gid} QA 대상 tree 재구성", str(e)[:120])
                continue
            ok(rebuilt == rt, f"{gid} QA 대상 tree 재구성 일치 (커밋에서 기록 {len(back)}개를 부모 판으로)",
               f"재구성 {rebuilt[:12]} ≠ 기록 {rt[:12]} — QA 뒤 바뀌었을 수 있는 코드: "
               + (", ".join(rest[:5]) + (" …" if len(rest) > 5 else "") if rest else "(없음 — 기록 파일만 다름)"))
            continue
        if not ok(ttree and rt == ttree, f"{gid} QA tree = MR 「QA 결과」 대상",
                  "MR에 대상 없음" if not tgt else f"기록 {rt[:12]} · 대상 {tgt[:12]}{'' if ttree else '(이 clone에 없음)'}"):
            continue
        try:
            code, _ = mr_check.code_diff(ttree, tree, cfg)
        except RuntimeError as e:
            code = [f"비교 실패: {e}"]
        ok(not code, f"{gid} 커밋 tree와 QA tree 차이가 기록 파일뿐",
           "QA 뒤 바뀐 코드: " + ", ".join(code[:5]) + (" …" if len(code) > 5 else ""))
    for good, line in res:
        print(f"{'PASS' if good else 'FAIL'} {line}")
    for gid in gids:   # RED 증거는 참고(INFO) — 판정에 넣지 않는다
        q = f"{hdir}/mr/{gid}-red.json"
        raw = show(q)
        try:
            rr = json.loads(raw) if raw else None
        except ValueError:
            rr = None
        if not isinstance(rr, dict):
            print(f"INFO {gid} RED 기록 {q} " + ("형식이 아님" if raw else "없음 (qa_run.py --red — 필수 아님)"))
            continue
        bad_t = [k for k, v in (rr.get("tests") or {}).items() if v == "fail"]
        print(f"INFO {gid} RED 기록 {q} — {str(rr.get('tree'))[:12]} exit {rr.get('exit')}"
              + (f", {len(bad_t)}개 실패({', '.join(bad_t[:5])})" if bad_t else ""))
    bad = sum(1 for good, _ in res if not good)
    print(f"[verify-evidence] {vf_git.git('rev-parse', '--short', sha)} " + (f"FAIL {bad}건" if bad else "통과 — 커밋된 증거만으로 확인"))
    sys.exit(1 if bad else 0)


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
        sys.exit(readiness(cfg, run_tests="--run-tests" in a))
    elif a[:1] == ["claim"] and len(a) >= 4:
        claim(cfg, a[1], a[2], a[3], push="--no-push" not in a)
    elif a[:1] == ["check-record"]:
        check_record(cfg, a[2] if len(a) > 2 and a[1] == "--commit" else None)
    elif a[:1] == ["export-evidence"] and len(a) == 2:
        export_evidence(cfg, a[1])
    elif a[:1] == ["verify-evidence"] and len(a) <= 4:
        rest = a[1:]
        at = rest[rest.index("--commit") + 1] if "--commit" in rest[:-1] else None
        gs = [x for x in rest if x != "--commit" and x != at]
        if len(gs) > 1 or (gs and not re.fullmatch(r"G-\d{3,}", gs[0])) or ("--commit" in rest and not at):
            die(__doc__)
        verify_evidence(gs[0] if gs else None, at)
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
