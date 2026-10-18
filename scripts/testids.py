"""테스트 식별자 — 정규화·추출·존재 확인·실행 기록 대조를 한 곳에서(진단 평가 C6 Top 4).

mr_check(리뷰 CHECKED 근거·'- 회귀:'·QA 대조)와 qa_run(테스트별 결과 키)이 같은 규칙을 쓴다.
  파이썬: test_x · Class.test_x · mod.Class.test_x · path.py::test_x · path.py::Class.test_x · tests/…py
  JS:     'path.test.ts › 묶음 › 이름'(jest) · 'path.test.ts > 묶음 > 이름'(vitest) — 한 줄에 하나, 이름 속 구분자 보존
  '파일:줄'(CODE_REF)은 코드 위치이지 테스트 이름이 아니다.
경로를 적은 식별자는 그 파일의 테스트와만, 경로 없는 한정형은 끝 일치, 맨 이름은 마지막 성분 일치.
"""
import os
import re


# 코드 위치 '파일:줄' — 리뷰 근거로 받지만 테스트 이름은 아니다
CODE_REF = re.compile(r"(?<![\w./\\-])([\w./\\-]+\.[A-Za-z0-9]+):(\d+)(?:-\d+)?(?![\w])")

TEST_ID = re.compile(r"(?<![\w./\\-])(?:[\w./\\-]+\.py::\w+(?:(?:::|\.)\w+)*|(?:[\w.-]+[/\\])*tests?[/\\][\w./\\-]*\.py"
                     r"|(?:[A-Za-z_]\w*\.)*test_\w+)(?![\w./\\-])")


# JS 테스트 식별자(A11-01·12차): qa_run.parse_tests와 같은 모양 — jest '파일 › 묶음 › 이름', vitest '파일 > 묶음 > 이름'.
# JS 테스트 이름에는 공백·쉼표·괄호·';'가 들어갈 수 있다 — 중간에서 자르지 않는다(A13-02·A15-02): 한 줄에 JS 식별자는 하나,
# 파일부터 줄 끝까지에서 끝의 '(파일:줄)' 하나만 뗀다(여럿이면 줄을 나눈다 — CHECKED는 조건마다 한 줄, '- 회귀:'는 줄 여럿)
JS_TEST_START = re.compile(r"(?<![\w./\\-])[\w./\\-]+\.(?:test|spec)\.[cm]?[jt]sx?\s*[›>]")
JS_TRAIL_REF = re.compile(r"\s*\(\s*[\w./\\-]+\.[A-Za-z0-9]+:\d+(?:-\d+)?\s*\)\s*$")
JS_TEST_FILE = re.compile(r"\.(?:test|spec)\.[cm]?[jt]sx?$")


def js_parts(tid):
    """JS 식별자 → (파일, 나머지 문자열 — 정규화한 전체). JS 식별자가 아니면 None.
    구분자는 파일 바로 뒤의 것 하나로 정한다(jest ' › ', vitest ' > ') — 이름 속 '>'·'›'는 쪼개지 않는다(A17-01).
    대조는 이 전체 문자열의 일치로만 한다(구분자 표기만 맞춤)."""
    m = re.match(r"\s*([\w./\\-]+\.(?:test|spec)\.[cm]?[jt]sx?) ([›>]) (\S.*?)\s*$", tid or "")
    if not m:
        return None
    rest = m.group(3)
    # 구분자는 러너가 쓰는 '공백 › 공백'(jest)·'공백 > 공백'(vitest)뿐 — 이름 속 'a›b'·'a>b'는 그대로 둔다(A18-01: 공백을
    # 맞추면 서로 다른 이름 'a›b'와 'a › b'가 같아진다). vitest 표기만 jest 모양으로 바꾼다
    if m.group(2) == ">":
        rest = rest.replace(" > ", " › ")
    return m.group(1).replace("\\", "/"), rest


def js_names(rest):
    """js_parts 나머지의 이름 후보 — 끝에서부터 묶음을 붙여 간다('Suite › a > b'에서 'a > b'처럼 이름에 구분자가 든 경우)."""
    parts = rest.split(" › ")
    return [" › ".join(parts[i:]) for i in range(len(parts))][::-1]


def test_ids(value):
    """'- 코드:'·'- 회귀:'·CHECKED 값의 테스트 식별자(test_x · Class.test_x · path/test_x.py::name · tests/…py ·
    JS '파일 › 묶음 › 이름'·'파일 > 묶음 > 이름')."""
    js, rest = [], []
    for line in (value or "").split("\n"):
        starts = [m.start() for m in JS_TEST_START.finditer(line)]
        if not starts:
            rest.append(line)
            continue
        rest.append(line[:starts[0]])
        # 한 줄의 JS 식별자는 하나(A15-02): 이름에는 ';'·','·괄호는 물론 다른 식별자처럼 보이는 문자열도 들어갈 수 있어
        # 어디서 끊어도 다른 테스트로 바뀔 수 있다 — 첫 시작부터 줄 끝까지, 끝의 '(파일:줄)' 하나만 뗀다. 여럿이면 줄을 나눈다
        seg = line[starts[0]:]
        ref = JS_TRAIL_REF.search(seg)
        js.append((seg[:ref.start()] if ref else seg).strip())
        if ref:
            rest.append(ref.group(0))
    # '파일:줄'(코드 위치)은 테스트 이름이 아니다 — 'test_x (tests/test_a.py:62)'의 경로를 이름으로 뽑지 않는다(E2E S1-E1)
    return js + TEST_ID.findall(CODE_REF.sub(" ", " ; ".join(rest)))


def _test_files():
    skip = {".git", ".vibe", "node_modules", ".venv", "venv", "__pycache__"}
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if d not in skip]
        in_tests = re.search(r"(^|[/\\])tests?([/\\]|$)", root)
        for f in files:
            if in_tests or f.startswith("test") or "_test" in f or JS_TEST_FILE.search(f):
                yield os.path.join(root, f)


def test_exists(tid):
    """식별자가 레포 테스트 파일에 있는가 — 경로면 그 파일이 있어야, 이름이면 마지막 성분이 테스트 파일에 나와야 한다.
    JS 식별자는 그 파일이 있고 마지막 이름이 it('…')·test('…')로 정의돼 있어야."""
    js = js_parts(tid)
    if js:
        f, rest_js = js
        if not os.path.isfile(f):
            return False
        with open(f, encoding="utf-8", errors="ignore") as fh:
            body = fh.read()
        # 이름은 끝 성분부터(이름 속 구분자 가능) — 그 문자열 그대로 it/test 제목으로 정의돼 있어야
        return any(re.search(rf"\b(?:it|test)(?:\.\w+)?\(\s*([\"'`]){re.escape(n)}\1", body) for n in js_names(rest_js))
    path, _, rest = tid.partition("::")
    if rest and path.endswith(".py") and re.search(r"::|\.", rest):   # 'path.py::Class.test_x' — 그 클래스가 그 파일에 있어야(A17-02)
        cls = re.split(r"::|\.", rest)[0]
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                if not re.search(rf"^\s*class\s+{re.escape(cls)}\b", fh.read(), re.M):
                    return False
        except OSError:
            return False
    if path.endswith(".py") and not os.path.isfile(path):
        return False
    # 'path.py::Class.test_x'(pytest 경로 + unittest 점 이름 — E2E S3 t3y2)도 마지막 성분이 정의 이름
    name = re.split(r"::|\.", rest)[-1] if rest else ("" if path.endswith(".py") else tid.split(".")[-1])
    if not name:
        return True
    n = re.escape(name)   # 정의만 — 주석·문자열 속 이름은 테스트가 아니다
    pat = re.compile(rf"^\s*(?:async\s+)?def\s+{n}\s*\(|^\s*(?:export\s+)?(?:async\s+)?function\s*\*?\s*{n}\s*\("
                     rf"|\b(?:it|test)(?:\.\w+)?\(\s*([\"'`]){n}\1", re.M)
    for p in ([path] if rest else _test_files()):
        try:
            with open(p, encoding="utf-8", errors="ignore") as f:
                if pat.search(f.read()):
                    return True
        except OSError:
            continue
    return False




def _last(name):
    """테스트 이름의 마지막 성분 — 'a.B.test_x' · 'p.py::test_x' · 'test_x (a.B.test_x)' → test_x."""
    parts = [x for x in re.split(r"::|[.\s()]+", name) if x]
    return parts[-1] if parts else ""


def _qual(name):
    """비교용 한정 이름 — 'test_x (a.B.test_x)'는 괄호 안, 경로 구분자·'::'는 '.', '.py'는 뺀다."""
    m = re.fullmatch(r"\s*\S+\s*\(([^()]+)\)\s*", name)
    n = (m.group(1) if m else name).strip()
    return re.sub(r"\.py(?=\.|$)", "", re.sub(r"::|[/\\]", ".", n))


def test_match(rid, recorded):
    """'- 회귀:' 식별자와 기록 이름 — 맨 이름(test_x)은 마지막 성분, 한정형(B.test_x · p.py::test_x)은 끝이 그 한정형.
    JS 식별자는 파일·묶음·이름을 구분자(›·>)와 무관하게 전부 같아야."""
    jr, jk = js_parts(rid), js_parts(recorded)
    if jr or jk:
        return bool(jr and jk and jr == jk)
    q = _qual(rid)
    if "." not in q:
        return _last(recorded) == q
    r = _qual(recorded)
    if re.search(r"[/\\]|\.py(?:::|$)", rid):   # 경로를 적은 식별자는 그 파일의 테스트만 — 접미 일치로 다른 경로를 받지 않는다(A17-02)
        return r == q
    return r == q or r.endswith("." + q)
