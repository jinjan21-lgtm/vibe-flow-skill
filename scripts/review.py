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
결과: .vibe/review/r<N>.txt (Codex 원문), r<N>.tree (그 시점 스냅샷 + goal·branch·base), d<N>.meta (골·브랜치·기준
tree·설계 확인 때 코드가 이미 바뀌었는지). 다른 골·브랜치·기준의 기록은 다음 회차의 근거가 아니다(mr_check도 같다).
VERDICT: CONFIRM인데 blocker FINDING이 있는 응답은 모순이라 무효(.failed).

Codex 호출 전에 mr_check 단계 검사를 직접 돌린다(라운드: review, 설계: draft). 막히면 exit 1.
설계 확인 입력의 파일 내용은 기준 커밋의 것이다. 라운드 1 응답은 완료 조건 번호(1..N)마다 정확히 한 줄
'CHECKED: <번호> — <근거>'가 있어야 유효하다(중복·범위 밖·누락·번호 없음은 무효).
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
    """실패(종료 코드·빈 출력)면 판정 없이 exit 1. 이전 실행의 결과 파일을 판정으로 쓰지 않는다."""
    if os.path.exists(out):
        os.remove(out)
    with open(out + ".in", "w", encoding="utf-8") as f:
        f.write(text)
    with open(out + ".in", encoding="utf-8") as stdin:
        r = subprocess.run(vf_git.codex_cmd(out), stdin=stdin,
                           capture_output=True, timeout=1200, shell=(os.name == "nt"))
    body = read(out) if os.path.exists(out) else ""
    if r.returncode or not body.strip():
        if os.path.exists(out):
            os.replace(out, out + ".failed")
        err = (r.stderr or b"").decode("utf-8", "replace").strip()[-400:]
        sys.exit(f"[review] Codex 실행 실패 (exit {r.returncode}, 출력 {'없음' if not body.strip() else '있음 — 무시'}). "
                 f"판정을 적지 않습니다.\n{err}")
    return body


def invalidate(*paths):
    """무효가 된 결과를 .failed로 옮긴다(판정·라운드 기준으로 쓰이지 않게)."""
    for p in paths:
        if os.path.exists(p):
            os.replace(p, p + ".failed")


def rec_path(kind, k):
    return os.path.join(D, f"{kind}{k}.{'meta' if kind == 'd' else 'tree'}")


def done(kind, k, goal):
    """이 골의 그 회차가 끝났는가: VERDICT가 있는 출력 + 지금 맥락(같은 골·브랜치·기준)의 기록(라운드 .tree, 설계 .meta).
    다른 골·다른 브랜치·리베이스 전 기준의 기록은 이전 작업의 것이라 다음 회차의 근거가 되지 않는다."""
    import mr_check
    out = os.path.join(D, f"{kind}{k}.txt")
    if not os.path.exists(out) or not mr_check.VERDICT.search(read(out)):
        return False
    return not mr_check.record_problem(rec_path(kind, k), goal, vf_git.config())


def stale_note(kind, k, goal):
    """기록이 지금 맥락의 것이 아니면 그 이유를 한 줄로(막힌 이유를 숨기지 않는다)."""
    import mr_check
    rec = rec_path(kind, k)
    if not os.path.exists(rec):
        return ""
    why = mr_check.record_problem(rec, goal, vf_git.config())
    return f" {why}." if why else ""


def contradiction(text):
    """VERDICT: CONFIRM인데 blocker FINDING이 있으면 모순 — 판정이 아니다(review-prompt.md: CONFIRM은 열린 blocker 0)."""
    import mr_check
    bl = mr_check.blockers(text)
    if bl and re.search(r"^VERDICT:\s*CONFIRM", text, re.M):
        return "VERDICT: CONFIRM인데 blocker FINDING이 있음(" + ", ".join(x["id"] for x in bl) + ")"
    return ""


def tree_sha(path):
    """r<N>.tree 첫 줄(스냅샷 tree sha). 둘째 줄은 'goal: G-###'."""
    return read(path).strip().splitlines()[0].strip()


def stage_gate(mr_path, stage):
    """mr_check와 같은 단계 검사. 막혔으면 Codex를 부르지 않는다(명령을 이어 붙여도 라운드가 돌지 않게)."""
    import mr_check
    miss = mr_check.check(read(mr_path), stage, vf_git.config())
    if miss:
        sys.exit(f"[review] mr_check --stage {stage} 통과 못 함 — Codex를 부르지 않습니다.\n"
                 + "\n".join(f" - {x}" for x in miss))


def conditions(mr):
    """「완료 조건」 항목 문구 — mr_check.completion_items와 같은 파서(번호 목록 '1. [x] …'도 같다)."""
    import mr_check
    return [t for _, t in mr_check.completion_items(mr) if t]


def numbered(conds):
    """리뷰 입력에 넣는 완료 조건 번호표(MR 순서 1..N)."""
    return "".join(f"{i}. {c}\n" for i, c in enumerate(conds, 1))


def checked_problems(text, conds):
    """CHECKED 줄 검사: 'CHECKED: <번호> — <근거>' 형식, 1..N이 정확히 한 번씩(중복·범위 밖·누락·번호 없음은 무효).
    줄 수만 세면 아무 말 두 줄로 두 조건을 채울 수 있다(근거 없는 확정)."""
    bad, seen = [], {}
    for line in re.findall(r"^CHECKED:[ \t]*(.*)$", text, re.M):
        m = re.match(r"(\d+)\s*[—–-]+\s*(\S.*)$", line.strip())
        if not m:
            bad.append(f"번호·근거 형식 아님: 'CHECKED: {line.strip()}' — 'CHECKED: <번호> — <근거>'")
            continue
        k = int(m.group(1))
        if not 1 <= k <= len(conds):
            bad.append(f"범위 밖 번호 {k} (완료 조건 1~{len(conds)})")
        elif k in seen:
            bad.append(f"번호 {k} 중복")
        seen[k] = True
    bad += [f"{i}. {c} — CHECKED 줄 없음" for i, c in enumerate(conds, 1) if i not in seen]
    return bad


def findings(text):
    import mr_check
    return mr_check.findings(text)


def design_system(old, cur):
    """UI 파일이 바뀌었고 디자인시스템 문서가 있으면 리뷰 입력에 넣는다."""
    cfg = vf_git.config()
    path = cfg.get("design_system", os.path.join("docs", "design-system.md"))
    ui = [f for f in vf_git.changed_files(old, cur) if vf_git.glob_match(f, cfg["ui_globs"])]
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
    import mr_check
    goal = mr_check.mr_goal(read(mr_path))
    if n == 2 and not done("d", 1, goal):
        sys.exit("[design] 이 골의 1회차 유효한 기록(VERDICT 있는 d1.txt + 같은 골의 d1.meta)이 없습니다. 건너뛸 수 없습니다."
                 + stale_note("d", 1, goal))
    mr = vf_git.normalize_mr(read(mr_path))
    contract = mr.split("## 설계 확인")[0]
    m = re.search(r"^##\s+설계\s*\n(.*?)(?=^##\s|\Z)", mr, re.M | re.S)
    design = m.group(1) if m else ""
    cfg = vf_git.config()
    ns_path = vf_git.paths(cfg)["northstar"]
    ns = vf_git.northstar_text(ns_path) or "(노스스타 없음)"
    # 설계는 구현 전 코드에 대한 것이다 — 작업 트리가 아니라 기준 커밋의 파일을 보여 준다
    base, cur = vf_git.base_tree(cfg["base"]), vf_git.snapshot()
    files = []
    for p in re.findall(r"[\w./-]+\.\w{1,5}", design):
        if vf_git.obj_type(f"{base}:{p}") == "blob" and p not in files:
            files.append(p)
    code = "".join(f"\n--- {p} (기준 커밋) ---\n{vf_git.git('show', f'{base}:{p}')[:4000]}" for p in files[:8])
    early, _ = mr_check.code_changes(cfg, base, cur)
    note = ""
    if early:
        shown = ", ".join(early[:5]) + (" …" if len(early) > 5 else "")
        note = (f"\n[주의] 구현이 설계 확인보다 먼저 시작됨 — 기준과 달라진 코드: {shown}. "
                "설계는 기준 커밋 기준으로 판단하고, 이미 바뀐 부분이 설계를 앞질러 정한 것이 있으면 지적한다.\n")
        print(f"[design] 경고: 설계 확인 전에 코드가 바뀌었습니다({shown}). 결과와 함께 「설계 확인」에 "
              "'- 순서: 구현 선행 (사유)'를 적으세요 — 없으면 mr_check --stage review가 막습니다.", file=sys.stderr)
    ds_path = cfg.get("design_system", os.path.join("docs", "design-system.md"))
    ds = f"\n[디자인시스템]\n{read(ds_path)}" if os.path.exists(ds_path) else ""
    prev = read(os.path.join(D, "d1.txt")) if n == 2 else "없음"
    payload = (read(DESIGN_PROMPT).replace("{ROUND}", str(n)) + "\n[노스스타]\n" + ns + "\n[MR 본문]\n" + contract
               + "\n[1회차 지적]\n" + prev + ds + note + "\n[설계가 언급한 파일의 기준 커밋 내용]" + (code or " 없음"))
    out = os.path.join(D, f"d{n}.txt")
    if dry:
        with open(out + ".in", "w", encoding="utf-8") as f:
            f.write(payload)
        print(out + ".in")
        return
    stage_gate(mr_path, "draft")
    text = run_codex(payload, out)
    v = re.search(r"^VERDICT:\s*(CONFIRM|CHANGES)", text, re.M)
    if not v:
        invalidate(out)
        sys.exit(f"[design] Codex 응답에 VERDICT가 없습니다 — 무효 ({out}.failed).")
    bad = contradiction(text)
    if bad:
        invalidate(out)
        sys.exit(f"[design] {bad} — 모순된 응답이라 무효, 판정을 적지 않습니다 ({out}.failed). 같은 회차를 다시 돌립니다.")
    with open(os.path.join(D, f"d{n}.meta"), "w", encoding="utf-8") as f:
        f.write(mr_check.record_stamp(goal, cfg) + f"diverged: {'yes' if early else 'no'}\nfiles: {', '.join(early)}\n")
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
    ap = argparse.ArgumentParser(epilog="설계 확인(구현 전): review.py --design 1|2 --mr <MR 본문> [--dry]")
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
    import mr_check
    goal = mr_check.mr_goal(read(a.mr))
    prev_tree = os.path.join(D, f"r{n - 1}.tree")
    if n > 1 and not done("r", n - 1, goal):
        sys.exit(f"[review] 이 골의 라운드 {n - 1} 유효한 기록(VERDICT 있는 r{n - 1}.txt + 같은 골의 r{n - 1}.tree)이 없습니다. "
                 "라운드를 건너뛸 수 없습니다." + stale_note("r", n - 1, goal))

    cur = vf_git.snapshot()
    if n == 1:
        old = vf_git.base_tree(a.base or vf_git.config()["base"])
    else:
        old = tree_sha(prev_tree)
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
    conds = conditions(mr)
    payload = (read(PROMPT).replace("{ROUND}", str(n)) + "\n[MR 본문]\n" + contract
               + "\n[완료 조건 번호 — CHECKED: <번호> — <근거>]\n" + (numbered(conds) or "없음\n") + design_system(old, cur)
               + "\n[직전 라운드 지적]\n" + (prev or "없음")
               + "\n[코드 테스트 결과]\n" + (read(a.tests) if a.tests and os.path.exists(a.tests) else "없음")
               + "\n[diff]\n" + diff)
    out = os.path.join(D, f"r{n}.txt")
    if a.dry:
        with open(out + ".in", "w", encoding="utf-8") as f:
            f.write(payload)
        print(out + ".in")
        return
    stage_gate(a.mr, "review")
    # 다시 돌리는 라운드와 그 뒤 라운드의 이전 결과는 무효 — 실패해도 옛 스냅샷으로 다음 라운드가 돌지 않게
    for k in range(n, 4):
        invalidate(os.path.join(D, f"r{k}.tree"), os.path.join(D, f"r{k}.txt"))
    text = run_codex(payload, out)
    v = re.search(r"^VERDICT:\s*(CONFIRM|CHANGES)", text, re.M)
    if not v:
        invalidate(out)
        sys.exit(f"[review] Codex 응답에 VERDICT가 없습니다 — 무효, 판정을 적지 않습니다 ({out}.failed).")
    bad = contradiction(text)
    if bad:
        invalidate(out)
        sys.exit(f"[review] {bad} — 모순된 응답이라 무효, 판정을 적지 않습니다 ({out}.failed). 같은 라운드를 다시 돌립니다.")
    if n == 1:
        bad = checked_problems(text, conds)
        if bad:
            invalidate(out)
            sys.exit(f"[review] Codex 응답의 CHECKED 근거가 완료 조건 1~{len(conds)}번과 한 번씩 맞지 않습니다 — 무효, "
                     f"판정을 적지 않습니다 ({out}.failed).\n" + "\n".join(f" - {c}" for c in bad)
                     + "\n→ 같은 라운드 1을 다시 돌립니다.")
    with open(os.path.join(D, f"r{n}.tree"), "w", encoding="utf-8") as f:
        f.write(f"{cur}\n" + mr_check.record_stamp(goal, vf_git.config())
                + f"conds: {mr_check.completion_hash(mr)}\n")   # 리뷰 뒤 완료 조건이 바뀌면 qa·merge가 막는다
    fs = findings(text)
    checked = len(re.findall(r"^CHECKED:\s*\S", text, re.M))
    count = {}
    for x in fs:
        count[x["sev"]] = count.get(x["sev"], 0) + 1
    print(f"ROUND {n}: VERDICT {v.group(1)} · " + (" · ".join(f"{k} {c}" for k, c in count.items()) or "지적 없음")
          + f" · 근거 {checked}")
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
