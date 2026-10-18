"""13차 감사(A13-01·A13-02) 회귀 시험. 실행: python -m unittest tests/test_r6_audit13.py -v"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_r6_engine import Engine, HUMAN_DEC  # noqa: E402

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, SCRIPTS)

R1_UNMET = "FINDING: F1 | blocker | 빈 검색어\nCHECKED: 1 — 미충족 — F1\nVERDICT: CHANGES\n"
R2_EVIDENCE = "CHECKED: 1 — test_app.T.test_partial\nVERDICT: CHANGES\n"


class HumanEvidenceRunTest(Engine):
    """A13-01: 사람 판정으로 받은 최종 근거도 QA 실행 기록에서 ok여야 한다(근거 집합은 한 함수 — checked_map + 결정 ID)."""

    def setUp(self):
        super().setUp()
        self.flow(rounds=(R1_UNMET, R2_EVIDENCE, "VERDICT: CHANGES\n"))
        with open(os.path.join(self.d, ".vibe", "review", "r3.tree"), encoding="utf-8") as f:
            r3 = f.readline().strip()
        self.edit(".vibe/mr-G-001.md", "- 판정: 확정\n## QA 결과",
                  f"- 사람 결정: D-007 — F1 (tree {r3})\n- 판정: 확정 (사람 판정 D-007)\n## QA 결과")
        self.write("docs/DECISIONS.md", HUMAN_DEC)

    def merge(self):
        return self.run_py("mr_check.py", ".vibe/mr-G-001.md", "--stage", "merge")

    def test_passes_when_cited_test_ran(self):
        r = self.merge()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_fails_when_cited_test_missing_from_qa(self):
        p = self.qa_rec()
        rec = json.loads(self.read(p))
        rec["tests"] = {"test_other (test_app.T.test_other)": "ok"}
        self.write(p, json.dumps(rec))
        r = self.merge()
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("리뷰 근거 테스트가 QA 실행에서 ok가 아님", r.stdout)


class JsCommaNameTest(unittest.TestCase):
    """A13-02: 쉼표·괄호가 든 JS 테스트 이름을 중간에서 잘라 다른 테스트로 바꾸지 않는다."""

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="vf-js13-")
        self.old = os.getcwd()
        os.chdir(self.d)
        os.makedirs("src")
        with open("src/app.test.ts", "w", encoding="utf-8") as f:
            f.write("describe('Suite', () => {\n  test('logs in', () => {});\n"
                    "  test.skip('logs in, requires token', () => {});\n})\n")

    def tearDown(self):
        os.chdir(self.old)
        shutil.rmtree(self.d, ignore_errors=True)

    def test_full_name_kept_and_matched_exactly(self):
        import mr_check
        ev = "src/app.test.ts › Suite › logs in, requires token"
        self.assertEqual(mr_check.test_ids(ev), [ev])
        self.assertEqual(mr_check.test_ids("src/app.test.ts › Suite › a (b) c (src/app.ts:3)"),
                         ["src/app.test.ts › Suite › a (b) c"])
        self.assertTrue(mr_check.test_exists(ev))
        self.assertFalse(mr_check.test_match(ev, "src/app.test.ts > Suite > logs in"))
        self.assertTrue(mr_check.test_match(ev, "src/app.test.ts > Suite > logs in, requires token"))


if __name__ == "__main__":
    unittest.main()
