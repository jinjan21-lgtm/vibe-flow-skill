#!/usr/bin/env python3
"""QA 코드 단계: test_cmd를 실제로 돌리고 그 결과를 작업물 tree에 묶어 남긴다. 레포 루트에서 실행.

  python qa_run.py [--mr <mr 본문>]
  python qa_run.py --red --mr <mr 본문>

  - 지금 작업물(미커밋 포함)의 tree(vf_git.snapshot)를 잡고 .vibe-flow.json의 test_cmd를 셸로 실행
  - .vibe/qa/<tree>.json에 tree·cmd·exit·started·seconds·tail(출력 마지막 200줄) 기록,
    출력에서 테스트 수를 알아보면 passed·total·skipped도(unittest·pytest·jest/vitest) — 코드 줄에 'N/M 통과(K 건너뜀)'
  - 「QA 결과」에 붙일 줄을 출력. --mr이면 그 본문의 '대상 tree'·'코드' 줄을 바로 고친다
    verbose 출력(unittest -v·pytest -v)이면 테스트별 결과 tests: {"<전체 이름>": "ok"|"fail"|"skip"}도
  - 종료코드: 통과 0, 실패 1, test_cmd 없음 2(미검증)
  - --red: 구현 전 실패하는 테스트의 RED 증거. 같은 실행을 .vibe/qa/red-<tree>.json(+branch·goal·base)에 남기고
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
            if t and (p or re.search(r"\d+ failed", line)):   # 전부 실패면 'passed'가 없다(A11-01 — RED 출력)
                s = re.search(r"(\d+) (?:skipped|todo)", line)
                return int(p.group(1)) if p else 0, int(t.group(1)), int(s.group(1)) if s else 0
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
    syn = re.findall(r"^\[syntax\] (\d+)/(\d+) 통과", out or "", re.M)   # syntax_check.py(자동 테스트 없는 레포)
    if syn:
        return int(syn[-1][0]), int(syn[-1][1]), 0
    return None


UT_LINE = re.compile(r"^(\w+) \(([\w.]+)\)(?:\n.*?)? \.\.\. (ok|FAIL|ERROR|skipped\b.*|expected failure|unexpected success)$",
                     re.M)
PY_LINE = re.compile(r"^(\S+::\S+) (PASSED|FAILED|SKIPPED|ERROR|XFAIL|XPASS)\b", re.M)
VT_LINE = re.compile(r"^\s*([✓√×✕↓-])\s+(\S+\.(?:test|spec)\.[cm]?[jt]sx?\s+>\s+.+?)(?:\s+\d+(?:\.\d+)?\s*m?s)?\s*$", re.M)
JEST_FAIL = re.compile(r"^\s*●\s+(?!Test suite failed)(.+?)\s*$", re.M)   # jest 실패 요약 '● 묶음 › 이름'
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
    # vitest(--reporter=verbose) '✓ src/a.test.ts > 묶음 > 이름 3ms' — 파일까지 든 전체 이름
    for mark, full in VT_LINE.findall(out):
        res[full.strip()] = "ok" if mark in "✓√" else ("skip" if mark in "↓-" else "fail")
    # jest(--verbose) '  ✓ 이름 (3 ms)' — 파일(PASS/FAIL 머리줄)·describe 들여쓰기로 전체 이름. 실패 요약 '● 묶음 › 이름'도
    fname, stack = "", []
    for line in out.splitlines():
        h = re.match(r"^(?:PASS|FAIL)\s+(\S+)", line)
        if h:
            fname, stack = h.group(1), []
            continue
        if not fname:
            continue
        t = re.match(r"^(\s+)([✓√✕×○])\s+(.+?)(?:\s+\(\d+(?:\.\d+)?\s*m?s\))?\s*$", line)
        if t:
            depth = len(t.group(1)) // 2
            name = " › ".join([s for d, s in stack if d < depth] + [t.group(3)])
            res[f"{fname} › {name}"] = "ok" if t.group(2) in "✓√" else ("skip" if t.group(2) == "○" else "fail")
            continue
        d = re.match(r"^(\s+)([^\s●✓√✕×○].*?)\s*$", line)
        if d and not re.match(r"^\s+(?:at |Expected|Received|●)", line):
            depth = len(d.group(1)) // 2
            stack = [(dd, s) for dd, s in stack if dd < depth] + [(depth, d.group(2))]
    for name in JEST_FAIL.findall(out):
        if not any(k.endswith(" › " + name.strip()) or k.endswith(name.strip()) for k in res):
            res[name.strip()] = "fail"
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
    """통과한 실행인가: exit 0이고 ok가 false가 아니며, 출력에서 읽은 테스트 수가 있고 통과가 1건 이상(A9-08 — 0건 실행·
    수를 읽을 수 없는 출력은 통과가 아니다. 테스트 러너가 수를 출력하게 test_cmd를 고친다)."""
    return (isinstance(rec, dict) and rec.get("exit") == 0 and rec.get("ok", True) is not False
            and (rec.get("passed") or 0) > 0 and (rec.get("total") or 0) > 0)


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
    # 추적 중인 산출물(.pyc 등 — mr_check.tracked_artifact)도 뺀다: code_diff와 같은 제외 집합이어야 로컬·재연이 같다(A9-07)
    rec = [f for f in names if f and (f.startswith((h + "/mr/", ".vibe/")) or mr_check.is_record(f, cfg, plan=plan)
                                      or mr_check.tracked_artifact(f, cfg))]
    fd, idx = tempfile.mkstemp(prefix="vf-code-index-")
    os.close(fd)
    os.remove(idx)
    env = {"GIT_INDEX_FILE": idx}
    try:
        vf_git.git("read-tree", tree, env=env, check=True)
        if rec:
            for i in range(0, len(rec), 200):
                # rm --cached는 작업 트리 파일과 다르면 거부한다 — 임시 index에서만 지우는 update-index로
                vf_git.git("update-index", "--force-remove", "--", *rec[i:i + 200], env=env, check=True)
        return vf_git.git("write-tree", env=env, check=True)
    finally:
        if os.path.exists(idx):
            os.remove(idx)


def find_record(tgt):
    """「QA 결과」 대상 sha(commit·tree, 7자 이상)의 실행 기록 (경로, dict|None, 대상 tree). tree 객체가 없으면(새 clone —
    amend 전 tree는 받지 않는다) .vibe/qa/<tree>.json 이름이 그 sha로 시작하는 기록 하나. 못 찾으면 ('', None, '')."""
    tree = vf_git.tree_of(tgt) if tgt else ""
    if not tree and tgt and os.path.isdir(QA_DIR):
        hits = [f[:-5] for f in os.listdir(QA_DIR) if re.fullmatch(r"[0-9a-f]{40}\.json", f) and f.startswith(tgt)]
        tree = hits[0] if len(hits) == 1 else ""
    if not tree:
        return "", None, ""
    p = record_path(tree)
    if not os.path.exists(p):
        return p, None, tree
    try:
        with open(p, encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, ValueError):
        return p, "unreadable", tree
    return p, rec, tree


def record_path(tree, red=False):
    return f".vibe/qa/{'red-' if red else ''}{tree}.json"


def red_line(rec):
    """'- RED: <tree12> — N개 실패(이름…) (기록 .vibe/qa/red-<tree>.json)'."""
    bad = [k for k, v in (rec.get("tests") or {}).items() if v == "fail"]
    n = len(bad) if bad else (rec["total"] - rec["passed"] - rec.get("skipped", 0) if "passed" in rec else "?")
    names = f"({', '.join(bad[:5])}{' …' if len(bad) > 5 else ''})" if bad else ""
    return f"- RED: {rec['tree'][:12]} — {n}개 실패{names} (기록 {record_path(rec['tree'], red=True)})"


def run(cfg, red=False, goal=""):
    """test_cmd 실행 → 기록. (기록 dict, 붙일 줄들). test_cmd가 없으면 None. red면 red-<tree>.json(+branch·goal·base)·RED 줄.
    RED 기록의 goal(MR 「골」)·base(기준 tree)는 merge가 이 골·이 기준의 RED만 증거로 쓰게 한다(오래된 RED 재사용 방지)."""
    cmd = (cfg.get("test_cmd") or "").strip()
    if not cmd:
        return None, []
    tree = vf_git.snapshot()
    started = datetime.datetime.now().astimezone().isoformat(timespec="microseconds")   # RED→GREEN 순서 비교(A10-05)
    t0 = time.monotonic()
    r = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)   # unittest -v는 stderr로
    secs = round(time.monotonic() - t0, 1)
    out = (r.stdout or b"").decode("utf-8", errors="replace").replace("\r\n", "\n")
    rec = {"schema": vf_git.EVIDENCE_SCHEMA, "tree": tree, "cmd": cmd, "exit": r.returncode, "started": started, "seconds": secs,
           "tail": "\n".join(out.splitlines()[-TAIL:])}
    cnt = parse_counts(out)
    if cnt:   # 통과/전체/건너뜀 수는 출력에서 — 「QA 결과」에 손으로 쓴 수와 대조한다(verify)
        rec["passed"], rec["total"], rec["skipped"] = cnt
    tests = parse_tests(out)
    if tests:   # 테스트별 결과 — 회귀(전에 통과한 테스트가 빠지거나 실패) 대조용
        rec["tests"] = tests
    rec["ok"] = ok(rec)
    if red:
        import mr_check
        rec["branch"] = vf_git.current_branch()
        rec["goal"] = goal
        rec["base"] = mr_check.current_base(cfg)
        if not mr_check.red_valid(rec):   # 명령 오류·이미 통과는 RED가 아니다 — 기록하지 않는다(A9-05: 무효 RED가 뒤에 쓰이지 않게)
            return rec, []
    os.makedirs(QA_DIR, exist_ok=True)
    with open(record_path(tree, red), "w", encoding="utf-8", newline="\n") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
        f.write("\n")
    after = vf_git.snapshot()
    if after != tree:
        try:   # 코드(기록·산출물 제외)가 바뀌었으면 기록 tree의 코드를 돌린 것이 아니다 — 통과로 남기지 않는다(A11-03)
            moved = code_tree(after, cfg) != code_tree(tree, cfg)
        except RuntimeError:
            moved = True
        if moved:
            rec["ok"] = False
            rec["changed_code"] = True
            print("[qa-run] 실패: 테스트가 실행 중 코드를 바꿨다(추적 파일 수정·추적 안 된 파일 생성) — 기록 tree의 코드를 돌린 것이 "
                  "아니다. 테스트가 만드는 파일은 .gitignore에 넣고 다시 돌린다", file=sys.stderr)
            with open(record_path(tree, red), "w", encoding="utf-8", newline="\n") as f:
                json.dump(rec, f, ensure_ascii=False, indent=1)
                f.write("\n")
        else:
            print("[qa-run] 경고: 테스트가 산출물·기록 파일을 바꿨다 — .gitignore에 넣는다", file=sys.stderr)
    if red:
        return rec, [red_line(rec)]
    try:   # 기록 파일을 뺀 코드 tree — 새 clone은 QA 전·후 기록이 달라도 이것으로 대조한다(verify-evidence)
        rec["code_tree"] = code_tree(tree, cfg)
        with open(record_path(tree), "w", encoding="utf-8", newline="\n") as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)
            f.write("\n")
    except RuntimeError as e:
        print(f"[qa-run] 경고: 코드 tree 계산 실패({e}) — 새 clone 대조는 재구성으로", file=sys.stderr)
    verdict = "통과" if ok(rec) else "실패"   # 문구도 ok 기준(A10-08 — exit 0이어도 수를 못 읽으면 실패)
    if all_skipped(rec):
        verdict = "실패(전부 건너뜀)"
    elif rec.get("changed_code"):
        verdict = "실패(테스트가 코드를 바꿈)"
    elif r.returncode == 0 and not ok(rec):
        verdict = "실패(테스트 수를 읽을 수 없음·0건)"
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
        p, rec, tree = find_record(tgt)
        if not tgt:
            miss.append("「QA 결과」 코드 통과인데 대상 commit/tree 없음 — 실행 기록과 대조할 수 없음(qa_run.py)")
        elif not tree:
            miss.append(f"QA 대상 {tgt[:10]}을 찾을 수 없음 — 실행 기록과 대조할 수 없음")
        else:
            if rec is None:
                miss.append(f"코드 통과의 실행 기록 {p} 없음 — 손으로 쓴 '통과'는 증거가 아니다. python qa_run.py로 돌린다")
            else:
                if rec == "unreadable":
                    rec = None
                    miss.append(f"실행 기록 {p}을 읽을 수 없음 — python qa_run.py로 다시 돌린다")
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
    goal = ""
    if red:
        import mr_check
        if not mr:
            print("[qa-run] --red는 --mr <MR 본문>과 함께 — RED 기록에 골을 묶는다(다른 골·기준의 RED는 merge 증거가 아니다)",
                  file=sys.stderr)
            sys.exit(2)
        with open(mr, encoding="utf-8") as f:
            goal = mr_check.mr_goal(f.read())
    rec, lines = run(vf_git.config(), red=red, goal=goal)
    if rec is None:
        print("[qa-run] test_cmd 없음 — 미검증 (.vibe-flow.json에 test_cmd를 둔다. 자동 테스트가 없으면 syntax_check.py)")
        print("- 코드: 미검증 — test_cmd 없음")
        sys.exit(2)
    if red:
        if rec["exit"] == 0:
            print(f"[qa-run] RED가 아님 — 테스트가 이미 통과 — 기록하지 않음. 실패하는 테스트를 먼저 쓴다")
            sys.exit(1)
        import mr_check
        if not lines or not mr_check.red_valid(rec):   # 판정은 red_valid 하나(A11-05)
            print(f"[qa-run] RED 아님 — 실패한 테스트 이름을 출력에서 찾지 못함(실행 오류이거나 상세 출력이 아님 — "
                  f"unittest -v · pytest -v · jest --verbose · vitest --reporter=verbose) "
                  f"(exit {rec['exit']}, 기록하지 않음)")
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
