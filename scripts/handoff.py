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
  python handoff.py verify-evidence [G-###] [--commit <sha>] [--run-tests]
                                                   새 clone 재검증 = 재연: 그 커밋(기본 HEAD)의 커밋된 증거만으로 임시 clone에
                                                   .vibe/를 되살려 로컬과 같은 `mr_check --stage merge`를 돌린다(차이는
                                                   REPLAY_DIFF 표뿐). --run-tests: 커밋된 코드에서 test_cmd를 다시 돌려 기록과
                                                   대조(커밋의 명령을 실행 — 믿는 코드만, 환경변수는 허용 목록만).
                                                   0 통과(--run-tests 일치), 4 UNPROVEN(재실행 안 함), 1 실패,
                                                   3 LEGACY(증거 판 < EVIDENCE_SCHEMA — 재검증 대상)
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
    # merge가 고른 RED를 그대로 내보낸다(mr_check.select_red — 재연이 로컬과 같은 RED를 본다, A9-06)
    red_src = mr_check.select_red(mr_check.sections(vf_git.normalize_mr(mr, cfg)).get("QA 결과", ""), goals.split(","), cfg)
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
        elif os.path.exists(f"{hdir}/mr/{x}-red.json"):   # 지금 merge가 고른 RED가 없으면 예전 사본도 지운다(A10-04)
            os.remove(f"{hdir}/mr/{x}-red.json")
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


ROUND_HEAD = re.compile(r"^##\s+([dr])(\d+)\.txt\b[^\n]*\n", re.M)


def evidence_rounds(review_md):
    """G-###-review.md(export-evidence 사본)의 회차 [(종류 d|r, n, 도장 dict, 원문)] 순서대로."""
    heads = list(ROUND_HEAD.finditer(review_md or ""))
    out = []
    for i, m in enumerate(heads):
        sec = review_md[m.end():heads[i + 1].start() if i + 1 < len(heads) else len(review_md)]
        body = re.search(r"^````text\n(.*?)\n````\s*$", sec, re.M | re.S)
        out.append((m.group(1), int(m.group(2)), parse_stamp(sec), body.group(1) + "\n" if body else ""))
    return out


def evidence_schema(rounds, qa_rec, red_rec):
    """커밋된 증거의 판(EVIDENCE_SCHEMA)이 지금 판보다 낮은 곳 [설명]. 비면 지금 판."""
    want = vf_git.EVIDENCE_SCHEMA

    def low(v):
        try:
            return int(v) < want
        except (TypeError, ValueError):
            return True
    old = [f"{k}{n} 도장 schema {st.get('schema') or '없음'}" for k, n, st, _ in rounds if low(st.get("schema"))]
    if isinstance(qa_rec, dict) and low(qa_rec.get("schema")):
        old.append(f"QA 기록 schema {qa_rec.get('schema') or '없음'}")
    if isinstance(red_rec, dict) and low(red_rec.get("schema")):
        old.append(f"RED 기록 schema {red_rec.get('schema') or '없음'}")
    return old


def base_commit(sha, base_tree):
    """sha의 조상 중 tree가 base_tree인 가장 가까운 커밋(리뷰 도장 base = 그때 기준과의 merge-base tree). 없으면 ''."""
    for line in vf_git.git("log", "--format=%H %T", sha).splitlines():
        h, _, t = line.partition(" ")
        if t == base_tree:
            return h
    return ""


# 재연이 로컬 merge와 다르게 보는 곳 — 이 표가 전부다(나머지는 mr_check.check(…, "merge")가 그대로 판정한다)
REPLAY_DIFF = (
    ("기준(base)", "설정의 base 브랜치 대신 판정 회차 도장 base(tree)를 가진 조상 커밋 — 머지 뒤 base가 앞서 가도 그때 기준으로"),
    ("브랜치", "판정 회차 도장 branch 이름으로 재연 clone에서 체크아웃"),
    ("골 상태", "active 또는 done — 기록 커밋은 골을 닫을 수 있다"),
    ("tree 객체", "amend 전 QA·리뷰 tree는 clone되지 않는다 — 기록의 code_tree(기록 파일을 뺀 tree)로 같은 비교(changed_since)"),
    ("캡처 링크", "사본의 <골>-evidence/ 상대 링크를 레포 루트 기준 <핸드오프>/mr/<골>-evidence/로"),
)


def replay(sha, gid, cfg, hdir, show, out, rerun=False):
    """기록 커밋 sha의 증거로 임시 clone에 .vibe/를 되살리고 로컬과 같은 `mr_check.py --stage merge`를 돌린다.
    out(ok, 줄)에 결과를 쌓는다. 증거 판이 낮으면 재연하지 않고 'LEGACY'를 돌려준다."""
    import shutil
    import tempfile
    mr_raw = show(f"{hdir}/mr/{gid}.md")
    if not out(mr_raw is not None, f"{gid} MR 사본 {hdir}/mr/{gid}.md", "커밋에 없음"):
        return ""
    import mr_check
    goals = mr_check.mr_goal(vf_git.normalize_mr(mr_raw, cfg), cfg)
    out(gid in goals.split(","), f"{gid}가 MR 사본 「골」에 있음", f"「골」: {goals or '골 ID 없음'} — {gid} 없음")
    rv_raw = show(f"{hdir}/mr/{gid}-review.md")
    rounds = evidence_rounds(rv_raw)
    rr = [x for x in rounds if x[0] == "r"]
    if not out(rr, f"{gid} 리뷰 원문 {hdir}/mr/{gid}-review.md의 코드 리뷰 회차(## rN.txt)",
               "커밋에 없음" if rv_raw is None else "rN.txt 회차 없음 — 설계 확인(dN)은 코드 리뷰가 아니다"):
        return ""

    def js(p):
        raw = show(p)
        try:
            return json.loads(raw) if raw else None
        except ValueError:
            return "bad"
    qa_rec, red_rec = js(f"{hdir}/mr/{gid}-qa.json"), js(f"{hdir}/mr/{gid}-red.json")
    if not out(isinstance(qa_rec, dict) and all(k in qa_rec for k in ("tree", "cmd", "exit")),
               f"{gid} QA 기록 {hdir}/mr/{gid}-qa.json", "커밋에 없음" if qa_rec is None else "JSON tree·cmd·exit 아님"):
        return ""
    # 커밋된 값은 믿지 않는다 — tree는 파일 이름이 되므로 정확히 40자리 16진수만(A11-04: '../../x'로 바깥 파일 덮어쓰기)
    bad_tree = [n for n, rc in (("QA", qa_rec), ("RED", red_rec)) if isinstance(rc, dict)
                and not re.fullmatch(r"[0-9a-f]{40}", str(rc.get("tree", "")))]
    if not out(not bad_tree, f"{gid} 증거 기록의 tree 값 형식(40자리 16진수)", f"{', '.join(bad_tree)} 기록의 tree가 sha가 아님"):
        return ""
    old = evidence_schema(rounds, qa_rec, red_rec if isinstance(red_rec, dict) else None)
    if old:
        return "LEGACY: " + "; ".join(old[:6])
    stamp = rr[-1][2]
    branch, base = stamp.get("branch", ""), base_commit(sha, stamp.get("base", ""))
    if branch and (branch.startswith("-") or vf_git.git("check-ref-format", "--branch", branch) != branch):
        branch = ""   # 도장 branch는 git 인자가 된다 — 옵션처럼 보이거나 브랜치 이름이 아니면 쓰지 않는다
    if not out(branch and base, f"{gid} 판정 회차 도장의 브랜치·기준 커밋",
               f"branch '{branch or '없음'}', base tree {stamp.get('base', '없음')[:12]}의 조상 커밋 없음"):
        return ""
    tmp = tempfile.mkdtemp(prefix="vf-replay-")
    try:
        src = vf_git.git("rev-parse", "--show-toplevel")
        vf_git.git("clone", "-q", "--shared", "--no-checkout", src, tmp, check=True)

        def g(*a):
            return subprocess.run(["git", "-C", tmp, *a], capture_output=True, text=True, encoding="utf-8")
        if not out(g("checkout", "-q", "-B", branch, sha).returncode == 0, f"{gid} 재연 clone 체크아웃 {branch}@{sha[:10]}",
                   "체크아웃 실패"):
            return ""
        with open(os.path.join(tmp, ".git", "info", "exclude"), "a", encoding="utf-8") as f:
            f.write("\n.vibe/\n")
        vd = os.path.join(tmp, ".vibe")
        # 커밋이 .vibe(또는 그 심볼릭 링크)를 담고 있으면 되살린 기록이 커밋 내용과 섞이거나 링크를 따라 바깥에 쓰인다(A11-04 잔여)
        if not out(not os.path.lexists(vd), f"{gid} 커밋에 .vibe/ 없음(재연이 만드는 자리)",
                   ".vibe가 커밋에 들어 있음(링크 포함) — .vibe/는 추적하지 않는다(.gitignore)"):
            return ""
        os.makedirs(vd)
        if os.path.realpath(vd) != os.path.join(os.path.realpath(tmp), ".vibe"):
            out(False, f"{gid} 재연 .vibe 경로", "임시 clone 밖을 가리킴")
            return ""
        for k, n, st, body in rounds:
            os.makedirs(os.path.join(vd, "review"), exist_ok=True)
            write(os.path.join(vd, "review", f"{k}{n}.txt"), body)
            head = f"{st['tree']}\n" if k == "r" and st.get("tree") else ""
            write(os.path.join(vd, "review", f"{k}{n}.{'tree' if k == 'r' else 'meta'}"),
                  head + "".join(f"{x}: {v}\n" for x, v in st.items() if x != "tree"))
        os.makedirs(os.path.join(vd, "qa"), exist_ok=True)
        write(os.path.join(vd, "qa", f"{qa_rec['tree']}.json"), json.dumps(qa_rec, ensure_ascii=False))
        if isinstance(red_rec, dict) and red_rec.get("tree"):
            write(os.path.join(vd, "qa", f"red-{red_rec['tree']}.json"), json.dumps(red_rec, ensure_ascii=False))
        mr_local = re.sub(r"(?<![\w/.-])(G-\d{3,}-evidence/)", lambda m: f"{hdir}/mr/{m.group(1)}", mr_raw)
        mr_path = os.path.join(vd, f"mr-{gid}.md")
        write(mr_path, mr_local)
        env = {**os.environ, "VF_REPLAY": json.dumps({"base": base})}
        here = os.path.dirname(os.path.abspath(__file__))
        r = subprocess.run([sys.executable, os.path.join(here, "mr_check.py"), mr_path, "--stage", "merge"], cwd=tmp,
                           env=env, capture_output=True, text=True, encoding="utf-8")
        miss = [x.strip()[2:] for x in r.stdout.splitlines() if x.startswith(" - ")]
        for x in r.stdout.splitlines():   # 막지 않는 상태(시뮬레이션 결정 등)도 제3자에게 보인다
            if x.startswith("[state] "):
                print(f"STATE {gid} {x[8:]}")
        if r.returncode and not miss:
            miss = [(r.stdout + r.stderr).strip()[-300:] or "mr_check 실패"]
        out(r.returncode == 0 and not miss, f"{gid} 재연 merge 검사(로컬과 같은 mr_check --stage merge) 통과",
            f"{len(miss)}건")
        for x in miss:
            out(False, f"{gid} merge", x)
        if rerun and r.returncode == 0 and not miss:
            # 실행 사실 재확인(A9-04): 기록의 tree·code_tree는 자기 신고다 — 커밋된 코드에서 test_cmd를 다시 돌려 대조.
            # 커밋의 test_cmd를 그대로 실행하므로(A10-07) --run-tests로 명시했을 때만, merge 재연이 통과했을 때만,
            # 비밀이 든 환경변수를 넘기지 않는다(RUN_ENV 허용 목록). OS 격리는 하지 않는다 — 믿지 않는 코드는 컨테이너에서.
            q = subprocess.run([sys.executable, os.path.join(here, "qa_run.py")], cwd=tmp, env=run_env(env),
                               capture_output=True, text=True, encoding="utf-8")
            m = re.search(r"대상 tree: ([0-9a-f]{40})", q.stdout)
            got = None
            if m:
                try:
                    with open(os.path.join(tmp, ".vibe", "qa", f"{m.group(1)}.json"), encoding="utf-8") as fh:
                        got = json.load(fh)
                except (OSError, ValueError):
                    got = None
            same_tests = not isinstance(qa_rec.get("tests"), dict) or got is not None and got.get("tests") == qa_rec["tests"]
            out(isinstance(got, dict) and qa_run.ok(got) and got.get("code_tree") == qa_rec.get("code_tree")
                and (got.get("passed"), got.get("total")) == (qa_rec.get("passed"), qa_rec.get("total")) and same_tests,
                f"{gid} 독립 재실행: 커밋된 코드에서 test_cmd 통과·수·테스트별 결과가 기록과 같음",
                "재실행 기록 없음" if not got else
                f"exit {got.get('exit')}, {got.get('passed')}/{got.get('total')} (기록 {qa_rec.get('passed')}/{qa_rec.get('total')})"
                + ("" if got.get("code_tree") == qa_rec.get("code_tree") else ", 코드 tree 다름")
                + ("" if same_tests else ", 테스트별 결과가 기록과 다름"))
        return "\n".join(miss)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


RUN_ENV = ("PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR", "HOME",
           "USERPROFILE", "LANG", "LC_ALL", "PYTHONIOENCODING", "PYTHONUTF8", "VF_REPLAY")


def run_env(env):
    """--run-tests 재실행에 넘기는 환경변수 — 허용 목록만(토큰·키 등은 넘기지 않는다)."""
    return {k: v for k, v in env.items() if k.upper() in RUN_ENV}


def verify_evidence(g=None, commit=None, rerun=False):
    """새 clone 재검증 = 재연(replay): 그 커밋(기본 HEAD)에 커밋된 증거(MR 사본·리뷰 원문과 회차 도장·QA·RED 기록)만으로
    임시 clone에 .vibe/를 되살려 로컬과 **같은** merge 검사(mr_check.py --stage merge)를 돌린다 — 판정 규칙은 하나다.
    로컬과 다르게 보는 곳은 REPLAY_DIFF 표뿐. 증거 판(schema)이 지금 판보다 낮으면 FAIL이 아니라 LEGACY(재검증 대상, 종료 3).
    상태(UNVERIFIED·ACCEPTED-RISK·POLICY-PENDING)는 STATE 줄로도 낸다. 실행 사실(테스트가 정말 그렇게 돌았나)은
    --run-tests(rerun)로 커밋된 코드에서 test_cmd를 다시 돌려야 확인된다 — 안 돌리면 통과가 아니라 UNPROVEN(종료 4).
    종료: 통과 0, 실패 1, LEGACY 3, UNPROVEN 4(재연 merge는 통과, 실행 사실 미확인)."""
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
    res, legacy = [], []

    def ok(cond, name, why=""):
        res.append((bool(cond), name if cond else f"{name} — {why}"))
        return cond

    for gid in gids:
        miss = replay(sha, gid, cfg, hdir, show, ok, rerun=rerun)
        if miss.startswith("LEGACY: "):
            legacy.append(f"{gid} 증거 판 < v{vf_git.EVIDENCE_SCHEMA} ({miss[8:]}) — 지금 규칙으로 판정 불가. 재검증 대상: "
                          f"같은 코드에서 review.py·qa_run.py(--red --mr)를 다시 돌리고 export-evidence {gid}로 기록을 고친다")
            continue
        for st in mr_check_states(miss):
            print(f"STATE {gid} {st}")
    for good, line in res:
        print(f"{'PASS' if good else 'FAIL'} {line}")
    for line in legacy:
        print(f"LEGACY {line}")
    bad = sum(1 for good, _ in res if not good)
    short = vf_git.git("rev-parse", "--short", sha)
    if bad:
        print(f"[verify-evidence] {short} FAIL {bad}건" + (f" · LEGACY {len(legacy)}건" if legacy else ""))
        sys.exit(1)
    if legacy:
        print(f"[verify-evidence] {short} LEGACY {len(legacy)}건 — 옛 판 증거, 재검증 대상(통과 아님)")
        sys.exit(3)
    if not rerun:   # A10-03: 기록 대조만으로는 테스트가 그렇게 돌았다는 증명이 아니다
        print(f"[verify-evidence] {short} UNPROVEN — 재연 merge 검사는 통과, 실행 사실은 미확인(통과 아님). "
              "커밋의 test_cmd를 믿을 수 있으면 --run-tests로 다시 돌려 확인한다(믿지 않는 코드는 격리된 환경에서)")
        sys.exit(4)
    print(f"[verify-evidence] {short} 통과 — 커밋된 증거만으로 로컬과 같은 merge 검사 + 테스트 재실행 일치")
    sys.exit(0)


def mr_check_states(miss):
    """재연 merge 결과 줄 중 상태(UNVERIFIED·ACCEPTED-RISK·POLICY-PENDING)로 시작하는 줄."""
    import mr_check
    return [x for x in (miss or "").splitlines() if x.split(" ", 1)[0] in mr_check.STATES]


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
    elif a[:1] == ["verify-evidence"] and len(a) <= 5:
        rerun = "--run-tests" in a   # 커밋의 test_cmd 재실행은 명시적으로만(A10-07). 없으면 UNPROVEN(종료 4, A10-03)
        rest = [x for x in a[1:] if x != "--run-tests"]
        at = rest[rest.index("--commit") + 1] if "--commit" in rest[:-1] else None
        gs = [x for x in rest if x != "--commit" and x != at]
        if len(gs) > 1 or (gs and not re.fullmatch(r"G-\d{3,}", gs[0])) or ("--commit" in rest and not at):
            die(__doc__)
        verify_evidence(gs[0] if gs else None, at, rerun=rerun)
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
