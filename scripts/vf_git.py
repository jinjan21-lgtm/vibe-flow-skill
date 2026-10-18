"""vibe-flow 스크립트들이 같이 쓰는 git 헬퍼. 레포 루트에서 호출한다."""
import json
import re
import os
import subprocess
import tempfile

# 증거 스키마 판 — qa_run 기록·리뷰 기록(r<N>.tree·d<N>.meta)·export 사본이 'schema'를 남긴다. 규격이 바뀌면 올린다.
# verify-evidence는 이보다 낮은(또는 없는) 판의 커밋 증거를 FAIL이 아니라 LEGACY(재검증 대상)로 나눈다.
# 2: 리뷰 도장(tree·code_tree·goal·branch·base·conds·contract), QA code_tree, RED goal·base
EVIDENCE_SCHEMA = 2

DEFAULT_CFG = {"base": "main",
               "ui_globs": ["**/*.tsx", "**/*.jsx", "**/*.vue", "**/*.svelte", "**/*.css", "**/*.scss",
                            "**/*.html", "**/pages/**", "**/routes/**", "**/components/**"],
               "branch_prefixes": [],          # 팀 레포 규칙. 예: ["docs","design","proto","plan","research","chore"]
               "design_skip": {"max_lines": 50, "max_files": 3},   # 이 이하면 설계 확인 생략 가능
               "claim_days": 7}                # 착수 표시 유효 기간


def git(*args, env=None, check=False):
    r = subprocess.run(["git", "-c", "core.quotepath=off", *args], capture_output=True, text=True, encoding="utf-8",
                       env={**os.environ, **(env or {})})
    if check and r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def git_input(args, stdin):
    """표준 입력을 넘기는 git 호출(check-ignore --stdin 등)."""
    r = subprocess.run(["git", "-c", "core.quotepath=off", *args], input=stdin, capture_output=True, text=True,
                       encoding="utf-8")
    return r.stdout.strip()


def codex_cmd(out, cfg=None):
    """codex exec 명령. 추론 강도는 이 호출에만 지정한다(사용자 ~/.codex 설정은 건드리지 않음) — 기본 high, 설정 키 codex_effort."""
    eff = (cfg or config()).get("codex_effort", "high")
    cmd = ["codex", "exec", "--skip-git-repo-check", "-o", out]
    return cmd + (["-c", f"model_reasoning_effort={eff}"] if eff else [])


def config():
    cfg = dict(DEFAULT_CFG)
    if os.path.exists(".vibe-flow.json"):
        with open(".vibe-flow.json", encoding="utf-8") as f:
            cfg.update(json.load(f))
    rp = os.environ.get("VF_REPLAY")
    if rp:   # handoff.py verify-evidence 재연 전용 — 기준을 판정 회차 도장의 조상 커밋으로(handoff.REPLAY_DIFF)
        cfg.update(json.loads(rp))
        cfg["_replay"] = True
    return cfg


def snapshot():
    """지금 작업 트리(미커밋·미추적 포함, 추적 안 된 .gitignore 대상 제외)의 tree sha. 실제 인덱스는 건드리지 않는다."""
    fd, idx = tempfile.mkstemp(prefix="vf-index-")
    os.close(fd)
    os.remove(idx)  # git이 새 인덱스로 만들게 한다
    try:
        env = {"GIT_INDEX_FILE": idx}
        if git("rev-parse", "--verify", "-q", "HEAD"):
            git("read-tree", "HEAD", env=env, check=True)  # 추적 중인 무시 대상 파일도 남긴다
        git("add", "-A", env=env, check=True)
        return git("write-tree", env=env, check=True)
    finally:
        if os.path.exists(idx):
            os.remove(idx)


def glob_match(f, globs):
    """fnmatch에 '**/'가 0개 디렉터리도 뜻하게 한다(루트의 App.tsx도 '**/*.tsx'에 걸림)."""
    import fnmatch
    return any(fnmatch.fnmatch(f, g) or (g.startswith("**/") and fnmatch.fnmatch(f, g[3:])) for g in globs)


def obj_type(ref):
    return git("cat-file", "-t", ref)


def base_tree(base):
    """기준을 tree sha로. 커밋/브랜치면 HEAD와의 merge-base의 tree, tree sha면 그대로."""
    t = obj_type(base)
    if t == "tree":
        return base
    if t == "commit":
        head = git("rev-parse", "--verify", "-q", "HEAD")
        mb = git("merge-base", base, "HEAD") if head else ""
        return git("rev-parse", f"{mb or base}^{{tree}}")
    raise RuntimeError(f"기준 '{base}'를 찾을 수 없습니다 (브랜치·커밋·tree sha 중 하나여야 함)")


def tree_of(ref):
    """commit이나 tree sha를 tree sha로."""
    t = obj_type(ref)
    if t == "tree":
        return ref
    if t == "commit":
        return git("rev-parse", f"{ref}^{{tree}}")
    return ""


def changed_files(a_tree, b_tree):
    return [f for f in git("diff", "--name-only", a_tree, b_tree).splitlines() if f]


def current_branch():
    """지금 브랜치 이름. 커밋이 없는 브랜치에서도 동작한다 (rev-parse --abbrev-ref는 'HEAD'를 돌려줌)."""
    return git("symbolic-ref", "--short", "-q", "HEAD") or git("rev-parse", "--abbrev-ref", "HEAD")


def handoff_mode(cfg=None):
    """team(team-handoff, docs/handoff/) 또는 personal(session-handoff, docs/)."""
    cfg = cfg or config()
    if cfg.get("handoff_dir"):
        d = cfg["handoff_dir"].rstrip("/")
        return ("team" if d.endswith("handoff") else "personal"), d
    if os.path.isdir(os.path.join(".claude", "skills", "team-handoff")) or os.path.isdir(os.path.join("docs", "handoff")):
        return "team", "docs/handoff"
    return "personal", "docs"


def paths(cfg=None):
    """노스스타·골 위치. .vibe-flow.json의 northstar·goals_dir가 있으면 그것을 쓴다."""
    cfg = cfg or config()
    mode, hdir = handoff_mode(cfg)
    goals = cfg.get("goals_dir", f"{hdir}/goals")
    return {"mode": mode, "handoff": hdir,
            "northstar": cfg.get("northstar", f"{hdir}/NORTHSTAR.md"),
            "goals": goals, "candidates": f"{goals}/candidates", "rejected": f"{goals}/rejected"}


def me():
    return git("config", "user.name") or "unknown"


def normalize_mr(text, cfg=None):
    """MR 본문의 제목·라벨 별칭을 기본 이름으로 바꾼다. .vibe-flow.json "mr_labels": {"Design": "설계", "Approach": "접근 방식", ...}
    영어 템플릿이나 다른 제목을 쓰는 레포에서도 같은 검사를 쓰기 위해서다(기본은 별칭 없음)."""
    al = (cfg or config()).get("mr_labels") or {}
    for a, c in al.items():
        ea = re.escape(a)
        text = re.sub(rf"^(##\s+){ea}\s*$", lambda m: m.group(1) + c, text, flags=re.M)
        text = re.sub(rf"^(\s*[-*]?\s*){ea}(\s*:)", lambda m: m.group(1) + c + m.group(2), text, flags=re.M)
        text = re.sub(rf"(:\s*){ea}(?=\W|$)", lambda m: m.group(1) + c, text, flags=re.M)
    return text


def northstar_text(path):
    """노스스타 원문. 인덱스 구조면(첫머리 vibe-index 표식) INDEX가 아니라 본문 파일(NORTHSTAR-body.md)을 돌려준다."""
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        t = f.read()
    if re.search(r"<!--\s*vibe-index:\s*NORTHSTAR\s*-->", t[:300]):
        body = path[:-3] + "-body.md"
        if os.path.exists(body):
            with open(body, encoding="utf-8") as f:
                return f.read()
    return t


def northstar_status(path):
    """노스스타 상태 주석 줄(<!-- status: draft|confirmed -->)만 본다. 본문·개정 이력의 같은 단어는 무시.
    인덱스 구조에서는 본문 파일의 주석을 본다 — INDEX에 주석이 없다고 confirmed로 보지 않는다."""
    if not os.path.exists(path):
        return "none"
    m = re.search(r"^<!--\s*status:\s*(draft|confirmed)\s*-->", northstar_text(path), re.M)
    return m.group(1) if m else "confirmed"
