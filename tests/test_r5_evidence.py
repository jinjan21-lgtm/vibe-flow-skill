"""R5 회귀: QA 대상 파싱이 주석을 무시(H-01), 여러 골 MR의 export-evidence(H-02), 다른 브랜치·기준 리뷰 제외(H-03),
precheck 착수 가능성, QA 테스트 수 파싱, RED 기록(--red --mr: goal·base).
새 clone 재검증(verify-evidence 재연)은 실제 흐름으로 tests/test_r6_engine.py가 본다(로컬 merge와 같은 판정).
실행: python -m unittest tests/test_r5_evidence.py -v (레포 루트)"""
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_scripts import GOAL, PY, SCRIPTS, sh  # noqa: E402
from test_c2_record import MR_FILE, PersonalRepo, init_repo, write  # noqa: E402

COMMENT_SHA = "a" * 40   # 주석 안의 예시 sha — 대상이 아니다


def mr_with_comment():
    """「QA 결과」 첫머리 안내 주석에 sha가 든 MR(템플릿 예시를 sha로 바꿔 둔 경우)."""
    return MR_FILE.replace("## QA 결과\n", f"## QA 결과\n<!-- - 대상 tree: {COMMENT_SHA} (예시) -->\n")


def ctx(d):
    """지금 브랜치·기준 tree(cfg base=main과의 merge-base) — review.py 기록 도장과 같은 값."""
    br = sh("git", "symbolic-ref", "--short", "HEAD", cwd=d).stdout.strip()
    mb = sh("git", "merge-base", "main", "HEAD", cwd=d).stdout.strip()
    return br, sh("git", "rev-parse", f"{mb}^{{tree}}", cwd=d).stdout.strip()


# ---------- H-01 ----------
class QaTargetCommentTest(PersonalRepo):
    def test_helper_ignores_comment(self):
        import qa_run
        importlib.reload(qa_run)
        t = f"<!-- - 대상 tree: {COMMENT_SHA} -->\n- 대상 tree: {'b' * 40}\n"
        self.assertEqual(qa_run.target(t), "b" * 40)
        self.assertEqual(qa_run.target(f"<!-- 대상 commit: {COMMENT_SHA} -->\n"), "")

    def test_check_record_ignores_comment_sha(self):
        self.assertEqual(self.ho("claim", "G-001", "거래처 검색", "feat/G-001-search").returncode, 0)
        self.work_and_record(mr=mr_with_comment())
        r = self.ho("check-record")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_export_ignores_comment_sha(self):
        tree = "c" * 40
        write(self.d, ".vibe/mr-G-001.md", mr_with_comment().replace("{tree}", tree))
        write(self.d, f".vibe/qa/{tree}.json", json.dumps({"tree": tree, "cmd": "t", "exit": 0}))
        br, base = ctx(self.d)
        write(self.d, ".vibe/review/r1.txt", "VERDICT: CONFIRM\n")
        write(self.d, ".vibe/review/r1.tree", f"{tree}\ngoal: G-001\nbranch: {br}\nbase: {base}\n")
        r = self.ho("export-evidence", "G-001")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_verify_ignores_comment_sha(self):
        os.chdir(self.d)
        try:
            write(self.d, ".vibe-flow.json", json.dumps({"base": "main", "test_cmd": "t"}))
            import qa_run
            import vf_git
            importlib.reload(qa_run)
            tree = vf_git.snapshot()
            write(self.d, f".vibe/qa/{tree}.json", json.dumps({"schema": 2, "tree": tree, "cmd": "t", "exit": 0,
                                                               "passed": 1, "total": 1}))
            qa = f"<!-- - 대상 tree: {COMMENT_SHA} -->\n- 대상 tree: {tree}\n- 코드: 통과 — x\n"
            self.assertEqual(qa_run.verify(qa, vf_git.config()), [])
        finally:
            os.chdir(os.path.dirname(SCRIPTS))


# ---------- H-02 · H-03 ----------
class ExportMultiGoalTest(PersonalRepo):
    def setUp(self):
        super().setUp()
        write(self.d, "docs/goals/G-002-filter.md", GOAL.format(gid="G-002", st="active"))
        self.tree = "c" * 40
        self.br, self.base = ctx(self.d)

    def stamp(self, name, goal, br=None, base=None, tree=True):
        head = f"{self.tree}\n" if tree else ""
        write(self.d, f".vibe/review/{name}",
              f"{head}goal: {goal}\nbranch: {br or self.br}\nbase: {base or self.base}\n")

    def seed(self, goals="G-001, G-002"):
        mr = MR_FILE.replace("## 골\nG-001 거래처 검색", f"## 골\n{goals} 거래처 검색").replace("{tree}", self.tree)
        write(self.d, ".vibe/mr-G-001.md", mr)
        write(self.d, f".vibe/qa/{self.tree}.json", json.dumps({"tree": self.tree, "cmd": "t", "exit": 0}))

    def read(self, p):
        return open(os.path.join(self.d, p), encoding="utf-8").read()

    def test_two_goals_export_for_each(self):   # H-02
        self.seed()
        write(self.d, ".vibe/review/d1.txt", "설계 원문\nVERDICT: CONFIRM\n")
        self.stamp("d1.meta", "G-001,G-002", tree=False)
        write(self.d, ".vibe/review/r1.txt", "리뷰 원문\nVERDICT: CONFIRM\n")
        self.stamp("r1.tree", "G-001,G-002")
        r = self.ho("export-evidence", "G-001")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for g in ("G-001", "G-002"):
            self.assertIn("리뷰 원문", self.read(f"docs/mr/{g}-review.md"))
            self.assertIn("설계 원문", self.read(f"docs/mr/{g}-review.md"))
            self.assertEqual(json.loads(self.read(f"docs/mr/{g}-qa.json"))["tree"], self.tree)
            self.assertIn("G-002", self.read(f"docs/mr/{g}.md"))

    def test_second_goal_id_finds_shared_mr(self):   # H-02: G-002로 불러도 그 골을 적은 MR을 찾는다
        self.seed()
        write(self.d, ".vibe/review/r1.txt", "리뷰 원문\nVERDICT: CONFIRM\n")
        self.stamp("r1.tree", "G-001,G-002")
        r = self.ho("export-evidence", "G-002")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.d, "docs/mr/G-001-review.md")))
        self.assertTrue(os.path.exists(os.path.join(self.d, "docs/mr/G-002-review.md")))

    def test_other_branch_or_base_excluded(self):   # H-03
        self.seed("G-001")
        write(self.d, ".vibe/review/r1.txt", "지금 리뷰\nVERDICT: CONFIRM\n")
        self.stamp("r1.tree", "G-001")
        write(self.d, ".vibe/review/r2.txt", "다른 브랜치 리뷰\nVERDICT: CHANGES\n")
        self.stamp("r2.tree", "G-001", br="feat/G-001-old")
        write(self.d, ".vibe/review/d1.txt", "옛 기준 설계\nVERDICT: CONFIRM\n")
        self.stamp("d1.meta", "G-001", base="e" * 40, tree=False)
        r = self.ho("export-evidence", "G-001")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rv = self.read("docs/mr/G-001-review.md")
        self.assertIn("지금 리뷰", rv)
        self.assertNotIn("다른 브랜치 리뷰", rv)
        self.assertNotIn("옛 기준 설계", rv)


# ---------- precheck 착수 가능성 ----------
class PrecheckReadinessTest(PersonalRepo):
    def run_pre(self, path_dirs, *args):
        env = {**os.environ, "PATH": os.pathsep.join(path_dirs)}
        return subprocess.run([PY, os.path.join(SCRIPTS, "handoff.py"), "precheck", *args], cwd=self.d, env=env,
                              capture_output=True, text=True, encoding="utf-8")

    def base_path(self):
        return [os.path.dirname(shutil.which("git")), os.path.dirname(PY)]

    def fake_codex(self):
        d = os.path.join(self.root, "fakebin")
        os.makedirs(d, exist_ok=True)
        if os.name == "nt":
            write(d, "codex.cmd", "@echo off\r\n")
        else:
            write(d, "codex", "#!/bin/sh\n")
            os.chmod(os.path.join(d, "codex"), 0o755)
        return d

    def cfg(self, **kw):
        write(self.d, ".vibe-flow.json", json.dumps({"base": "main", **kw}))

    def test_missing_codex_blocks(self):
        self.cfg(test_cmd="python -c pass")
        r = self.run_pre(self.base_path())
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("[precheck] 착수 불가", r.stdout)
        self.assertIn("codex", r.stdout.split("착수 불가")[1])

    def test_missing_test_cmd_blocks(self):
        r = self.run_pre(self.base_path() + [self.fake_codex()])
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("test_cmd", r.stdout.split("착수 불가")[1])

    def test_ready_tests_not_run_by_default(self):
        self.cfg(test_cmd=f'"{PY}" -c "open(\'ran.txt\',\'w\')"')
        r = self.run_pre(self.base_path() + [self.fake_codex()])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("착수 불가", r.stdout)
        self.assertIn("미실행", r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.d, "ran.txt")))

    def test_run_tests_flag(self):
        self.cfg(test_cmd=f'"{PY}" -c "open(\'ran.txt\',\'w\')"')
        r = self.run_pre(self.base_path() + [self.fake_codex()], "--run-tests")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.d, "ran.txt")))

    def test_codex_false_still_required(self):   # 단일 정책: 골 판정·설계 확인·리뷰가 모두 Codex — 면제 없음
        self.cfg(test_cmd="python -c pass", codex=False)
        r = self.run_pre(self.base_path())
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("codex", r.stdout.split("착수 불가")[1])


# ---------- QA 테스트 수 ----------
class QaCountTest(unittest.TestCase):
    def setUp(self):
        import qa_run
        self.q = importlib.reload(qa_run)

    def test_parse_formats(self):
        c = self.q.parse_counts
        self.assertEqual(c("....\n----\nRan 14 tests in 3.1s\n\nOK\n")[:2], (14, 14))
        self.assertEqual(c("Ran 14 tests in 3.1s\n\nOK (skipped=2)\n")[:2], (12, 14))
        self.assertEqual(c("Ran 10 tests in 1s\n\nFAILED (failures=2, errors=1)\n")[:2], (7, 10))
        self.assertEqual(c("===== 3 passed, 1 failed, 2 skipped in 0.12s =====\n")[:2], (3, 6))
        self.assertEqual(c("===== 5 passed in 0.12s =====\n")[:2], (5, 5))
        self.assertEqual(c("Tests:       1 failed, 13 passed, 14 total\n")[:2], (13, 14))
        self.assertEqual(c(" Tests  14 passed (14)\n")[:2], (14, 14))
        self.assertEqual(c(" Tests  1 failed | 13 passed (14)\n")[:2], (13, 14))
        self.assertIsNone(c("ok 3/3\n"))

    def test_run_records_counts_and_line(self):
        d = tempfile.mkdtemp(prefix="vf-r5q-")
        old = os.getcwd()
        try:
            init_repo(d)
            cmd = f'"{PY}" -c "print(\'Ran 4 tests in 0.1s\'); print(); print(\'OK\')"'
            write(d, ".vibe-flow.json", json.dumps({"base": "main", "test_cmd": cmd}))
            write(d, ".gitignore", ".vibe/\n")
            sh("git", "add", "-A", cwd=d)
            sh("git", "commit", "-qm", "seed", cwd=d)
            os.chdir(d)
            import vf_git
            rec, lines = self.q.run(vf_git.config())
            self.assertEqual((rec["passed"], rec["total"]), (4, 4))
            self.assertRegex(lines[1], r"^- 코드: 통과 — 4/4 통과, ")
            tree = rec["tree"]
            ok = f"- 대상 tree: {tree}\n- 코드: 통과 — 4/4 통과\n"
            self.assertEqual(self.q.verify(ok, vf_git.config()), [])
            bad = self.q.verify(f"- 대상 tree: {tree}\n- 코드: 통과 — 14/14 통과\n", vf_git.config())
            self.assertTrue(any("4/4" in x for x in bad), bad)
        finally:
            os.chdir(old)
            shutil.rmtree(d, ignore_errors=True)


# ---------- 외부 감사 G-06: python 없음도 착수 불가 ----------
class PrecheckPythonTest(PrecheckReadinessTest):
    def fake(self, name):
        d = os.path.join(self.root, f"bin-{name}")
        os.makedirs(d, exist_ok=True)
        if os.name == "nt":
            write(d, f"{name}.cmd", "@echo off\r\n")
        else:
            write(d, name, "#!/bin/sh\n")
            os.chmod(os.path.join(d, name), 0o755)
        return d

    def test_missing_python_blocks(self):
        self.cfg(test_cmd="python -c pass")
        gitdir = os.path.dirname(shutil.which("git"))
        if any(shutil.which(n, path=gitdir) for n in ("python", "python3", "py")):
            self.skipTest("git 폴더에 python이 있음")
        r = self.run_pre([gitdir, self.fake_codex()])
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("python", r.stdout.split("착수 불가")[1])

    def test_py_launcher_counts(self):
        self.cfg(test_cmd="python -c pass")
        r = self.run_pre([os.path.dirname(shutil.which("git")), self.fake("py"), self.fake_codex()])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


# ---------- 외부 감사 G-08: 건너뛴 테스트는 통과가 아니다 ----------
class QaSkipTest(unittest.TestCase):
    def setUp(self):
        import qa_run
        self.q = importlib.reload(qa_run)

    def test_skipped_counts(self):
        c = self.q.parse_counts
        self.assertEqual(c("Ran 3 tests in 0.1s\n\nOK (skipped=1)\n"), (2, 3, 1))
        self.assertEqual(c("===== 2 passed, 1 skipped in 0.12s =====\n"), (2, 3, 1))
        self.assertEqual(c("Ran 4 tests in 0.1s\n\nFAILED (failures=1, skipped=1)\n"), (2, 4, 1))
        self.assertEqual(c("Tests:       1 skipped, 13 passed, 14 total\n"), (13, 14, 1))
        self.assertEqual(c(" Tests  13 passed | 1 skipped (14)\n"), (13, 14, 1))
        self.assertEqual(c("Ran 4 tests in 0.1s\n\nOK\n"), (4, 4, 0))

    def test_run_line_and_record(self):
        d = tempfile.mkdtemp(prefix="vf-r5s-")
        old = os.getcwd()
        try:
            init_repo(d)
            cmd = f'"{PY}" -c "print(\'Ran 3 tests in 0.1s\'); print(); print(\'OK (skipped=1)\')"'
            write(d, ".vibe-flow.json", json.dumps({"base": "main", "test_cmd": cmd}))
            write(d, ".gitignore", ".vibe/\n")
            sh("git", "add", "-A", cwd=d)
            sh("git", "commit", "-qm", "seed", cwd=d)
            os.chdir(d)
            import vf_git
            rec, lines = self.q.run(vf_git.config())
            self.assertEqual((rec["passed"], rec["total"], rec["skipped"]), (2, 3, 1))
            self.assertIn("2/3 통과(1 건너뜀)", lines[1])
            self.assertEqual(self.q.verify(f"- 대상 tree: {rec['tree']}\n{lines[1]}\n", vf_git.config()), [])
        finally:
            os.chdir(old)
            shutil.rmtree(d, ignore_errors=True)


# ---------- 외부 감사 J-05: check-record도 QA cmd = 커밋된 test_cmd ----------
class CheckRecordCmdTest(PersonalRepo):
    def seed_cfg(self, cmd):
        write(self.d, ".vibe-flow.json", json.dumps({"base": "main", "test_cmd": cmd}))
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-qm", "cfg", cwd=self.d)
        self.assertEqual(self.ho("claim", "G-001", "거래처 검색", "feat/G-001-search").returncode, 0)
        self.work_and_record(mr=MR_FILE)   # 기록 cmd는 "t"
        return self.ho("check-record")

    def test_cmd_differs_from_committed_config(self):
        r = self.seed_cfg("python -m unittest")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertRegex(r.stdout, r"test_cmd")

    def test_cmd_same_passes(self):
        r = self.seed_cfg("t")
        self.assertEqual(r.returncode, 0, r.stdout)



# ---------- 테스트별 결과 기록(tests) ----------
UT_V = """test_a (pkg.mod.T.test_a) ... ok
test_b (pkg.mod.T.test_b) ... FAIL
test_c (pkg.mod.T.test_c) ... ERROR
test_d (pkg.mod.T.test_d) ... skipped 'no db'
test_e (pkg.mod.T.test_e)
설명 줄 ... ok

----------------------------------------------------------------------
Ran 5 tests in 0.1s

FAILED (failures=1, errors=1, skipped=1)
"""
PY_V = """tests/test_x.py::TestX::test_a PASSED                                 [ 25%]
tests/test_x.py::TestX::test_b FAILED                                 [ 50%]
tests/test_x.py::test_c SKIPPED (why)                                 [ 75%]
tests/test_x.py::test_d ERROR                                         [100%]
===== 1 passed, 1 failed, 1 skipped, 1 error in 0.12s =====
"""


def fake_cmd(out, code):
    """out을 stderr로 내고 code로 끝나는 명령(unittest -v처럼)."""
    src = os.path.join(tempfile.mkdtemp(prefix="vf-out-"), "o.txt")
    with open(src, "w", encoding="utf-8") as f:
        f.write(out)
    return f'"{PY}" -c "import sys; sys.stderr.write(open(r\'{src}\', encoding=\'utf-8\').read()); sys.exit({code})"'


class QaTestsParseTest(unittest.TestCase):
    def setUp(self):
        import qa_run
        self.q = importlib.reload(qa_run)

    def test_unittest_verbose(self):
        self.assertEqual(self.q.parse_tests(UT_V), {"pkg.mod.T.test_a": "ok", "pkg.mod.T.test_b": "fail",
                                                     "pkg.mod.T.test_c": "fail", "pkg.mod.T.test_d": "skip",
                                                     "pkg.mod.T.test_e": "ok"})

    def test_pytest_verbose(self):
        self.assertEqual(self.q.parse_tests(PY_V), {"tests/test_x.py::TestX::test_a": "ok",
                                                     "tests/test_x.py::TestX::test_b": "fail",
                                                     "tests/test_x.py::test_c": "skip", "tests/test_x.py::test_d": "fail"})

    def test_nothing(self):
        self.assertEqual(self.q.parse_tests("Ran 3 tests in 0.1s\n\nOK\n"), {})


class QaRunRepo(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="vf-r6-")
        init_repo(self.d)
        write(self.d, ".gitignore", ".vibe/\n")
        write(self.d, "app.py", "# app\n")
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-qm", "seed", cwd=self.d)

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def cfg(self, cmd):
        write(self.d, ".vibe-flow.json", json.dumps({"base": "main", "test_cmd": cmd}))

    def qa(self, *args):
        return subprocess.run([PY, os.path.join(SCRIPTS, "qa_run.py"), *args], cwd=self.d,
                              capture_output=True, text=True, encoding="utf-8")

    def rec(self, name):
        with open(os.path.join(self.d, ".vibe", "qa", name), encoding="utf-8") as f:
            return json.load(f)


class QaTestsRecordTest(QaRunRepo):
    def test_stderr_verbose_recorded(self):
        self.cfg(fake_cmd(UT_V, 1))
        r = self.qa()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        tree = re.search(r"대상 tree: ([0-9a-f]{40})", r.stdout).group(1)
        rec = self.rec(f"{tree}.json")
        self.assertEqual(rec["tests"]["pkg.mod.T.test_b"], "fail")
        self.assertEqual(len(rec["tests"]), 5)

    def test_no_tests_key_when_unparsed(self):
        self.cfg(fake_cmd("Ran 1 test in 0s\n\nOK\n", 0))
        r = self.qa()
        tree = re.search(r"대상 tree: ([0-9a-f]{40})", r.stdout).group(1)
        self.assertNotIn("tests", self.rec(f"{tree}.json"))


# ---------- RED 증거 ----------
class QaRedTest(QaRunRepo):
    def test_red_failing_run_recorded(self):
        self.cfg(fake_cmd(UT_V, 1))
        write(self.d, "mr.md", "## 완료 조건\n- [ ] x\n\n## QA 결과\n<!-- - RED: 예시 -->\n(진행 전)\n\n## 리뷰 기록\n")
        r = self.qa("--red", "--mr", "mr.md")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        m = re.search(r"^- RED: ([0-9a-f]{12}) — 2개 실패\(pkg\.mod\.T\.test_b, pkg\.mod\.T\.test_c\) "
                      r"\(기록 \.vibe/qa/red-([0-9a-f]{40})\.json\)$", r.stdout, re.M)
        self.assertTrue(m, r.stdout)
        self.assertTrue(m.group(2).startswith(m.group(1)))
        rec = self.rec(f"red-{m.group(2)}.json")
        self.assertEqual((rec["tree"], rec["exit"]), (m.group(2), 1))
        self.assertEqual(rec["tests"]["pkg.mod.T.test_c"], "fail")
        with open(os.path.join(self.d, "mr.md"), encoding="utf-8") as f:
            mr = f.read()
        qa = mr.split("## QA 결과")[1].split("## 리뷰 기록")[0]
        self.assertIn(m.group(0), re.sub(r"<!--.*?-->", "", qa, flags=re.S))
        self.assertIn("<!-- - RED: 예시 -->", qa)
        self.assertFalse(os.path.exists(os.path.join(self.d, ".vibe", "qa", f"{m.group(2)}.json")))

    def red_mr(self):
        write(self.d, "mr.md", "## 골\nG-001 거래처 검색\n## 완료 조건\n- [ ] x\n\n## QA 결과\n(진행 전)\n")
        return "mr.md"

    def test_red_records_goal_and_base(self):   # merge는 이 골·이 기준의 RED만 증거로 쓴다
        import vf_git
        self.cfg(fake_cmd(UT_V, 1))
        r = self.qa("--red", "--mr", self.red_mr())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        tree = re.search(r"red-([0-9a-f]{40})\.json", r.stdout).group(1)
        rec = self.rec(f"red-{tree}.json")
        base = sh("git", "rev-parse", "main^{tree}", cwd=self.d).stdout.strip()
        self.assertEqual((rec["goal"], rec["base"], rec["branch"], rec["schema"]),
                         ("G-001", base, "main", vf_git.EVIDENCE_SCHEMA))

    def test_red_but_passed(self):
        self.cfg(fake_cmd("Ran 1 test in 0s\n\nOK\n", 0))
        r = self.qa("--red", "--mr", self.red_mr())
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("RED가 아님 — 테스트가 이미 통과", r.stdout + r.stderr)


class ExportRedTest(PersonalRepo):
    def seed(self):
        tree = "c" * 40
        write(self.d, ".vibe/mr-G-001.md", MR_FILE.replace("{tree}", tree))
        # GREEN: RED의 실패 테스트가 ok이고(tests), 모든 RED보다 뒤에 돌았다(started) — select_red가 RED→GREEN을 대조한다
        write(self.d, f".vibe/qa/{tree}.json", json.dumps(
            {"schema": 2, "tree": tree, "cmd": "t", "exit": 0, "passed": 1, "total": 1,
             "started": "2026-10-18T13:00:00.000000+09:00", "tests": {"tests.test_app.T.test_search": "ok"}}))
        br, base = ctx(self.d)
        write(self.d, ".vibe/review/r1.txt", "VERDICT: CONFIRM\n")
        write(self.d, ".vibe/review/r1.tree", f"{tree}\ngoal: G-001\nbranch: {br}\nbase: {base}\n")

    def red(self, ch, branch, started, goal="G-001", base=None):
        write(self.d, f".vibe/qa/red-{ch * 40}.json", json.dumps(
            {"tree": ch * 40, "cmd": "t", "exit": 1, "branch": branch, "started": started, "goal": goal,
             "base": ctx(self.d)[1] if base is None else base, "schema": 2,
             # 실패한 테스트가 있어야 RED다(red_valid — 명령 오류는 RED가 아님)
             "passed": 0, "total": 1, "tests": {"tests.test_app.T.test_search": "fail"}}))

    def test_export_copies_latest_red_of_branch(self):   # 같은 브랜치·이 골·지금 기준의 가장 최근 RED만
        sh("git", "checkout", "-q", "-b", "feat/G-001-search", cwd=self.d)
        self.red("d", "other", "2026-10-18T10:00:00+09:00")
        self.red("e", "feat/G-001-search", "2026-10-18T09:00:00+09:00")
        self.red("f", "feat/G-001-search", "2026-10-18T09:30:00+09:00")
        self.red("a", "feat/G-001-search", "2026-10-18T11:00:00+09:00", goal="G-099")   # 다른 골
        self.red("b", "feat/G-001-search", "2026-10-18T11:30:00+09:00", base="e" * 40)   # 리베이스 전 기준
        self.red("9", "feat/G-001-search", "2026-10-18T12:00:00+09:00", goal="")   # 골 표시 없는 예전 기록
        self.red("8", "feat/G-001-search", "2026-10-18T14:00:00+09:00")   # GREEN(13:00) 뒤에 돌린 RED
        self.seed()
        r = self.ho("export-evidence", "G-001")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(os.path.join(self.d, "docs", "mr", "G-001-red.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["tree"], "f" * 40)

    def test_export_without_red_ok(self):
        self.seed()
        write(self.d, "docs/mr/G-001-red.json", "{}\n")   # 예전에 내보낸 RED 사본 — 지금 고른 RED가 없으면 지운다
        r = self.ho("export-evidence", "G-001")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.d, "docs", "mr", "G-001-red.json")))


# ---------- 착수 가능성: 커밋 안 된 변경 ----------
class PrecheckDirtyTest(PrecheckReadinessTest):
    def test_dirty_tracked_blocks(self):
        self.cfg(test_cmd="python -c pass")
        write(self.d, "app.py", "# 바꿈\n", "a")
        r = self.run_pre(self.base_path() + [self.fake_codex()])
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("[precheck] 착수 불가: 커밋 안 된 변경", r.stdout)
        self.assertIn("app.py", r.stdout)

    def test_untracked_ok(self):
        self.cfg(test_cmd="python -c pass")
        write(self.d, "new.txt", "x\n")
        r = self.run_pre(self.base_path() + [self.fake_codex()])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


# ---------- 외부 감사 E-01: PLAN 링크 규칙을 주어진 PLAN.md 본문으로 ----------
class IsRecordPlanTextTest(unittest.TestCase):
    def test_plan_text_param(self):
        import mr_check
        cfg = {"handoff_dir": "docs/handoff", "goals_dir": "docs/goals"}
        f = "docs/handoff/PLAN-ui.md"
        self.assertTrue(mr_check.is_record(f, cfg, plan="# 계획\n- [ui](PLAN-ui.md)\n"))
        self.assertFalse(mr_check.is_record(f, cfg, plan="# 계획\n"))


class ExportStampTest(PersonalRepo):   # E-02: export가 회차 도장을 사본에 넣는다
    def test_stamp_in_review_copy(self):
        tree = "c" * 40
        write(self.d, ".vibe/mr-G-001.md", MR_FILE.replace("{tree}", tree))
        write(self.d, f".vibe/qa/{tree}.json", json.dumps({"tree": tree, "cmd": "t", "exit": 0}))
        br, base = ctx(self.d)
        write(self.d, ".vibe/review/r1.txt", "VERDICT: CONFIRM\n")
        write(self.d, ".vibe/review/r1.tree", f"{tree}\ngoal: G-001\nbranch: {br}\nbase: {base}\nconds: c1\ncontract: k1\n")
        r = self.ho("export-evidence", "G-001")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rv = open(os.path.join(self.d, "docs/mr/G-001-review.md"), encoding="utf-8").read()
        self.assertRegex(rv, rf"## r1\.txt[^\n]*\n<!-- stamp\ntree: {tree}\n(?:.*\n)*?conds: c1\ncontract: k1\n")


# ---------- 외부 감사 G-07 잔여: 정의만 테스트로 센다 ----------
class TestExistsDefTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="vf-te-")
        self.old = os.getcwd()
        os.chdir(self.d)
        write(self.d, "tests/test_a.py", "# test_ghost 나중에\ndef test_real():\n    pass\n")
        write(self.d, "tests/b.test.js", 'it("finds item", () => {})\n// test_jsghost\nfunction test_jsfn() {}\n')

    def tearDown(self):
        os.chdir(self.old)
        shutil.rmtree(self.d, ignore_errors=True)

    def test_defs_only(self):
        import mr_check
        self.assertTrue(mr_check.test_exists("test_real"))
        self.assertTrue(mr_check.test_exists("tests/test_a.py::test_real"))
        self.assertTrue(mr_check.test_exists("test_jsfn"))
        self.assertFalse(mr_check.test_exists("test_ghost"))
        self.assertFalse(mr_check.test_exists("tests/test_a.py::test_ghost"))
        self.assertFalse(mr_check.test_exists("test_jsghost"))


# ---------- 외부 감사 G-08 잔여: 전부 건너뜀은 통과가 아니다 ----------
class QaAllSkippedTest(QaRunRepo):
    def test_pytest_only_skipped(self):
        import qa_run
        importlib.reload(qa_run)
        self.assertEqual(qa_run.parse_counts("===== 2 skipped in 0.01s =====\n"), (0, 2, 2))

    def test_all_skipped_not_pass(self):
        self.cfg(f'"{PY}" -c "print(\'Ran 2 tests in 0.1s\'); print(); print(\'OK (skipped=2)\')"')
        r = self.qa()
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("코드: 실패(전부 건너뜀)", r.stdout)
        self.assertNotRegex(r.stdout, r"코드: 통과")


# ---------- 외부 감사 J-05 잔여: 커밋된 설정에 test_cmd가 없으면 check-record 실패 ----------
class CheckRecordNoCmdTest(PersonalRepo):
    def test_no_test_cmd(self):
        write(self.d, ".vibe-flow.json", json.dumps({"base": "main"}))
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-qm", "cfg", cwd=self.d)
        self.assertEqual(self.ho("claim", "G-001", "거래처 검색", "feat/G-001-search").returncode, 0)
        self.work_and_record(mr=MR_FILE)
        r = self.ho("check-record")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("커밋된 설정에 test_cmd 없음", r.stdout)


# ---------- 캡처 증거 내구성: export-evidence가 사본 폴더로 옮기고 verify-evidence가 커밋에서 확인 ----------
NO_BROWSER = "- 브라우저: 해당 없음 — 검색 함수만, 화면 없음"


class ExportCaptureTest(ExportRedTest):
    def test_export_copies_and_rewrites(self):
        tree = "c" * 40
        self.seed()
        mr = MR_FILE.replace(NO_BROWSER, "- 브라우저: 통과 — 화면\n- 증거: ![A1](.vibe/qa/shot.png) "
                             "![v](<.vibe/qa/my clip.mp4>) [로그](.vibe/qa/log.txt) [밖](https://x.io/a.png)")
        write(self.d, ".vibe/mr-G-001.md", mr.replace("{tree}", tree))
        write(self.d, ".vibe/qa/shot.png", "PNG")
        write(self.d, ".vibe/qa/my clip.mp4", "MP4")
        write(self.d, ".vibe/qa/log.txt", "log")
        r = self.ho("export-evidence", "G-001")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ev = os.path.join(self.d, "docs", "mr", "G-001-evidence")
        with open(os.path.join(ev, "shot.png"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "PNG")
        self.assertTrue(os.path.isfile(os.path.join(ev, "my clip.mp4")))
        self.assertFalse(os.path.exists(os.path.join(ev, "log.txt")))
        with open(os.path.join(self.d, "docs", "mr", "G-001.md"), encoding="utf-8") as f:
            out = f.read()
        self.assertIn("![A1](G-001-evidence/shot.png)", out)
        self.assertIn("![v](<G-001-evidence/my clip.mp4>)", out)
        self.assertIn("[로그](.vibe/qa/log.txt)", out)
        self.assertIn("(https://x.io/a.png)", out)
        self.assertNotIn(".vibe/qa/shot.png", out)


# ---------- B-02: 전부 건너뜀은 exit 0이어도 통과가 아니다(ok) ----------
class QaOkFieldTest(QaRunRepo):
    def test_ok_recorded(self):
        self.cfg(fake_cmd("Ran 2 tests in 0.1s\n\nOK (skipped=2)\n", 0))
        self.qa()
        f = [x for x in os.listdir(os.path.join(self.d, ".vibe", "qa")) if x.endswith(".json")][0]
        rec = self.rec(f)
        self.assertEqual((rec["exit"], rec["ok"], rec["passed"], rec["total"]), (0, False, 0, 2))

    def test_verify_rejects_all_skipped(self):
        import qa_run
        import vf_git
        importlib.reload(qa_run)
        old = os.getcwd()
        os.chdir(self.d)
        try:
            self.cfg("t")
            tree = vf_git.snapshot()
            write(self.d, f".vibe/qa/{tree}.json", json.dumps({"tree": tree, "cmd": "t", "exit": 0, "passed": 0, "total": 2}))
            miss = qa_run.verify(f"- 대상 tree: {tree}\n- 코드: 통과 — x\n", vf_git.config())
            self.assertTrue(any("통과가 아님" in m for m in miss), miss)
        finally:
            os.chdir(old)


class QaOkHelperTest(unittest.TestCase):   # check-record(qa_record_missing)도 이 판정을 쓴다
    def test_qa_ok(self):
        import handoff
        importlib.reload(handoff)
        self.assertTrue(handoff.qa_ok({"exit": 0, "passed": 1, "total": 1}))
        self.assertFalse(handoff.qa_ok({"exit": 0}))   # 수를 읽을 수 없는 실행은 통과가 아니다(A9-08)
        self.assertFalse(handoff.qa_ok({"exit": 0, "passed": 0, "total": 3}))
        self.assertFalse(handoff.qa_ok({"exit": 0, "ok": False}))
        self.assertFalse(handoff.qa_ok({"exit": 1}))


class CheckRecordSkipTest(PersonalRepo):
    def test_all_skipped_rejected(self):
        self.assertEqual(self.ho("claim", "G-001", "거래처 검색", "feat/G-001-search").returncode, 0)
        self.work_and_record(mr=MR_FILE)
        q = os.path.join(self.d, "docs", "mr", "G-001-qa.json")
        if not os.path.exists(q):
            self.skipTest("work_and_record가 qa 사본을 만들지 않음")
        with open(q, encoding="utf-8") as f:
            rec = json.load(f)
        rec.update(passed=0, total=2, skipped=2)
        write(self.d, "docs/mr/G-001-qa.json", json.dumps(rec))
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-q", "--amend", "--no-edit", cwd=self.d)
        r = self.ho("check-record")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("통과가 아님", r.stdout)


# ---------- B-06: 실행 오류는 RED가 아니다 ----------
class QaRedCrashTest(QaRunRepo):
    def test_crash_not_red(self):
        self.cfg(fake_cmd("Traceback (most recent call last):\nImportError: x\n", 1))
        write(self.d, "mr.md", "## 골\nG-001 거래처 검색\n## QA 결과\n(진행 전)\n")
        r = self.qa("--red", "--mr", "mr.md")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("RED 아님 — 실행 오류(테스트 실패가 아님)", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
