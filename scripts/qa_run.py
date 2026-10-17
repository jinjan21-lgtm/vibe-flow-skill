#!/usr/bin/env python3
"""QA 코드 단계: test_cmd를 실제로 돌리고 그 결과를 작업물 tree에 묶어 남긴다. 레포 루트에서 실행.

  python qa_run.py [--mr <mr 본문>]

  - 지금 작업물(미커밋 포함)의 tree(vf_git.snapshot)를 잡고 .vibe-flow.json의 test_cmd를 셸로 실행
  - .vibe/qa/<tree>.json에 tree·cmd·exit·started·seconds·tail(출력 마지막 200줄) 기록
  - 「QA 결과」에 붙일 줄을 출력. --mr이면 그 본문의 '대상 tree'·'코드' 줄을 바로 고친다
  - 종료코드: 통과 0, 실패 1, test_cmd 없음 2(미검증)

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


def record_path(tree):
    return f".vibe/qa/{tree}.json"


def run(cfg):
    """test_cmd 실행 → 기록. (기록 dict, 붙일 줄들). test_cmd가 없으면 None."""
    cmd = (cfg.get("test_cmd") or "").strip()
    if not cmd:
        return None, []
    tree = vf_git.snapshot()
    started = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    t0 = time.monotonic()
    r = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    secs = round(time.monotonic() - t0, 1)
    out = (r.stdout or b"").decode("utf-8", errors="replace").replace("\r\n", "\n")
    rec = {"tree": tree, "cmd": cmd, "exit": r.returncode, "started": started, "seconds": secs,
           "tail": "\n".join(out.splitlines()[-TAIL:])}
    os.makedirs(QA_DIR, exist_ok=True)
    with open(record_path(tree), "w", encoding="utf-8", newline="\n") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
        f.write("\n")
    if vf_git.snapshot() != tree:
        print("[qa-run] 경고: 테스트가 작업물을 바꿨다(추적 대상 파일 생성·수정) — 기록 tree는 실행 전 상태다. "
              "산출물을 .gitignore에 넣고 다시 돌린다", file=sys.stderr)
    verdict = "통과" if r.returncode == 0 else "실패"
    lines = [f"- 대상 tree: {tree}",
             f"- 코드: {verdict} — {cmd} exit {r.returncode}, {secs}s (기록 {record_path(tree)})"]
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
    for pat, line in ((r"^\s*-\s*대상 (?:commit|tree):.*$", lines[0]), (r"^\s*-\s*코드:.*$", lines[1])):
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


def evidence_paths(qa):
    """마크다운 이미지·링크 대상 중 http(s)가 아닌 것(레포 루트 기준 경로)."""
    out = []
    for a, b in re.findall(r"!?\[[^\]]*\]\(\s*(?:<([^>\n]+)>|([^)\s]+))(?:\s+\"[^\"]*\")?\s*\)", qa):
        t = (a or b).strip()
        if re.match(r"(?i)https?://", t) or t.startswith("#"):
            continue
        out.append(unquote(t.split("#")[0]))
    return [p for p in out if p]


def _verify(qa, cfg):
    miss = []
    if re.search(rf"^\s*-\s*코드:\s*{PASS}", qa, re.M):
        m = re.search(TARGET, qa)
        tree = vf_git.tree_of(m.group(1)) if m else ""
        if not m:
            miss.append("「QA 결과」 코드 통과인데 대상 commit/tree 없음 — 실행 기록과 대조할 수 없음(qa_run.py)")
        elif not tree:
            miss.append(f"QA 대상 {m.group(1)[:10]}을 찾을 수 없음 — 실행 기록과 대조할 수 없음")
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
                elif rec is not None:
                    miss.append(f"실행 기록 {p} 형식이 아님")
    if re.search(rf"^\s*-\s*브라우저:\s*{PASS}", qa, re.M):
        paths = evidence_paths(qa)
        if not paths:
            miss.append("브라우저 통과인데 증거 캡처 파일 링크 없음 — '- 증거: ![A1](<레포 기준 경로>.png)'로 실제 파일을 붙인다")
        for p in paths:
            if not os.path.isfile(p):
                miss.append(f"브라우저 증거 파일 없음: {p}")
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
    if a[:1] == ["--mr"] and len(a) == 2:
        mr = a[1]
    elif a:
        sys.exit(__doc__)
    if mr and not os.path.exists(mr):
        print(f"[qa-run] MR 본문 없음: {mr}", file=sys.stderr)
        sys.exit(2)
    rec, lines = run(vf_git.config())
    if rec is None:
        print("[qa-run] test_cmd 없음 — 미검증 (.vibe-flow.json에 test_cmd를 둔다. 자동 테스트가 없으면 syntax_check.py)")
        print("- 코드: 미검증 — test_cmd 없음")
        sys.exit(2)
    if rec["exit"]:
        print(f"[qa-run] 출력 마지막 {min(20, TAIL)}줄:\n" + "\n".join(rec["tail"].splitlines()[-20:]))
    print("[qa-run] 「QA 결과」에 붙일 줄:")
    print("\n".join(lines))
    if mr:
        fill_mr(mr, lines)
        print(f"[qa-run] {mr}의 「QA 결과」 대상·코드 줄을 갱신")
    sys.exit(0 if rec["exit"] == 0 else 1)


if __name__ == "__main__":
    for st in (sys.stdout, sys.stderr):
        st.reconfigure(encoding="utf-8")
    main()
