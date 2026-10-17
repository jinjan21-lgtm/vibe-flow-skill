#!/usr/bin/env python3
"""Codex 설계 확인(구현 전, 최대 2회)과 코드 리뷰(구현 후, 최대 3라운드)를 실행한다. 레포 루트에서 실행.

  python review.py --design 1 --mr mr-body.md      설계 확인 1회차 (2회차: --design 2)

  python review.py --round 1 --mr mr-body.md [--base main|<tree>] [--tests test-summary.txt]
  python review.py --round 2 --mr mr-body.md [--tests ...]
  python review.py --round 3 --mr mr-body.md --files a.py b.js [--tests ...]
  --dry  : Codex를 부르지 않고 입력만 만든다

라운드 1: 기준 대비 지금 작업물 전체 diff
라운드 2: 라운드 1 시점 스냅샷 대비 diff + 라운드 1 지적
라운드 3: 라운드 2 시점 스냅샷 대비 diff 중 --files만 + 열린 지적
결과: .vibe/review/r<N>.txt (Codex 원문), r<N>.tree (그 시점 스냅샷)
"""
import argparse
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vf_git  # noqa: E402

D = os.path.join(".vibe", "review")
PROMPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates", "review-prompt.md")


def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def run_codex(text, out):
    with open(out + ".in", "w", encoding="utf-8") as f:
        f.write(text)
    with open(out + ".in", encoding="utf-8") as stdin:
        subprocess.run(["codex", "exec", "--skip-git-repo-check", "-o", out], stdin=stdin,
                       capture_output=True, timeout=1200, shell=(os.name == "nt"))
    return read(out) if os.path.exists(out) else ""


def findings(text):
    rows = []
    for line in text.splitlines():
        m = re.match(r"^FINDING:\s*(.+)$", line.strip())
        if m:
            parts = [p.strip() for p in m.group(1).split("|")]
            rows.append({"id": parts[0], "sev": parts[1] if len(parts) > 1 else "?", "raw": line.strip()})
    return rows


def design_system(old, cur):
    """UI 파일이 바뀌었고 디자인시스템 문서가 있으면 리뷰 입력에 넣는다."""
    import fnmatch
    cfg = vf_git.config()
    path = cfg.get("design_system", os.path.join("docs", "design-system.md"))
    ui = [f for f in vf_git.changed_files(old, cur) if any(fnmatch.fnmatch(f, g) for g in cfg["ui_globs"])]
    if not ui or not os.path.exists(path):
        return ""
    return ("\n[디자인시스템 — UI 파일이 바뀌었으므로 기준에 포함. 위반은 major, 완료 조건에 명시돼 있으면 blocker]\n"
            + read(path))


DESIGN_PROMPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates", "design-prompt.md")


def design_review(n, mr_path, dry):
    """구현 전 설계 확인 (최대 2회). 결과: .vibe/review/d<N>.txt"""
    if n not in (1, 2):
        sys.exit("[design] 설계 확인은 2회까지입니다. 남은 blocker는 사람이 판정합니다.")
    os.makedirs(D, exist_ok=True)
    if n == 2 and not os.path.exists(os.path.join(D, "d1.txt")):
        sys.exit("[design] 1회차 기록이 없습니다. 건너뛸 수 없습니다.")
    mr = vf_git.normalize_mr(read(mr_path))
    contract = mr.split("## 설계 확인")[0]
    m = re.search(r"^##\s+설계\s*\n(.*?)(?=^##\s|\Z)", mr, re.M | re.S)
    design = m.group(1) if m else ""
    cfg = vf_git.config()
    ns_path = vf_git.paths(cfg)["northstar"]
    ns = vf_git.northstar_text(ns_path) or "(노스스타 없음)"
    files = []
    for p in re.findall(r"[\w./-]+\.\w{1,5}", design):
        if os.path.isfile(p) and p not in files:
            files.append(p)
    code = "".join(f"\n--- {p} (현재) ---\n{read(p)[:4000]}" for p in files[:8])
    ds_path = cfg.get("design_system", os.path.join("docs", "design-system.md"))
    ds = f"\n[디자인시스템]\n{read(ds_path)}" if os.path.exists(ds_path) else ""
    prev = read(os.path.join(D, "d1.txt")) if n == 2 else "없음"
    payload = (read(DESIGN_PROMPT).replace("{ROUND}", str(n)) + "\n[노스스타]\n" + ns + "\n[MR 본문]\n" + contract
               + "\n[1회차 지적]\n" + prev + ds + "\n[설계가 언급한 파일의 현재 내용]" + (code or " 없음"))
    out = os.path.join(D, f"d{n}.txt")
    if dry:
        with open(out + ".in", "w", encoding="utf-8") as f:
            f.write(payload)
        print(out + ".in")
        return
    text = run_codex(payload, out)
    v = re.search(r"^VERDICT:\s*(CONFIRM|CHANGES)", text, re.M)
    if not v:
        sys.exit(f"[design] Codex 응답에 VERDICT가 없습니다. {out} 를 확인하세요.")
    fs = findings(text)
    print(f"DESIGN {n}: VERDICT {v.group(1)} · " + (" · ".join(f"{x['sev']}" for x in fs) or "지적 없음"))
    for x in fs:
        print(" ", x["raw"])
    if v.group(1) == "CONFIRM":
        print("→ 「설계 확인」에 '- 확인 %d: 확정'과 '- 판정: 확정'을 적고 구현을 시작하세요 (mr_check --stage build)." % n)
    elif n == 2:
        print("→ 2회 뒤에도 blocker가 남았습니다. 「설계 확인」에 '판정: 보류'를 적고 사람에게 넘기세요.")


def main():
    if "--design" in sys.argv:
        ap = argparse.ArgumentParser()
        ap.add_argument("--design", type=int, required=True)
        ap.add_argument("--mr", required=True)
        ap.add_argument("--dry", action="store_true")
        a = ap.parse_args()
        return design_review(a.design, a.mr, a.dry)
    ap = argparse.ArgumentParser()
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--mr", required=True)
    ap.add_argument("--base")
    ap.add_argument("--tests")
    ap.add_argument("--files", nargs="*", default=[])
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    n = a.round
    if n not in (1, 2, 3):
        sys.exit("[review] 라운드는 1~3만 있습니다. 3라운드 뒤 남은 blocker는 사람이 판정합니다.")
    if n == 3 and not a.files:
        sys.exit("[review] 라운드 3은 열린 지적을 고친 파일만 봅니다: --files 를 주세요.")
    os.makedirs(D, exist_ok=True)
    prev_tree = os.path.join(D, f"r{n - 1}.tree")
    if n > 1 and not os.path.exists(prev_tree):
        sys.exit(f"[review] 라운드 {n - 1} 기록이 없습니다. 라운드를 건너뛸 수 없습니다.")

    cur = vf_git.snapshot()
    if n == 1:
        old = vf_git.base_tree(a.base or vf_git.config()["base"])
    else:
        old = read(prev_tree).strip()
    diff = vf_git.git("diff", old, cur, "--", *a.files) if n == 3 else vf_git.git("diff", old, cur)
    if not diff:
        print("[review] 직전 기준 대비 바뀐 것이 없습니다.")

    mr = vf_git.normalize_mr(read(a.mr))
    contract = mr.split("## 리뷰 기록")[0]
    prev = ""
    for k in range(1, n):
        p = os.path.join(D, f"r{k}.txt")
        if os.path.exists(p):
            prev += f"\n--- 라운드 {k} ---\n" + read(p)
    payload = (read(PROMPT).replace("{ROUND}", str(n)) + "\n[MR 본문]\n" + contract + design_system(old, cur)
               + "\n[직전 라운드 지적]\n" + (prev or "없음")
               + "\n[코드 테스트 결과]\n" + (read(a.tests) if a.tests and os.path.exists(a.tests) else "없음")
               + "\n[diff]\n" + diff)
    out = os.path.join(D, f"r{n}.txt")
    if a.dry:
        with open(out + ".in", "w", encoding="utf-8") as f:
            f.write(payload)
        print(out + ".in")
        return
    text = run_codex(payload, out)
    with open(os.path.join(D, f"r{n}.tree"), "w") as f:
        f.write(cur)
    v = re.search(r"^VERDICT:\s*(CONFIRM|CHANGES)", text, re.M)
    if not v:
        sys.exit(f"[review] Codex 응답에 VERDICT가 없습니다. {out} 를 확인하세요.")
    fs = findings(text)
    count = {}
    for x in fs:
        count[x["sev"]] = count.get(x["sev"], 0) + 1
    print(f"ROUND {n}: VERDICT {v.group(1)} · " + (" · ".join(f"{k} {c}" for k, c in count.items()) or "지적 없음"))
    for x in fs:
        print(" ", x["raw"])
    if v.group(1) == "CHANGES" and n == 3:
        print("→ 3라운드 뒤 blocker가 남았습니다. 리뷰 기록에 '판정: 보류'를 적고 사람에게 넘기세요.")
    elif v.group(1) == "CONFIRM":
        print("→ 리뷰 기록에 '판정: 확정'을 적고 QA로 가세요.")


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    main()
