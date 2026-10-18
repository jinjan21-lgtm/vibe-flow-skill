"""11차 감사(A11-01~A11-05, A10-01·02 잔여 — 사람 판정 경로) 회귀 시험. 실행: python -m unittest tests/test_r6_audit11.py -v"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_r6_engine import Engine, PY, HUMAN_DEC  # noqa: E402

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, SCRIPTS)

JEST_FAIL = """FAIL src/app.test.js
  app
    ✕ renders (3 ms)
    ✓ loads (1 ms)

  ● app › renders

    expect(received).toBe(expected)

Tests:       1 failed, 1 passed, 2 total
"""
JEST_OK = JEST_FAIL.replace("FAIL src", "PASS src").replace("✕ renders", "✓ renders").replace(
    "Tests:       1 failed, 1 passed, 2 total", "Tests:       2 passed, 2 total")
VITEST_FAIL = """ ✓ src/app.test.ts > app > loads 1ms
 × src/app.test.ts > app > renders 2ms

      Tests  1 failed | 1 passed (2)
"""


class JsRunnerTest(unittest.TestCase):
    """A11-01: jest(--verbose)·vitest(--reporter=verbose) 출력도 테스트별 결과 — RED와 GREEN이 같은 이름으로 이어진다."""

    def test_jest_red_to_green_names_match(self):
        import qa_run
        import mr_check
        red, green = qa_run.parse_tests(JEST_FAIL), qa_run.parse_tests(JEST_OK)
        self.assertEqual(red["src/app.test.js › app › renders"], "fail")
        self.assertEqual(green["src/app.test.js › app › renders"], "ok")
        self.assertEqual(qa_run.parse_counts(JEST_FAIL), (1, 2, 0))
        self.assertTrue(mr_check.red_valid({"exit": 1, "tests": red}))

    def test_jest_all_failed_counts(self):
        import qa_run
        self.assertEqual(qa_run.parse_counts("Tests:       1 failed, 1 total\n"), (0, 1, 0))

    def test_vitest(self):
        import qa_run
        t = qa_run.parse_tests(VITEST_FAIL)
        self.assertEqual(t, {"src/app.test.ts > app > loads": "ok", "src/app.test.ts > app > renders": "fail"})
        self.assertEqual(qa_run.parse_counts(VITEST_FAIL), (1, 2, 0))


R1_OK = "ROUND: 1\nRESOLVED: 없음\nCHECKED: 1 — test_app.T.test_partial\nFINDING: F9 | blocker | 정렬\nVERDICT: CHANGES\n"
R2_UNMET_MINOR = ("ROUND: 2\nRESOLVED: F9\nFINDING: F2 | minor | 완료 조건 재검증\nCHECKED: 1 — 미충족 — F2\n"
                  "VERDICT: CHANGES\n")
R3_NO_RESOLVE = "ROUND: 3\nRESOLVED: 없음\nCHECKED: 1 — test_app.T.test_partial\nVERDICT: CONFIRM\n"


class LaterUnmetTest(Engine):
    """A11-02: r2 이후의 '미충족'도 RESOLVED로 닫혀야 한다(minor라 장부에 없어도)."""

    def test_r2_unmet_minor_must_be_resolved(self):
        self.flow(rounds=(R1_OK, R2_UNMET_MINOR, R3_NO_RESOLVE))
        r = self.run_py("mr_check.py", ".vibe/mr-G-001.md", "--stage", "merge")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("'미충족' FINDING F2이 뒤 라운드 RESOLVED로 닫히지 않음", r.stdout)


HUMAN_UNMET_R1 = ("FINDING: F1 | blocker | 빈 검색어\nCHECKED: 1 — 미충족 — F1\nVERDICT: CHANGES\n")


class HumanPathCheckedTest(Engine):
    """A10-01·02 잔여: 사람 판정도 완료 조건마다 실재하는 근거가 필요 — 사람이 정하는 것은 지적 처리이지 테스트 실행이 아니다."""

    def human(self):
        p = os.path.join(self.d, ".vibe", "review", "r3.tree")
        with open(p, encoding="utf-8") as f:
            r3 = f.readline().strip()
        self.edit(".vibe/mr-G-001.md", "- 판정: 확정\n## QA 결과",
                  f"- 사람 결정: D-007 — F1 (tree {r3})\n- 판정: 확정 (사람 판정 D-007)\n## QA 결과")
        self.write("docs/DECISIONS.md", HUMAN_DEC)

    def test_unmet_condition_needs_evidence_even_with_human_decision(self):
        self.flow(rounds=(HUMAN_UNMET_R1, "VERDICT: CHANGES\n", "VERDICT: CHANGES\n"))
        self.human()
        r = self.run_py("mr_check.py", ".vibe/mr-G-001.md", "--stage", "merge")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("완료 조건 1번의 확인 근거 없음", r.stdout)

    def test_human_decision_with_later_evidence_passes(self):
        self.flow(rounds=(HUMAN_UNMET_R1, "CHECKED: 1 — test_app.T.test_partial\nVERDICT: CHANGES\n",
                          "VERDICT: CHANGES\n"))
        self.human()
        r = self.run_py("mr_check.py", ".vibe/mr-G-001.md", "--stage", "merge")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class CodeChangedByTestsTest(Engine):
    """A11-03: 테스트가 실행 중 코드를 바꾸면 그 실행은 통과가 아니다(재실행 대조도 같은 판정)."""

    def test_tests_modifying_code_fail(self):
        self.template("base", self.flow)
        cmd = (f'"{PY}" -c "open(\'app.py\',\'a\').write(\'#x\\n\'); '
               "print('Ran 1 test in 0.0s'); print(); print('OK')\"")
        self.write(".vibe-flow.json", json.dumps({"base": "main", "test_cmd": cmd}))
        r = self.run_py("qa_run.py", "--mr", ".vibe/mr-G-001.md")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("실패(테스트가 코드를 바꿈)", r.stdout)


class TreePathTest(Engine):
    """A11-04: 커밋된 QA 기록 tree 값이 경로를 바꾸면 재연은 쓰기 전에 거부한다."""

    def test_path_like_tree_rejected_before_write(self):
        self.template("base", self.flow)
        outside = os.path.join(self.root, "outside.json")
        with open(outside, "w", encoding="utf-8") as f:
            f.write("ORIGINAL")
        self.record()
        q = json.loads(self.read("docs/mr/G-001-qa.json"))
        q["tree"] = "../../../../" + os.path.relpath(outside[:-5], os.path.join(self.root, "x", "y", "z", "w")).replace("\\", "/")
        self.write("docs/mr/G-001-qa.json", json.dumps(q))
        from test_scripts import sh
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-q", "--amend", "--no-edit", cwd=self.d)
        _, ver = self.judge()
        self.assertEqual(ver.returncode, 1, ver.stdout + ver.stderr)
        self.assertIn("tree가 sha가 아님", ver.stdout)
        with open(outside, encoding="utf-8") as f:
            self.assertEqual(f.read(), "ORIGINAL")


class RedCliTest(Engine):
    """A11-05: 수만 실패를 알리고 이름이 없는 출력 — RED CLI는 예외 없이 거부한다."""

    def test_counts_only_red_rejected_cleanly(self):
        self.mr()
        cmd = f'"{PY}" -c "import sys; print(\'Ran 2 tests in 0.0s\'); print(); print(\'FAILED (failures=1)\'); sys.exit(1)"'
        self.write(".vibe-flow.json", json.dumps({"base": "main", "test_cmd": cmd}))
        r = self.run_py("qa_run.py", "--red", "--mr", ".vibe/mr-G-001.md")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("RED 아님", r.stdout)


if __name__ == "__main__":
    unittest.main()
