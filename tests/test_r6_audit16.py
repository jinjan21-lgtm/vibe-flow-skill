"""16차 감사(A16-01) 회귀 시험. 실행: python -m unittest tests/test_r6_audit16.py -v"""
import os
import sys
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, SCRIPTS)


class RegressionLineTest(unittest.TestCase):
    """A16-01: '- 회귀:' 값의 '<…>'를 지우지 않는다(실제 테스트 이름일 수 있다). 자리표시뿐이거나 식별자가 없는 줄은 따로 거부."""

    def test_angle_brackets_kept(self):
        import mr_check
        ids, bad = mr_check.regression_ids("- 회귀: src/a.test.ts › Suite › renders <div>\n")
        self.assertEqual((ids, bad), (["src/a.test.ts › Suite › renders <div>"], []))

    def test_placeholder_or_empty_line_rejected(self):
        import mr_check
        ids, bad = mr_check.regression_ids("- 회귀: test_app.T.test_x\n- 회귀: <test_missing>\n- 회귀: 확인함\n")
        self.assertEqual(ids, ["test_app.T.test_x"])
        self.assertEqual(len(bad), 2)

    def test_comment_ignored(self):
        import mr_check
        self.assertEqual(mr_check.regression_ids("<!-- - 회귀: <돌린 테스트> -->\n- 회귀: test_app.T.test_x\n"),
                         (["test_app.T.test_x"], []))


class PathDottedIdTest(unittest.TestCase):
    """E2E S3 t3y2: Codex가 쓴 'tests/test_hotel.py::TestBilling.test_x'(경로 + 점 이름)를 파일 경로로만 읽어 merge가 막혔다."""

    def setUp(self):
        import tempfile
        self.d = tempfile.mkdtemp(prefix="vf-a16-")
        self.old = os.getcwd()
        os.chdir(self.d)
        os.makedirs("tests")
        with open("tests/test_hotel.py", "w", encoding="utf-8") as f:
            f.write("import unittest\n\n\nclass TestBilling(unittest.TestCase):\n    def test_x(self):\n        pass\n")

    def tearDown(self):
        import shutil
        os.chdir(self.old)
        shutil.rmtree(self.d, ignore_errors=True)

    def test_path_with_dotted_name(self):
        import mr_check
        tid = "tests/test_hotel.py::TestBilling.test_x"
        self.assertEqual(mr_check.test_ids(tid + " (tests/test_hotel.py:5)"), [tid])
        self.assertTrue(mr_check.test_exists(tid))
        self.assertTrue(mr_check.test_match(tid, "test_x (tests.test_hotel.TestBilling.test_x)"))
        self.assertFalse(mr_check.test_match(tid, "test_x (tests.test_other.TestBilling.test_x)"))
        self.assertEqual(mr_check.checked_ref_problems(tid, True), [])


if __name__ == "__main__":
    unittest.main()
