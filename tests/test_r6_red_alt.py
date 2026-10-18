"""RED 대체(진단 평가 C7): 동작 불변 변경은 바뀌지 않은 기존 테스트가 QA에서 ok면 RED 대신. 실행: python -m unittest tests/test_r6_red_alt.py -v"""
import contextlib
import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import mr_check  # noqa: E402

QA = "- 코드: 통과 — 3/3\n- RED 대체: 동작 불변 — tests/test_app.py::AppTest.test_total\n"


class RedAltTest(unittest.TestCase):
    def run_alt(self, qa, changed=(), tests=None, exists=True):
        rec = {"tests": tests if tests is not None else {"tests.test_app.AppTest.test_total": "ok"}}
        with mock.patch.object(mr_check, "select_red", return_value=None), \
             mock.patch.object(mr_check, "_qa_record", return_value=rec), \
             mock.patch.object(mr_check, "changed_test_files", return_value=list(changed)), \
             mock.patch.object(mr_check, "test_exists", return_value=exists), \
             contextlib.redirect_stdout(io.StringIO()) as out:
            return mr_check.red_evidence(qa, ["G-001"], {"base": "main"}), out.getvalue()

    def test_unchanged_existing_test_ok(self):
        miss, out = self.run_alt(QA)
        self.assertEqual(miss, [])
        self.assertIn("RED-ALT", out)

    def test_changed_test_file_blocks(self):
        miss, _ = self.run_alt(QA, changed=["tests/test_app.py"])
        self.assertTrue(any("테스트 파일이 그대로일 때만" in x for x in miss), miss)

    def test_not_ok_in_qa_blocks(self):
        miss, _ = self.run_alt(QA, tests={"tests.test_app.AppTest.test_total": "fail"})
        self.assertTrue(miss)

    def test_missing_test_blocks(self):
        miss, _ = self.run_alt(QA, exists=False)
        self.assertTrue(any("레포 테스트 파일에 없음" in x for x in miss), miss)

    def test_no_names_blocks(self):
        miss, _ = self.run_alt("- 코드: 통과 — 3/3\n- RED 대체: 동작 불변 — 기존 테스트 전부\n")
        self.assertTrue(any("테스트 이름이 없음" in x for x in miss), miss)

    def test_without_line_still_needs_red(self):
        miss, _ = self.run_alt("- 코드: 통과 — 3/3\n")
        self.assertTrue(any("RED 증거 없음" in x for x in miss), miss)


if __name__ == "__main__":
    unittest.main()
