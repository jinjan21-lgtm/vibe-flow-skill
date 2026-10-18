"""런 6: 리뷰 CHECKED 근거의 실질 검사 (C5 Top 4). 실행: python -m unittest tests/test_r6_checked.py -v

- 근거는 레포에 실재하는 테스트 이름이나 '파일:줄'이어야 한다(review.py가 라운드 1 응답을 무효로 돌린다)
- 위험 표식이 있는 MR(표준·강화)은 조건마다 테스트 이름이 필요하다
- merge는 리뷰가 근거로 든 테스트가 QA 실행 기록에서 ok인지 대조한다 — 완료 조건 [x]가 실행된 테스트에 묶인다
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_r6_engine import Engine, R1, TEST_FILE  # noqa: E402

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, SCRIPTS)


class RefUnitTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="vf-ck-")
        self.old = os.getcwd()
        os.chdir(self.d)
        os.makedirs("tests")
        with open("tests/test_a.py", "w", encoding="utf-8") as f:
            f.write("def test_real():\n    pass\n")
        with open("app.py", "w", encoding="utf-8") as f:
            f.write("a = 1\nb = 2\n")

    def tearDown(self):
        os.chdir(self.old)
        shutil.rmtree(self.d, ignore_errors=True)

    def bad(self, ev, need=False):
        import mr_check
        return mr_check.checked_ref_problems(ev, need)

    def test_real_refs_ok(self):
        self.assertEqual(self.bad("tests/test_a.py::test_real (app.py:2)", need=True), [])
        self.assertEqual(self.bad("app.py:1"), [])
        self.assertEqual(self.bad("미충족 — F1"), [])

    def test_no_ref_is_invalid(self):
        self.assertTrue(self.bad("확인함"))
        self.assertTrue(self.bad("코드를 읽어 보니 맞음"))

    def test_ghost_test_and_line_invalid(self):
        self.assertTrue(any("test_ghost" in x for x in self.bad("test_ghost")))
        self.assertTrue(any("줄 범위 밖" in x for x in self.bad("app.py:99")))
        self.assertTrue(any("없음" in x for x in self.bad("nope.py:1")))

    def test_standard_needs_test_name(self):
        self.assertTrue(any("테스트 이름이 필요" in x for x in self.bad("app.py:1", need=True)))
        self.assertEqual(self.bad("test_real", need=True), [])


class ReviewInvalidatesTest(Engine):
    """review.py --round 1: 근거가 실재하지 않으면 응답 전체가 무효(.failed), 판정 기록(r1.tree)을 남기지 않는다."""

    def setUp(self):
        super().setUp()
        self.mr()
        self.ok(self.run_py("review.py", "--design", "1", "--mr", ".vibe/mr-G-001.md", reply="VERDICT: CONFIRM\n"))
        self.write("test_app.py", TEST_FILE)
        self.write("app.py", 'def search(q):\n    return [x for x in ["abc"] if q in x]\n')

    def round1(self, checked):
        return self.run_py("review.py", "--round", "1", "--mr", ".vibe/mr-G-001.md",
                           reply=f"ROUND: 1\nRESOLVED: 없음\nCHECKED: 1 — {checked}\nVERDICT: CONFIRM\n")

    def test_vague_evidence_invalid(self):
        r = self.round1("확인함")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("근거", r.stdout + r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.d, ".vibe/review/r1.tree")))

    def test_ghost_test_invalid(self):
        r = self.round1("test_app.T.test_ghost")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("test_ghost", r.stdout + r.stderr)

    def test_standard_profile_line_only_invalid(self):   # MR 위험이 '없음'이 아니라 표준 — 테스트 이름 필요
        r = self.round1("app.py:2")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("테스트 이름이 필요", r.stdout + r.stderr)

    def test_real_test_valid(self):
        self.ok(self.round1("test_app.T.test_partial (app.py:2)"))
        self.assertTrue(os.path.exists(os.path.join(self.d, ".vibe/review/r1.tree")))


class CheckedRunTest(Engine):
    """merge: 리뷰가 근거로 든 테스트가 QA 실행 기록에서 ok가 아니면 막는다(로컬·재연 같게)."""

    def test_cited_test_must_have_run_ok(self):
        self.flow()
        qa_dir = os.path.join(self.d, ".vibe", "qa")
        for f in os.listdir(qa_dir):   # QA 기록에서 근거 테스트를 지운다 — 다른 테스트만 돌린 것처럼
            if f.endswith(".json") and not f.startswith("red-"):
                p = os.path.join(qa_dir, f)
                with open(p, encoding="utf-8") as fh:
                    rec = json.load(fh)
                rec["tests"] = {"test_other (test_app.T.test_other)": "ok"}
                with open(p, "w", encoding="utf-8") as fh:
                    json.dump(rec, fh)
        self.record()
        self.same(*self.judge(), passed=False, key="리뷰 근거 테스트가 QA 실행에서 ok가 아님")

    def test_flow_cites_and_passes(self):
        self.assertIn("test_app.T.test_partial", R1)
        self.flow()
        self.record()
        self.same(*self.judge(), passed=True)


if __name__ == "__main__":
    unittest.main()
