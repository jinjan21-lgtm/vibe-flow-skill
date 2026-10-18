"""18차 감사(A18-01) 회귀 시험. 실행: python -m unittest tests/test_r6_audit18.py -v"""
import os
import shutil
import sys
import tempfile
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, SCRIPTS)


class JestNoSpaceSeparatorTest(unittest.TestCase):
    """A18-01: 'renders a›b'와 'renders a › b'는 다른 이름 — 공백 정규화로 같아지지 않는다."""

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="vf-a18-")
        self.old = os.getcwd()
        os.chdir(self.d)
        os.makedirs("src")
        with open("src/a.test.ts", "w", encoding="utf-8") as f:
            f.write("describe('Suite', () => {\n  test('renders a › b', () => {});\n})\n")

    def tearDown(self):
        os.chdir(self.old)
        shutil.rmtree(self.d, ignore_errors=True)

    def test_distinct_names(self):
        import mr_check
        cited = "src/a.test.ts › Suite › renders a›b"
        self.assertFalse(mr_check.test_exists(cited))
        self.assertFalse(mr_check.test_match(cited, "src/a.test.ts › Suite › renders a › b"))
        self.assertTrue(mr_check.checked_ref_problems(cited, True))
        ok = "src/a.test.ts › Suite › renders a › b"
        self.assertTrue(mr_check.test_exists(ok))
        self.assertTrue(mr_check.test_match(ok, "src/a.test.ts › Suite › renders a › b"))
        self.assertTrue(mr_check.test_match("src/a.test.ts > Suite > x", "src/a.test.ts › Suite › x"))


if __name__ == "__main__":
    unittest.main()
