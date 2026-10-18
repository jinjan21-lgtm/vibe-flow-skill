"""17차 감사(A17-01·A17-02) 회귀 시험. 실행: python -m unittest tests/test_r6_audit17.py -v"""
import os
import shutil
import sys
import tempfile
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, SCRIPTS)


class Tmp(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="vf-a17-")
        self.old = os.getcwd()
        os.chdir(self.d)

    def tearDown(self):
        os.chdir(self.old)
        shutil.rmtree(self.d, ignore_errors=True)

    def write(self, p, t):
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(t)


class JsGtInNameTest(Tmp):
    """A17-01: JS 이름 속 '>'를 구분자로 읽어 'renders >'를 'renders'로 바꾸지 않는다 — 대조는 전체 문자열 일치."""

    def test_name_with_gt(self):
        import mr_check
        self.write("src/a.test.ts", "describe('Suite', () => {\n  test('renders', () => {});\n  test.skip('renders >', () => {});\n})\n")
        rid = "src/a.test.ts › Suite › renders >"
        self.assertEqual(mr_check.test_ids(rid), [rid])
        self.assertTrue(mr_check.test_exists(rid))
        self.assertFalse(mr_check.test_match(rid, "src/a.test.ts › Suite › renders"))
        self.assertTrue(mr_check.test_match(rid, "src/a.test.ts › Suite › renders >"))
        self.assertTrue(mr_check.test_match("src/a.test.ts > Suite > renders", "src/a.test.ts › Suite › renders"))
        bad = mr_check.regression_evidence([rid], "- 대상 tree: 0\n")   # 기록이 없으면 실행 증거 없음
        self.assertTrue(bad)


class PathQualifiedExactTest(Tmp):
    """A17-02: 경로를 적은 파이썬 테스트는 그 파일의 테스트만 — 다른 디렉터리의 같은 이름으로 대체되지 않는다."""

    def test_exact_path(self):
        import mr_check
        body = "import unittest\n\n\nclass TestBilling(unittest.TestCase):\n    def test_x(self):\n        pass\n"
        self.write("tests/test_hotel.py", body)
        self.write("package/tests/test_hotel.py", body)
        rid = "tests/test_hotel.py::TestBilling.test_x"
        self.assertFalse(mr_check.test_match(rid, "package/tests/test_hotel.py::TestBilling::test_x"))
        self.assertFalse(mr_check.test_match(rid, "test_x (package.tests.test_hotel.TestBilling.test_x)"))
        self.assertTrue(mr_check.test_match(rid, "tests/test_hotel.py::TestBilling::test_x"))
        self.assertTrue(mr_check.test_match(rid, "test_x (tests.test_hotel.TestBilling.test_x)"))
        # 경로 없는 한정형은 예전처럼 끝 일치(클래스·메서드 이름)
        self.assertTrue(mr_check.test_match("TestBilling.test_x", "test_x (package.tests.test_hotel.TestBilling.test_x)"))

    def test_exists_checks_class(self):
        import mr_check
        self.write("tests/test_hotel.py", "import unittest\n\n\nclass TestOther(unittest.TestCase):\n    def test_x(self):\n        pass\n")
        self.assertFalse(mr_check.test_exists("tests/test_hotel.py::TestBilling.test_x"))
        self.assertTrue(mr_check.test_exists("tests/test_hotel.py::TestOther.test_x"))


if __name__ == "__main__":
    unittest.main()
