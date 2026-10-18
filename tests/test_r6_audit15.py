"""15차 감사(A15-01·A15-02) 회귀 시험. 실행: python -m unittest tests/test_r6_audit15.py -v"""
import os
import shutil
import sys
import tempfile
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, SCRIPTS)


class PlaceholderItemTest(unittest.TestCase):
    """A15-01: '정책 A; <정책 B>'의 자리표시 항목이 지워져 미결이 사라지면 안 된다 — 나눈 뒤 항목마다 본다."""

    def test_placeholder_item_keeps_line_unresolved(self):
        import mr_check
        self.assertIsNone(mr_check._items("정책 A; <정책 B>"))
        self.assertIsNone(mr_check._items("정책 A; "))
        self.assertEqual(mr_check._items("정책 A; 정책 B"), ["정책 A", "정책 B"])
        self.assertEqual(mr_check._items("없음"), [])


class OneJsIdPerLineTest(unittest.TestCase):
    """A15-02: 한 줄의 JS 식별자는 하나 — 제목 안에 다른 JS 식별자 문자열이 있어도 쪼개지 않는다."""

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="vf-a15-")
        self.old = os.getcwd()
        os.chdir(self.d)
        os.makedirs("src")
        with open("src/a.test.ts", "w", encoding="utf-8") as f:
            f.write("describe('Suite', () => {\n  test('prints', () => {});\n"
                    "  test.skip('prints src/b.test.ts › Sub › success', () => {});\n})\n")

    def tearDown(self):
        os.chdir(self.old)
        shutil.rmtree(self.d, ignore_errors=True)

    def test_title_with_embedded_id_is_one_id(self):
        import mr_check
        ev = "src/a.test.ts › Suite › prints src/b.test.ts › Sub › success"
        self.assertEqual(mr_check.test_ids(ev), [ev])
        self.assertEqual(mr_check.test_ids(ev + " (src/a.ts:3)"), [ev])

    def test_regression_lines_each_one_id(self):
        import mr_check
        qa = "- 회귀: src/a.test.ts › Suite › prints\n- 회귀: test_app.T.test_x\n"
        self.assertEqual(mr_check.regression_ids(qa), ["src/a.test.ts › Suite › prints", "test_app.T.test_x"])


if __name__ == "__main__":
    unittest.main()
