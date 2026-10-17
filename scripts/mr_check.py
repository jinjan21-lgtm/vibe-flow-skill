#!/usr/bin/env python3
"""MR 본문이 현재 단계로 넘어갈 조건을 갖췄는지 기계적으로 검사한다.

  python mr_check.py <mr-body.md> --stage claim|draft|build|review|qa|merge
  python mr_check.py <mr-body.md> --next     처음 실패하는 단계와 그 단계의 세부 스킬(오케스트레이터용)

  claim  : 「골」에 활성 G-###, 브랜치 이름에 그 골 ID(팀 레포는 접두사 규칙도), 중복 없음 (dupe.py)
  draft  : + 사용자 가치·완료 조건·제외 범위·영향·위험·검증 계획·설계(5요소)가 채워짐, 중복 재검사
  build  : + 「설계 확인」에 '판정: 확정' 또는 '생략: 작은 변경' (구현 시작 전에 돌린다). 확인은 2회까지
  review : + 「계획 vs 실제」. '생략'이었는데 diff가 design_skip 기준을 넘으면 차단. 400줄·10파일 넘으면 경고
  qa     : + 「리뷰 기록」에 "판정: 확정", 라운드 3회 이하
  merge  : + 「QA 결과」의 대상(commit 또는 tree)이 지금 작업물(미커밋 포함)과 같고 코드 통과.
           UI 파일이 바뀌었으면 브라우저 통과 + 캡처. 노스스타가 기준 이후 바뀌었으면 골 재판정 필요.
           base가 앞서 갔으면 리베이스 후 QA

레포 루트에서 실행한다. 설정은 .vibe-flow.json (vf_git.DEFAULT_CFG 참고).
기준(base)은 브랜치·커밋 이름 또는 tree sha(커밋 없는 스냅샷 모드)다.
통과하면 exit 0, 아니면 빠진 항목을 출력하고 exit 1.
"""
import fnmatch
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vf_git  # noqa: E402

DRAFT = ["사용자 가치", "완료 조건", "제외 범위", "영향·위험", "검증 계획"]
DESIGN_ITEMS = ["접근 방식", "바꿀 모듈", "데이터·API", "대안", "테스트 계획"]
EMPTY = {"", "-", "(진행 전)", "(작성 예정)", "tbd", "todo"}
STAGES = ["claim", "draft", "build", "review", "qa", "merge"]
# 막혔을 때 준수 경로 — 메시지에 이 말이 있으면 해당 안내를 붙인다
HINTS = [("비어 있음", "templates/mr-body.md 안내대로 그 칸을 채운다"),
         ("골 파일 없음", "python goal_gate.py candidate \"<제목>\" → judge <후보> --apply"),
         ("G-### 없음", "「골」 칸에 활성 골 ID를 적는다"),
         ("브랜치", "브랜치 이름을 <접두사>/G-###-<주제>로(git branch -m)"),
         ("착수", "그 작업에 합류하거나 골을 나눈다 — 사용자와 정한다"),
         ("같은 골", "그 작업에 합류하거나 골을 나눈다 — 사용자와 정한다"),
         ("설계 확인", "python review.py --design 1 --mr <mr-body.md>"),
         ("리뷰 기록", "python review.py --round 1 --mr <mr-body.md>"),
         ("회를 넘음", "자동 진행을 멈추고 사용자에게 남은 지적을 보고한다(사람 판정)"),
         ("재검증", "qa-gate.md 순서로 지금 작업물에 QA를 다시 하고 「QA 결과」 대상을 갱신"),
         ("브라우저", "qa-gate.md 「브라우저」 — Aside로 확인하고 캡처를 붙인다"),
         ("UI 판정", "화면에 닿는지 판단해 브라우저 줄에 근거를 적는다(닿으면 Aside)"),
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


def diff_size(cfg):
    old, cur = vf_git.base_tree(cfg["base"]), vf_git.snapshot()
    files = vf_git.changed_files(old, cur)
    stat = vf_git.git("diff", "--numstat", old, cur)
    lines = sum(int(a) + int(b) for a, b, *_ in (l.split("\t") for l in stat.splitlines()) if a.isdigit() and b.isdigit())
    return lines, len(files)


def goal_checks(s, cfg):
    miss = []
    gids = re.findall(r"\bG-\d{3,}\b", s.get("골", ""))
    gdir = vf_git.paths(cfg)["goals"]
    if not gids:
        miss.append("「골」에 G-### 없음")
    for gid in gids:
        hit = [fn for fn in os.listdir(gdir) if fn.startswith(gid)] if os.path.isdir(gdir) else []
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
    if gids and not any(g in cur for g in gids):
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
    if i >= 1:
        miss += [f"「{n}」 비어 있음" for n in DRAFT if not filled(s, n)]
        miss += design_items_missing(s.get("설계", ""))
    if i >= 2:
        dc = s.get("설계 확인", "")
        confirmed = re.search(r"판정:\s*확정", dc)
        skipped = re.search(r"생략:\s*작은 변경", dc)
        if not (confirmed or skipped):
            miss.append("「설계 확인」에 '판정: 확정'(또는 '생략: 작은 변경') 없음 — review.py --design 먼저")
        if len(re.findall(r"^-\s*확인\s*\d", dc, re.M)) > 2:
            miss.append("설계 확인이 2회를 넘음 — 사람 판정 필요")
        if i >= 3 and skipped and not confirmed:
            lines, files = diff_size(cfg)
            lim = cfg.get("design_skip", {})
            if lines > lim.get("max_lines", 50) or files > lim.get("max_files", 3):
                miss.append(f"설계 확인을 생략했지만 변경이 {lines}줄·{files}파일로 커짐 — review.py --design 필요")
    if i >= 3 and not filled(s, "계획 vs 실제"):
        miss.append("「계획 vs 실제」 비어 있음")
    if stage == "review":
        size_warning(cfg)
    if i >= 4:
        rv = s.get("리뷰 기록", "")
        if not re.search(r"판정:\s*확정", rv):
            miss.append("「리뷰 기록」에 '판정: 확정' 없음")
        if len(re.findall(r"^-\s*라운드\s*\d", rv, re.M)) > 3:
            miss.append("리뷰 라운드가 3회를 넘음 — 사람 판정 필요")
    if stage == "merge":
        miss += merge_checks(s.get("QA 결과", ""), cfg)
    return miss


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
        p = vf_git.paths(cfg)
        keep = (p["handoff"] + "/", p["goals"] + "/")
        code = [f for f in vf_git.changed_files(vf_git.tree_of(m.group(1)), cur) if not f.startswith(keep)]
        if code:
            miss.append(f"QA 대상 {m.group(1)[:10]} 이후 바뀐 파일({', '.join(code[:3])}) — 재검증 필요(미커밋 포함)")
    if not re.search(r"^-\s*코드:\s*통과", qa, re.M):
        miss.append("「QA 결과」 코드 단계가 '통과'가 아님")
    base = vf_git.base_tree(cfg["base"])
    files = vf_git.changed_files(base, cur)
    ui = [f for f in files if any(fnmatch.fnmatch(f, g) for g in cfg["ui_globs"])]
    if ui:
        if not re.search(r"^-\s*브라우저:\s*통과", qa, re.M):
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
        if code and not (val.startswith("통과") or re.search(r"해당 없음\s*[(（—–:-]\s*\S{2,}", val)):
            miss.append(f"UI 판정 불명확 — 바뀐 코드({', '.join(code[:3])})가 ui_globs에 안 걸림. 「QA 결과」 브라우저 줄에 "
                        "'해당 없음 — <화면에 닿지 않는 이유>'를 적거나, 화면에 닿으면 브라우저 QA(통과 + 캡처)")
    if vf_git.obj_type(cfg["base"]) == "commit" and vf_git.git("rev-parse", "--verify", "-q", "HEAD"):
        mb = vf_git.git("merge-base", cfg["base"], "HEAD")
        ns = vf_git.paths(cfg)["northstar"]
        if vf_git.git("diff", "--name-only", mb, cfg["base"], "--", ns, ns[:-3] + "-body.md"):
            miss.append("이 브랜치가 갈라진 뒤 base에서 노스스타가 바뀜 — 골을 다시 judge 받아야 함")
        if vf_git.git("rev-parse", cfg["base"]) != mb:
            miss.append(f"base({cfg['base']})에 이 브랜치에 없는 커밋이 있음 — 리베이스한 뒤 그 위에서 QA를 다시 하세요")
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
