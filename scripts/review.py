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
결과: .vibe/review/r<N>.txt (Codex 원문), r<N>.tree (그 시점 스냅샷 + schema·goal·branch·base·code_tree·conds·contract), d<N>.meta (골·브랜치·기준
tree·설계 확인 때 코드가 이미 바뀌었는지·design: 「설계」 해시). 다른 골·브랜치·기준의 기록은 다음 회차의 근거가 아니다(mr_check도 같다).
VERDICT: CONFIRM인데 blocker FINDING이 있는 응답은 모순이라 무효(.failed).
지적 장부: 라운드 N>1의 CONFIRM은 앞 라운드에서 열린 blocker·major ID를 모두 RESOLVED에 적어야 유효하다
(major만 'CARRY: <id> — 골 후보 <사유>' 가능, blocker는 불가). 빠지면 무효(.failed).

Codex 호출 전에 mr_check 단계 검사를 직접 돌린다(라운드: review, 설계: draft). 막히면 exit 1.
설계 확인 입력의 파일 내용은 기준 커밋의 것이다. 라운드 1 응답은 완료 조건 번호(1..N)마다 정확히 한 줄
'CHECKED: <번호> — <근거>'가 있어야 유효하다(중복·범위 밖·누락·번호 없음은 무효).
설계 확인 응답은 설계 다섯 칸마다 'CHECKED: <요소> — <근거>'와 POLICY 줄이 있어야 유효하다(design_problems).

라운드 상한: 받아들인 라운드를 .vibe/review/cycles.log에 덧붙이고(append-only), 같은 골·브랜치·기준에서 3라운드를
쓰면 계약이 바뀌어 1라운드부터 다시 돌리는 것도 막는다. 사람 판정 뒤에만 새 사이클:
  python review.py --round 1 --mr mr-body.md --after-decision D-nnn   (결정 블록에 이 골 ID와 '리뷰', D-nnn당 한 번)
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


def ledger_problems(text, prev):
    """라운드 N>1의 CONFIRM: 앞 라운드에서 열린 blocker·major는 이 출력의 RESOLVED에 있어야 한다
    (major만 'CARRY: <id> — 골 후보 <사유>'로 넘길 수 있다). 빠지면 무효 — 열린 지적을 덮은 확정이다."""
    import mr_check
    open_ = mr_check.ledger(prev, mr_check.GATE_SEVS)
    res, car = mr_check.resolved_ids(text), mr_check.carried_ids(text)
    bad = []
    for i, (sev, n) in sorted(open_.items()):
        if i in res or (sev == "major" and i in car):
            continue
        bad.append(f"열린 blocker {i}(라운드 {n})는 CARRY로 넘길 수 없음 — RESOLVED로 닫아야 CONFIRM" if i in car
                   else f"열린 {sev} {i}(라운드 {n})가 RESOLVED에 없음" + (" (major는 'CARRY: <id> — 골 후보 <사유>' 가능)"
                                                                         if sev == "major" else ""))
    return bad


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


CYCLES = os.path.join(D, "cycles.log")
ROUND_CAP = 3


def cycle_ctx(goal, cfg):
    """사이클 장부의 맥락 — 골·브랜치·기준 tree(record_stamp와 같은 기준). 계약 버전은 넣지 않는다:
    계약이 바뀌어 1라운드부터 다시 돌려도 같은 상한 안이다."""
    import mr_check
    return {"goal": goal, "branch": vf_git.current_branch(), "base": mr_check.current_base(cfg)}


def cycle_entries(ctx):
    """cycles.log에서 이 맥락의 줄들(필드 dict). 줄 형식:
    'goal=<골> branch=<브랜치> base=<기준 tree> round=<n> verdict=<CONFIRM|CHANGES>' — 받아들인 라운드
    'cycle=<D-nnn> goal=… branch=… base=…' — 사람 판정 뒤 새 사이클 시작(이 줄 뒤부터 다시 센다)."""
    if not os.path.exists(CYCLES):
        return []
    rows = [dict(re.findall(r"(\w+)=(\S*)", ln)) for ln in read(CYCLES).splitlines()]
    return [r for r in rows if all(r.get(k, "") == v for k, v in ctx.items())]


def rounds_used(ctx):
    """마지막 cycle 표식 뒤에 받아들인 라운드 수."""
    n = 0
    for r in cycle_entries(ctx):
        n = 0 if "cycle" in r else n + ("round" in r)
    return n


def cycle_append(ctx, **kw):
    """장부에 한 줄 덧붙인다(append-only — 지우거나 고치지 않는다)."""
    os.makedirs(D, exist_ok=True)
    head = "".join(f"{k}={v} " for k, v in kw.items() if k == "cycle")
    tail = "".join(f" {k}={v}" for k, v in kw.items() if k != "cycle")
    with open(CYCLES, "a", encoding="utf-8", newline="\n") as f:
        f.write(head + " ".join(f"{k}={v}" for k, v in ctx.items()) + tail + "\n")


def cycle_gate(ctx, n, did, cfg):
    """Codex 전 라운드 상한 검사. did(--after-decision)가 있으면 새 사이클을 열 수 있는지 본다 — 열 수 있으면 True."""
    import mr_check
    if did:
        if n != 1:
            sys.exit("[review] --after-decision은 새 사이클이라 --round 1과만 쓴다.")
        why = mr_check.decision_problem(did, re.findall(r"\bG-\d{3,}\b", ctx["goal"]), cfg) \
            if re.fullmatch(r"D-\d+", did) else f"결정 ID 형식 아님: {did} (D-nnn)"
        if not why and "리뷰" not in mr_check.decision_block(did, cfg)[1]:
            why = f"결정 블록 {did}에 '리뷰'가 없음 — 리뷰를 다시 받기로 한 사람 판정이어야 한다"
        if not why and any(r.get("cycle") == did for r in cycle_entries(ctx)):
            why = f"{did}는 이미 이 골·브랜치·기준의 리뷰 사이클을 한 번 열었다 — 새 사람 판정(D-nnn)이 필요"
        if why:
            sys.exit(f"[review] --after-decision {did} 거부: {why}. Codex를 부르지 않습니다.")
        return True
    used = rounds_used(ctx)
    if used >= ROUND_CAP:
        sys.exit(f"[review] 리뷰 3라운드를 이미 썼다(계약이 바뀌어 1라운드부터 다시 돌리는 경우 포함) — "
                 f"사람 판정(D-nnn) 뒤에만 새 리뷰 사이클. 이 골·브랜치·기준에서 받은 라운드 {used}회({CYCLES}). "
                 "결정 블록에 이 골 ID와 '리뷰'를 적고 'review.py --round 1 --after-decision D-nnn'. Codex를 부르지 않습니다.")
    return False


def conditions(mr):
    """「완료 조건」 항목 문구 — mr_check.completion_items와 같은 파서(번호 목록 '1. [x] …'도 같다)."""
    import mr_check
    return [t for _, t in mr_check.completion_items(mr) if t]


def numbered(conds):
    """리뷰 입력에 넣는 완료 조건 번호표(MR 순서 1..N)."""
    return "".join(f"{i}. {c}\n" for i, c in enumerate(conds, 1))


def checked_problems(text, conds, need_test=False):
    """CHECKED 줄 검사: 'CHECKED: <번호> — <근거>' 형식, 1..N이 정확히 한 번씩(중복·범위 밖·누락·번호 없음은 무효).
    줄 수만 세면 아무 말 두 줄로 두 조건을 채울 수 있다(근거 없는 확정). 근거는 레포에 실재하는 테스트 이름이나
    '파일:줄'이어야 한다(mr_check.checked_ref_problems) — need_test(표준·강화)면 조건마다 테스트 이름이 하나 이상."""
    import mr_check
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
        else:
            bad += [f"{k}번 {p}" for p in mr_check.checked_ref_problems(m.group(2), need_test)]
            bad += [f"{k}번 {p}" for p in mr_check.unmet_problems(m.group(2), text)]
        seen[k] = True
    bad += [f"{i}. {c} — CHECKED 줄 없음" for i, c in enumerate(conds, 1) if i not in seen]
    return bad


def code_tree_line(tree):
    """'code_tree: <기록 파일을 뺀 tree>' 줄 — 새 clone(리뷰 tree 객체가 없음)에서도 리뷰가 본 코드를 대조한다."""
    import qa_run
    try:
        return f"code_tree: {qa_run.code_tree(tree, vf_git.config())}\n"
    except RuntimeError:
        return ""


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
DESIGN_ELEMENTS = ("접근 방식", "바꿀 모듈·파일", "데이터·API 변경", "대안과 선택 이유", "테스트 계획")
DESIGN_MIN_EVIDENCE = 10   # 'CHECKED: <요소> — <근거>'의 근거 최소 글자 수 — '확인함' 같은 빈말로 칸을 채우지 않게
POLICY_LINE = re.compile(r"^POLICY:[ \t]*(.*)$", re.M)
DASH_SPLIT = re.compile(r"^(\S.*?)(?:\s*[—–]+\s*|\s+-+\s+)(\S.*)$")   # '<앞> — <뒤>' (— · – · 띄운 -)


def _policy_none(v):
    return bool(re.fullmatch(r"없음\s*\.?", v.strip()))


def design_policies(text):
    """설계 확인 응답의 POLICY 항목 이름 목록. 'POLICY: 없음'이거나 POLICY 줄이 없으면 [].

    형식(templates/design-prompt.md): 요청이 정하지 않은 업무 정책(보고 지표의 뜻·반올림·할인 대상·권한·보존 기간 등)을
    바꾸는 설계면 항목마다 한 줄 'POLICY: <항목> — <왜 사람 결정이 필요한가>', 없으면 정확히 'POLICY: 없음' 한 줄.
    mr_check는 최근 유효 설계 확인의 이 항목이 MR 「영향·위험」 '- 미확인:'이나 '- 정책 결정: D-nnn — <항목>'에 있는지 본다."""
    out = []
    for v in POLICY_LINE.findall(text):
        m = DASH_SPLIT.match(v.strip())
        if m and not _policy_none(v):
            out.append(m.group(1).strip())
    return out


def design_problems(text):
    """설계 확인 응답 형식 검사. 설계 다섯 칸(DESIGN_ELEMENTS)마다 정확히 한 줄 'CHECKED: <요소> — <근거>'
    (근거 DESIGN_MIN_EVIDENCE자 이상), 그리고 POLICY 줄('없음' 한 줄 또는 '<항목> — <이유>' 한 줄 이상).
    'DESIGN: 1 / VERDICT: CONFIRM' 두 줄만으로는 무엇을 확인했는지 남지 않는다 — 판정 증거가 아니다."""
    bad, seen = [], set()
    for line in re.findall(r"^CHECKED:[ \t]*(.*)$", text, re.M):
        line = line.strip()
        el = next((e for e in DESIGN_ELEMENTS if line.startswith(e)), None)
        m = re.match(r"\s*(?:[—–]+|-+)\s*(.*)$", line[len(el):]) if el else None
        if not m:
            bad.append(f"요소·근거 형식 아님: 'CHECKED: {line}' — 'CHECKED: <요소> — <근거>' (요소: {', '.join(DESIGN_ELEMENTS)})")
            continue
        if el in seen:
            bad.append(f"{el} CHECKED 줄 중복")
            continue
        seen.add(el)
        ev = m.group(1).strip()
        if len(ev) < DESIGN_MIN_EVIDENCE:
            bad.append(f"{el} 근거가 너무 짧음('{ev}') — 확인한 근거나 검토한 대안을 한 문장 이상({DESIGN_MIN_EVIDENCE}자 이상)")
    bad += [f"{e} — CHECKED 줄 없음" for e in DESIGN_ELEMENTS if e not in seen]
    vals = [v.strip() for v in POLICY_LINE.findall(text)]
    if not vals:
        bad.append("POLICY 줄 없음 — 'POLICY: 없음' 또는 'POLICY: <항목> — <왜 사람 결정이 필요한가>'")
    elif any(_policy_none(v) for v in vals) and len(vals) > 1:
        bad.append("'POLICY: 없음'과 다른 POLICY 줄이 같이 있음")
    else:
        bad += [f"POLICY 항목·이유 형식 아님: 'POLICY: {v}' — 'POLICY: <항목> — <왜 사람 결정이 필요한가>'"
                for v in vals if not _policy_none(v) and not DASH_SPLIT.match(v)]
    return bad


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
    bad = design_problems(text)
    if bad:
        invalidate(out)
        sys.exit(f"[design] Codex 응답이 설계 다섯 칸의 CHECKED 근거·POLICY 줄 형식과 맞지 않습니다 — 무효, "
                 f"판정을 적지 않습니다 ({out}.failed).\n" + "\n".join(f" - {c}" for c in bad)
                 + "\n→ 같은 회차를 다시 돌립니다.")
    with open(os.path.join(D, f"d{n}.meta"), "w", encoding="utf-8") as f:
        f.write(mr_check.record_stamp(goal, cfg) + f"diverged: {'yes' if early else 'no'}\nfiles: {', '.join(early)}\n"
                + f"design: {mr_check.design_hash(read(mr_path))}\n")   # 확인 뒤 「설계」가 바뀌면 build부터 막는다
    fs = findings(text)
    print(f"DESIGN {n}: VERDICT {v.group(1)} · " + (" · ".join(f"{x['sev']}" for x in fs) or "지적 없음"))
    for x in fs:
        print(" ", x["raw"])
    pol = design_policies(text)
    if pol:
        print("→ 사람 결정이 필요한 정책: " + "; ".join(pol) + " — 「영향·위험」 '- 미확인:'에 그대로 옮기세요"
              " (결정 뒤 '- 정책 결정: D-nnn — <항목>'). 결정 전에는 merge가 막힙니다.")
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
    ap.add_argument("--after-decision", metavar="D-nnn",
                    help="3라운드를 쓴 뒤 사람 판정(결정 블록에 이 골과 '리뷰')으로 새 리뷰 사이클을 연다(--round 1)")
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
    prev_rounds = [(k, t) for k, t in mr_check.valid_rounds("r", goal, vf_git.config()) if k < n]
    open_ = mr_check.ledger(prev_rounds, ("blocker", "major"))
    ledger_in = ("\n[열린 지적 — RESOLVED 또는 CARRY로 닫는다]\n"
                 + ("".join(f"{i} ({s}, 라운드 {k})\n" for i, (s, k) in sorted(open_.items())) or "없음\n")) if n > 1 else ""
    payload = (read(PROMPT).replace("{ROUND}", str(n)) + "\n[MR 본문]\n" + contract
               + "\n[완료 조건 번호 — CHECKED: <번호> — <근거>]\n" + (numbered(conds) or "없음\n") + design_system(old, cur)
               + ledger_in + "\n[직전 라운드 지적]\n" + (prev or "없음")
               + "\n[코드 테스트 결과]\n" + (read(a.tests) if a.tests and os.path.exists(a.tests) else "없음")
               + "\n[diff]\n" + diff)
    out = os.path.join(D, f"r{n}.txt")
    if a.dry:
        with open(out + ".in", "w", encoding="utf-8") as f:
            f.write(payload)
        print(out + ".in")
        return
    cfg = vf_git.config()
    ctx = cycle_ctx(goal, cfg)
    new_cycle = cycle_gate(ctx, n, a.after_decision, cfg)   # 상한은 계약 버전과 무관하게 골·브랜치·기준당 3
    stage_gate(a.mr, "review")
    if new_cycle:
        cycle_append(ctx, cycle=a.after_decision)
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
    bad = mr_check.resolved_problems(text)
    if bad:
        invalidate(out)
        sys.exit(f"[review] {bad[0]} — 형식이 어긋난 응답이라 무효, 판정을 적지 않습니다 ({out}.failed). "
                 "같은 라운드를 다시 돌립니다.")
    if n > 1 and v.group(1) == "CONFIRM":
        bad = ledger_problems(text, prev_rounds)
        if bad:
            invalidate(out)
            sys.exit(f"[review] VERDICT: CONFIRM인데 앞 라운드의 열린 지적이 닫히지 않음 — 무효, 판정을 적지 않습니다 "
                     f"({out}.failed).\n" + "\n".join(f" - {c}" for c in bad) + f"\n→ 같은 라운드 {n}을 다시 돌립니다.")
    if n > 1:   # 2·3라운드의 CHECKED(r1 '미충족'을 닫으며 다는 새 근거)도 같은 근거 규칙(A10-02)
        need = mr_check.profile(mr_check.sections(mr)) != "경량"
        bad = [f"{k}번 {p}" for k, ev in mr_check.CHECKED_LINE.findall(text)
               for p in mr_check.checked_ref_problems(ev, need) + mr_check.unmet_problems(ev, text)]
        if bad:
            invalidate(out)
            sys.exit(f"[review] 라운드 {n} CHECKED 근거가 무효 — 판정을 적지 않습니다 ({out}.failed).\n"
                     + "\n".join(f" - {c}" for c in bad) + f"\n→ 같은 라운드 {n}을 다시 돌립니다.")
    if n == 1:
        bad = checked_problems(text, conds, need_test=mr_check.profile(mr_check.sections(mr)) != "경량")
        if bad:
            invalidate(out)
            sys.exit(f"[review] Codex 응답의 CHECKED 근거가 완료 조건 1~{len(conds)}번과 한 번씩 맞지 않습니다 — 무효, "
                     f"판정을 적지 않습니다 ({out}.failed).\n" + "\n".join(f" - {c}" for c in bad)
                     + "\n→ 같은 라운드 1을 다시 돌립니다.")
    with open(os.path.join(D, f"r{n}.tree"), "w", encoding="utf-8") as f:
        f.write(f"{cur}\n" + mr_check.record_stamp(goal, vf_git.config()) + code_tree_line(cur)
                + f"conds: {mr_check.completion_hash(mr)}\ncontract: {mr_check.contract_hash(mr)}\n")   # 리뷰 뒤 완료 조건이 바뀌면 qa·merge가 막는다
    cycle_append(ctx, round=n, verdict=v.group(1))   # 받아들인 라운드만 센다(실패·무효 실행은 세지 않는다)
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
