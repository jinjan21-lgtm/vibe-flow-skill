#!/usr/bin/env python3
"""QA 코드 단계: test_cmd를 실제로 돌리고 그 결과를 작업물 tree에 묶어 남긴다. 레포 루트에서 실행.

  python qa_run.py [--red] [--mr <mr 본문>]

  - 지금 작업물(미커밋 포함)의 tree(vf_git.snapshot)를 잡고 .vibe-flow.json의 test_cmd를 셸로 실행
  - .vibe/qa/<tree>.json에 tree·cmd·exit·started·seconds·tail(출력 마지막 200줄) 기록,
    출력에서 테스트 수를 알아보면 passed·total·skipped도(unittest·pytest·jest/vitest) — 코드 줄에 'N/M 통과(K 건너뜀)'
  - 「QA 결과」에 붙일 줄을 출력. --mr이면 그 본문의 '대상 tree'·'코드' 줄을 바로 고친다
    verbose 출력(unittest -v·pytest -v)이면 테스트별 결과 tests: {"<전체 이름>": "ok"|"fail"|"skip"}도
  - 종료코드: 통과 0, 실패 1, test_cmd 없음 2(미검증)
  - --red: 구현 전 실패하는 테스트의 RED 증거. 같은 실행을 .vibe/qa/red-<tree>.json(+branch)에 남기고
    '- RED: <tree12> — N개 실패(이름…)' 줄을 출력(--mr이면 「QA 결과」에). 실패면 0, 이미 통과면 1(RED가 아님)

verify(qa_text, cfg)는 mr_check merge 검사가 쓴다 — 「QA 결과」의 '코드: 통과'·'브라우저: 통과'를
실행 기록·실제 캡처 파일과 대조해 문제 목록을 돌려준다(없으면 []). 예외를 던지지 않는다.
기록 커밋에서는 이 기록을 <핸드오프>/mr/G-###-qa.json으로 복사한다(vibe-record, handoff.py check-record).
"""
import datetime
import json
import os
import re
import subprocess
import sys
import time
from urllib.parse import unquote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vf_git  # noqa: E402

TAIL = 200
QA_DIR = os.path.join(".vibe", "qa")
PASS = r"통과(?=$|[\s(（—–])"   # mr_check.PASS와 같다
TARGET = r"대상 (?:commit|tree):\s*`?([0-9a-f]{7,40})"   # mr_check.merge_checks와 같다
MEDIA = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm")   # 브라우저 증거로 받는 파일


def target(qa_text):
    """「QA 결과」(또는 MR 본문)의 대상 commit/tree sha — 안내 주석(<!-- … -->) 안의 예시는 대상이 아니다. 없으면 ''.
    handoff.py check-record·export-evidence·verify-evidence와 verify()가 같이 쓴다(fill_mr도 주석 안을 건드리지 않는다)."""
    m = re.search(TARGET, re.sub(r"<!--.*?-->", "", qa_text or "", flags=re.S))
    return m.group(1) if m else ""


def parse_counts(out):
    """테스트 출력에서 (통과 수, 전체 수, 건너뜀 수). 알아볼 수 없으면 None — 수를 손으로 쓰지 않게 기록에 남긴다.
    건너뛴 테스트는 통과가 아니다(전체에는 센다). jest/vitest 'Tests: … N passed …', pytest '== N passed, M failed ==',
    unittest 'Ran N tests' + OK/FAILED(...)."""
    lines = (out or "").splitlines()
    for line in reversed(lines):   # jest·vitest
        if re.match(r"^\s*Tests:?\s", line):
            p = re.search(r"(\d+) passed", line)
            t = re.search(r"(\d+) total", line) or re.search(r"\((\d+)\)", line)
            if p and t:
                s = re.search(r"(\d+) (?:skipped|todo)", line)
                return int(p.group(1)), int(t.group(1)), int(s.group(1)) if s else 0
    for line in reversed(lines):   # pytest 요약 줄
        if re.search(r"\b\d+ (?:passed|failed|skipped)\b.*\bin [\d.]+s\b", line):
            n = {k: int(v) for v, k in re.findall(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed)\b", line)}
            p, sk = n.get("passed", 0), n.get("skipped", 0) + n.get("xfailed", 0)
            return p, p + sk + n.get("failed", 0) + n.get("error", 0) + n.get("errors", 0) + n.get("xpassed", 0), sk
    ran = re.findall(r"^Ran (\d+) tests? in ", out or "", re.M)   # unittest
    if ran:
        tot = int(ran[-1])
        tail = (out or "")[(out or "").rfind("Ran " + ran[-1]):]
        st = re.search(r"^(OK|FAILED)\b(?: \(([^)]*)\))?", tail, re.M)
        if st:
            kv = {k.strip(): int(v) for k, v in re.findall(r"([a-z ]+)=(\d+)", st.group(2) or "")}
            sk = kv.get("skipped", 0) + kv.get("expected failures", 0)
            bad = kv.get("failures", 0) + kv.get("errors", 0) + kv.get("unexpected successes", 0)
            return tot - bad - sk, tot, sk
    return None


UT_LINE = re.compile(r"^(\w+) \(([\w.]+)\)(?:\n.*?)? \.\.\. (ok|FAIL|ERROR|skipped\b.*|expected failure|unexpected success)$",
                     re.M)
PY_LINE = re.compile(r"^(\S+::\S+) (PASSED|FAILED|SKIPPED|ERROR|XFAIL|XPASS)\b", re.M)
STATUS = {"ok": "ok", "PASSED": "ok", "FAIL": "fail", "ERROR": "fail", "FAILED": "fail", "unexpected success": "fail",
          "XPASS": "fail", "SKIPPED": "skip", "XFAIL": "skip", "expected failure": "skip"}


def parse_tests(out):
    """verbose 출력의 테스트별 결과 {"<전체 이름>": "ok"|"fail"|"skip"}. unittest -v 'test_x (pkg.mod.C.test_x) ... ok'
    (docstring 설명 줄이 끼면 다음 줄), pytest -v 'path::C::test_x PASSED'. 알아볼 줄이 없으면 {}."""
    out = (out or "").replace("\r\n", "\n")
    res = {}
    for name, full, st in UT_LINE.findall(out):
        key = full if full.endswith("." + name) else f"{full}.{name}"   # 3.11+는 전체 이름, 그 전은 모듈.클래스
        res[key] = "skip" if st.startswith("skipped") else STATUS[st]
    for full, st in PY_LINE.findall(out):
        res[full] = STATUS[st]
    return res


def count_text(rec):
    """'2/3 통과(1 건너뜀)' — 기록에 수가 없으면 ''."""
    if "passed" not in rec:
        return ""
    sk = rec.get("skipped", 0)
    return f"{rec['passed']}/{rec.get('total')} 통과" + (f"({sk} 건너뜀)" if sk else "")


def all_skipped(rec):
    """테스트가 있는데 하나도 통과하지 않았다(전부 건너뜀) — exit 0이어도 통과가 아니다."""
    return "passed" in rec and rec["passed"] == 0 and (rec.get("total") or 0) > 0


def ok(rec):
    """통과한 실행인가: exit 0이고 ok가 false가 아니며 전부 건너뜀(passed 0, total>0)이 아니다."""
    return isinstance(rec, dict) and rec.get("exit") == 0 and rec.get("ok", True) is not False and not all_skipped(rec)


def is_media(p):
    return p.lower().endswith(MEDIA)


def code_tree(tree, cfg, plan=None):
    """tree에서 기록 파일(mr_check.is_record, <핸드오프>/mr/ 전부, .vibe/)을 뺀 tree sha — 임시 index로 만든다.
    plan: PLAN.md 본문(없으면 그 tree의 PLAN.md) — PLAN 링크 규칙도 그 tree 기준."""
    import tempfile
    import mr_check
    h = vf_git.paths(cfg)["handoff"].rstrip("/")
    if plan is None:
        plan = vf_git.git("show", f"{tree}:{h}/PLAN.md") if vf_git.obj_type(f"{tree}:{h}/PLAN.md") == "blob" else ""
    names = vf_git.git("ls-tree", "-r", "--name-only", tree, check=True).splitlines()
    rec = [f for f in names if f and (f.startswith((h + "/mr/", ".vibe/")) or mr_check.is_record(f, cfg, plan=plan))]
    fd, idx = tempfile.mkstemp(prefix="vf-code-index-")
    os.close(fd)
    os.remove(idx)
    env = {"GIT_INDEX_FILE": idx}
    try:
        vf_git.git("read-tree", tree, env=env, check=True)
        if rec:
            for i in range(0, len(rec), 200):
                vf_git.git("rm", "--cached", "-q", "--", *rec[i:i + 200], env=env, check=True)
        return vf_git.git("write-tree", env=env, check=True)
    finally:
        if os.path.exists(idx):
            os.remove(idx)


def record_path(tree, red=False):
    return f".vibe/qa/{'red-' if red else ''}{tree}.json"


def red_line(rec):
    """'- RED: <tree12> — N개 실패(이름…) (기록 .vibe/qa/red-<tree>.json)'."""
    bad = [k for k, v in (rec.get("tests") or {}).items() if v == "fail"]
    n = len(bad) if bad else (rec["total"] - rec["passed"] - rec.get("skipped", 0) if "passed" in rec else "?")
    names = f"({', '.join(bad[:5])}{' …' if len(bad) > 5 else ''})" if bad else ""
    return f"- RED: {rec['tree'][:12]} — {n}개 실패{names} (기록 {record_path(rec['tree'], red=True)})"


def run(cfg, red=False):
    """test_cmd 실행 → 기록. (기록 dict, 붙일 줄들). test_cmd가 없으면 None. red면 red-<tree>.json(+branch)·RED 줄."""
    cmd = (cfg.get("test_cmd") or "").strip()
    if not cmd:
        return None, []
    tree = vf_git.snapshot()
    started = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    t0 = time.monotonic()
    r = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)   # unittest -v는 stderr로
    secs = round(time.monotonic() - t0, 1)
    out = (r.stdout or b"").decode("utf-8", errors="replace").replace("\r\n", "\n")
    rec = {"tree": tree, "cmd": cmd, "exit": r.returncode, "started": started, "seconds": secs,
           "tail": "\n".join(out.splitlines()[-TAIL:])}
    cnt = parse_counts(out)
    if cnt:   # 통과/전체/건너뜀 수는 출력에서 — 「QA 결과」에 손으로 쓴 수와 대조한다(verify)
        rec["passed"], rec["total"], rec["skipped"] = cnt
    tests = parse_tests(out)
    if tests:   # 테스트별 결과 — 회귀(전에 통과한 테스트가 빠지거나 실패) 대조용
        rec["tests"] = tests
    rec["ok"] = ok(rec)
    if red:
        rec["branch"] = vf_git.current_branch()
    os.makedirs(QA_DIR, exist_ok=True)
    with open(record_path(tree, red), "w", encoding="utf-8", newline="\n") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
        f.write("\n")
    if vf_git.snapshot() != tree:
        print("[qa-run] 경고: 테스트가 작업물을 바꿨다(추적 대상 파일 생성·수정) — 기록 tree는 실행 전 상태다. "
              "산출물을 .gitignore에 넣고 다시 돌린다", file=sys.stderr)
    if red:
        return rec, [red_line(rec)]
    try:   # 기록 파일을 뺀 코드 tree — 새 clone은 QA 전·후 기록이 달라도 이것으로 대조한다(verify-evidence)
        rec["code_tree"] = code_tree(tree, cfg)
        with open(record_path(tree), "w", encoding="utf-8", newline="\n") as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)
            f.write("\n")
    except RuntimeError as e:
        print(f"[qa-run] 경고: 코드 tree 계산 실패({e}) — 새 clone 대조는 재구성으로", file=sys.stderr)
    verdict = "통과" if r.returncode == 0 else "실패"
    if all_skipped(rec):
        verdict = "실패(전부 건너뜀)"
    lines = [f"- 대상 tree: {tree}",
             f"- 코드: {verdict} — {count_text(rec) + ', ' if cnt else ''}{cmd} exit {r.returncode}, {secs}s (기록 {record_path(tree)})"]
    return rec, lines


def fill_mr(path, lines):
    """MR 본문 「QA 결과」의 '대상'·'코드' 줄을 바꾼다(없으면 섹션 첫머리에 넣는다)."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"^##\s+QA 결과\s*$\n?", text, re.M)
    if not m:
        text = text.rstrip("\n") + "\n\n## QA 결과\n"
        m = re.search(r"^##\s+QA 결과\s*$\n?", text, re.M)
    start = m.end()
    nxt = re.search(r"^##\s", text[start:], re.M)
    end = start + nxt.start() if nxt else len(text)
    body = re.sub(r"^\(진행 전\)\s*\n?", "", text[start:end], flags=re.M)
    pats = (r"^\s*-\s*RED:.*$",) if len(lines) == 1 else (r"^\s*-\s*대상 (?:commit|tree):.*$", r"^\s*-\s*코드:.*$")
    for pat, line in zip(pats, lines):
        # 템플릿 안내 주석(<!-- … -->) 안의 예시 줄은 건드리지 않는다
        spans = [c.span() for c in re.finditer(r"<!--.*?-->", body, re.S)]
        hit = next((h for h in re.finditer(pat, body, re.M)
                    if not any(a <= h.start() < b for a, b in spans)), None)
        if hit:
            body = body[:hit.start()] + line + body[hit.end():]
        else:
            body = line + "\n" + body
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text[:start] + body + text[end:])


LINK_RE = re.compile(r"!?\[[^\]]*\]\(\s*(?:<([^>\n]+)>|([^)\s]+))(?:\s+\"[^\"]*\")?\s*\)")


def local_link(m):
    """LINK_RE 매치의 로컬 경로(http(s)·#앵커면 '')."""
    t = (m.group(1) or m.group(2)).strip()
    if re.match(r"(?i)https?://", t) or t.startswith("#"):
        return ""
    return unquote(t.split("#")[0])


def evidence_paths(qa):
    """마크다운 이미지·링크 대상 중 http(s)가 아닌 것(레포 루트 기준 경로). export-evidence·verify-evidence도 쓴다."""
    return [p for p in (local_link(m) for m in LINK_RE.finditer(qa)) if p]


def _verify(qa, cfg):
    miss = []
    if re.search(rf"^\s*-\s*코드:\s*{PASS}", qa, re.M):
        tgt = target(qa)
        tree = vf_git.tree_of(tgt) if tgt else ""
        if not tgt:
            miss.append("「QA 결과」 코드 통과인데 대상 commit/tree 없음 — 실행 기록과 대조할 수 없음(qa_run.py)")
        elif not tree:
            miss.append(f"QA 대상 {tgt[:10]}을 찾을 수 없음 — 실행 기록과 대조할 수 없음")
        else:
            p = record_path(tree)
            if not os.path.exists(p):
                miss.append(f"코드 통과의 실행 기록 {p} 없음 — 손으로 쓴 '통과'는 증거가 아니다. python qa_run.py로 돌린다")
            else:
                try:
                    with open(p, encoding="utf-8") as f:
                        rec = json.load(f)
                except (OSError, ValueError) as e:
                    rec = None
                    miss.append(f"실행 기록 {p}을 읽을 수 없음({e}) — python qa_run.py로 다시 돌린다")
                if isinstance(rec, dict):
                    if rec.get("tree") != tree:
                        miss.append(f"실행 기록 {p}의 tree({str(rec.get('tree'))[:12]})가 QA 대상 tree({tree[:12]})와 다름")
                    if rec.get("exit") != 0:
                        miss.append(f"실행 기록 {p}은 exit {rec.get('exit')} — 코드 단계는 '실패'다")
                    elif not ok(rec):
                        miss.append(f"실행 기록 {p}은 통과가 아님(전부 건너뜀·ok false) — 건너뛰지 않고 돌아가게 고친다")
                    if rec.get("cmd") != (cfg.get("test_cmd") or "").strip():
                        miss.append(f"테스트 명령이 바뀜 — qa_run.py 다시 (기록 {p}: {str(rec.get('cmd'))[:60]})")
                    said = re.search(r"^\s*-\s*코드:.*?(\d+)\s*/\s*(\d+)", qa, re.M)
                    if said and "passed" in rec and (int(said.group(1)), int(said.group(2))) != (rec["passed"], rec.get("total")):
                        miss.append(f"「QA 결과」 코드 줄의 테스트 수 {said.group(1)}/{said.group(2)}가 실행 기록"
                                    f"({rec['passed']}/{rec.get('total')})과 다름 — 손으로 쓰지 말고 qa_run.py --mr로 채운다")
                elif rec is not None:
                    miss.append(f"실행 기록 {p} 형식이 아님")
    if re.search(rf"^\s*-\s*브라우저:\s*{PASS}", qa, re.M):
        paths = evidence_paths(qa)
        if not paths:
            miss.append("브라우저 통과인데 증거 캡처 파일 링크 없음 — '- 증거: ![A1](<레포 기준 경로>.png)'로 실제 파일을 붙인다")
        for p in paths:
            if not os.path.isfile(p):
                miss.append(f"브라우저 증거 파일 없음: {p}")
            elif not p.lower().endswith(MEDIA):
                miss.append(f"브라우저 증거가 이미지·영상이 아님: {p} ({'·'.join(e[1:] for e in MEDIA)}만)")
    return miss


def verify(qa_text, cfg):
    """「QA 결과」 본문의 주장을 실행 기록·캡처 파일과 대조. 문제 목록(없으면 []). 예외를 던지지 않는다."""
    try:
        return _verify(qa_text if isinstance(qa_text, str) else "", cfg or {})
    except Exception as e:  # merge 검사를 죽이지 않는다 — 대신 통과도 시키지 않는다
        return [f"QA 증거 검사 오류: {e}"]


def main():
    a = sys.argv[1:]
    mr = None
    red = a[:1] == ["--red"]
    a = a[1:] if red else a
    if a[:1] == ["--mr"] and len(a) == 2:
        mr = a[1]
    elif a:
        sys.exit(__doc__)
    if mr and not os.path.exists(mr):
        print(f"[qa-run] MR 본문 없음: {mr}", file=sys.stderr)
        sys.exit(2)
    rec, lines = run(vf_git.config(), red=red)
    if rec is None:
        print("[qa-run] test_cmd 없음 — 미검증 (.vibe-flow.json에 test_cmd를 둔다. 자동 테스트가 없으면 syntax_check.py)")
        print("- 코드: 미검증 — test_cmd 없음")
        sys.exit(2)
    if red:
        if rec["exit"] == 0:
            print(f"[qa-run] RED가 아님 — 테스트가 이미 통과 (기록 {record_path(rec['tree'], True)}). 실패하는 테스트를 먼저 쓴다")
            sys.exit(1)
        if not any(v == "fail" for v in (rec.get("tests") or {}).values()) and not (
                "passed" in rec and rec["passed"] + rec.get("skipped", 0) < (rec.get("total") or 0)):
            print(f"[qa-run] RED 아님 — 실행 오류(테스트 실패가 아님): 실패한 테스트를 출력에서 찾지 못함 "
                  f"(exit {rec['exit']}, 기록 {record_path(rec['tree'], True)})")
            sys.exit(1)
        print("[qa-run] RED 증거 — 「QA 결과」에 붙일 줄:\n" + lines[0])
        if mr:
            fill_mr(mr, lines)
            print(f"[qa-run] {mr}의 「QA 결과」 RED 줄을 갱신")
        sys.exit(0)
    if rec["exit"]:
        print(f"[qa-run] 출력 마지막 {min(20, TAIL)}줄:\n" + "\n".join(rec["tail"].splitlines()[-20:]))
    print("[qa-run] 「QA 결과」에 붙일 줄:")
    print("\n".join(lines))
    if mr:
        fill_mr(mr, lines)
        print(f"[qa-run] {mr}의 「QA 결과」 대상·코드 줄을 갱신")
    if all_skipped(rec):
        print("[qa-run] 테스트가 전부 건너뜀 — 통과가 아니다. 건너뛰지 않고 돌아가게 고친다")
    sys.exit(0 if ok(rec) else 1)


if __name__ == "__main__":
    for st in (sys.stdout, sys.stderr):
        st.reconfigure(encoding="utf-8")
    main()
