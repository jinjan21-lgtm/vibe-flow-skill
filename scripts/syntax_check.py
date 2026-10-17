#!/usr/bin/env python3
"""자동 테스트가 없는 레포의 최소 QA 코드 단계: JS 파일 문법 검사 (node --check).

  python syntax_check.py <폴더 또는 파일> [...]

결과를 "통과/전체"로 출력하고, 하나라도 실패하면 exit 1. node가 없거나 검사할 파일이 0개면 exit 2(미검증).
"""
import os
import shutil
import subprocess
import sys


def main(targets):
    node = shutil.which("node")
    if not node:
        print("[syntax] node 없음 — 미검증")
        sys.exit(2)
    files = []
    for t in targets:
        if os.path.isfile(t):
            files.append(t)
        for root, _, names in os.walk(t):
            files += [os.path.join(root, n) for n in sorted(names) if n.endswith((".js", ".mjs"))]
    if not files:
        print(f"[syntax] 검사할 .js/.mjs 파일 없음 — 미검증 (대상: {' '.join(targets)})")
        sys.exit(2)
    bad = []
    for f in files:
        r = subprocess.run([node, "--check", f], capture_output=True, text=True, encoding="utf-8")
        if r.returncode:
            bad.append((f, (r.stderr.strip().splitlines() or ["?"])[-1]))
    print(f"[syntax] {len(files) - len(bad)}/{len(files)} 통과")
    for f, e in bad:
        print(f"  실패 {f}: {e}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        s.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
