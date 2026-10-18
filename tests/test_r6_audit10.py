"""10차 감사(A10-01~A10-08) 회귀 시험. 실행: python -m unittest tests/test_r6_audit10.py -v (레포 루트)"""
import json
import os
import re
import shutil
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_r6_engine import Engine, PY  # noqa: E402

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, SCRIPTS)

R1_UNMET = ("ROUND: 1\nRESOLVED: 없음\nCHECKED: 1 — 미충족 — F1\n"
            "FINDING: F1 | blocker | app.py:2 | 완료 조건 1 위반 | 고친다\nVERDICT: CHANGES\n")
R2_CLOSE = "ROUND: 2\nRESOLVED: F1\nVERDICT: CONFIRM\n"
R2_CLOSE_CHECKED = "ROUND: 2\nRESOLVED: F1\nCHECKED: 1 — test_app.T.test_partial (app.py:2)\nVERDICT: CONFIRM\n"


class Base(Engine):
    def setUp(self):
        super().setUp()
        self.template("base", self.flow)

    def merge(self):
        return self.run_py("mr_check.py", ".vibe/mr-G-001.md", "--stage", "merge")


class CheckedRefAtMergeTest(Base):
    """A10-01: merge도 근거의 실재(파일·줄·테스트)와 표준·강화의 테스트 이름을 다시 본다."""

    def test_ghost_file_line_blocks(self):
        p = ".vibe/review/r1.txt"
        self.write(p, self.read(p).replace("CHECKED: 1 — test_app.T.test_partial", "CHECKED: 1 — does/not/exist.py:999999"))
        r = self.merge()
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("근거 파일 does/not/exist.py 없음", r.stdout)

    def test_standard_needs_test_name_at_merge(self):
        p = ".vibe/review/r1.txt"
        self.write(p, self.read(p).replace("CHECKED: 1 — test_app.T.test_partial", "CHECKED: 1 — app.py:1"))
        self.assertIn("테스트 이름이 필요", self.merge().stdout)


class UnmetClosedTest(Engine):
    """A10-02: r1 '미충족'을 RESOLVED로 닫을 때 그 조건의 새 근거(실행된 테스트)가 있어야 한다."""

    def test_resolved_without_new_evidence_blocks(self):
        self.flow(rounds=(R1_UNMET, R2_CLOSE))
        r = self.run_py("mr_check.py", ".vibe/mr-G-001.md", "--stage", "merge")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("완료 조건 1번의 확인 근거 없음", r.stdout)

    def test_resolved_with_new_evidence_passes(self):
        self.flow(rounds=(R1_UNMET, R2_CLOSE_CHECKED))
        r = self.run_py("mr_check.py", ".vibe/mr-G-001.md", "--stage", "merge")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class UnprovenTest(Base):
    """A10-03: 테스트를 다시 돌리지 않은 재연은 통과(0)가 아니라 UNPROVEN(4)."""

    def test_without_run_tests_is_unproven(self):
        self.record()
        _, ver = self.judge()   # judge가 --run-tests를 붙이더라도 아래에서 직접 다시 돈다
        clone = os.path.join(self.root, "clone")
        r = self.run_py("handoff.py", "verify-evidence", "G-001", cwd=clone)
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertIn("UNPROVEN", r.stdout)
        r = self.run_py("handoff.py", "verify-evidence", "G-001", "--run-tests", cwd=clone)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class StaleRedCopyTest(Base):
    """A10-04: 지금 고른 RED가 없으면 예전에 내보낸 -red.json도 지운다."""

    def test_old_red_copy_removed(self):
        self.write("docs/mr/G-001-red.json", json.dumps({"tree": "e" * 40, "exit": 1}))
        for f in os.listdir(os.path.join(self.d, ".vibe", "qa")):
            if f.startswith("red-"):
                os.remove(os.path.join(self.d, ".vibe", "qa", f))
        self.ok(self.run_py("handoff.py", "export-evidence", "G-001"))
        self.assertFalse(os.path.exists(os.path.join(self.d, "docs/mr/G-001-red.json")))


class RedTimingTest(unittest.TestCase):
    """A10-05·06: 같은 초라도 마이크로초로 순서를 본다. 수만 있고 실패 테스트 이름이 없으면 RED가 아니다."""

    def test_before_uses_datetimes(self):
        import mr_check
        self.assertTrue(mr_check._before("2026-10-18T11:00:00.100000+09:00", "2026-10-18T11:00:00.200000+09:00"))
        self.assertFalse(mr_check._before("2026-10-18T11:00:00+09:00", "2026-10-18T11:00:00+09:00"))
        self.assertTrue(mr_check._before("2026-10-18T02:00:00+00:00", "2026-10-18T11:00:01+09:00"))

    def test_counts_only_is_not_red(self):
        import mr_check
        self.assertFalse(mr_check.red_valid({"exit": 1, "passed": 1, "total": 2, "skipped": 0, "tests": {}}))
        self.assertTrue(mr_check.red_valid({"exit": 1, "tests": {"test_x (a.T.test_x)": "fail"}}))


class RunEnvTest(unittest.TestCase):
    """A10-07: 재실행은 허용 목록 환경변수만 넘긴다."""

    def test_secrets_not_passed(self):
        import handoff
        env = handoff.run_env({"PATH": "p", "GITHUB_TOKEN": "x", "AWS_SECRET_ACCESS_KEY": "y", "VF_REPLAY": "{}"})
        self.assertEqual(sorted(env), ["PATH", "VF_REPLAY"])


class QaLineTest(Base):
    """A10-08: exit 0이어도 수를 못 읽으면 MR 코드 줄은 '실패'."""

    def test_unparseable_exit0_writes_fail(self):
        self.write(".vibe-flow.json", json.dumps({"base": "main", "test_cmd": f'"{PY}" -c "print(1)"'}))
        r = self.run_py("qa_run.py", "--mr", ".vibe/mr-G-001.md")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("- 코드: 실패(테스트 수를 읽을 수 없음·0건)", r.stdout)
        self.assertNotRegex(self.read(".vibe/mr-G-001.md"), r"- 코드: 통과")


if __name__ == "__main__":
    unittest.main()
