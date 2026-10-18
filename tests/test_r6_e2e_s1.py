"""런 6 E2E(S1 판) 결함 회귀 시험. 실행: python -m unittest tests/test_r6_e2e_s1.py -v

E1: 리뷰 근거 'TestBilling.test_x (tests/test_hotel.py:62)'의 괄호 속 파일 경로를 테스트 이름으로도 뽑아
    'QA 기록에 없음'으로 merge가 막혔다(t3w1·t3w2 — 프롬프트가 요구한 형식 그대로인데 막힘).
"""
import os
import sys
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, SCRIPTS)


class CodeRefNotTestIdTest(unittest.TestCase):
    def test_file_line_is_not_a_test_id(self):
        import mr_check
        self.assertEqual(mr_check.test_ids("TestBilling.test_cross_month (tests/test_hotel.py:62)"),
                         ["TestBilling.test_cross_month"])
        self.assertEqual(mr_check.test_ids("tests/test_hotel.py::test_x (tests/test_hotel.py:3-5)"),
                         ["tests/test_hotel.py::test_x"])

    def test_test_file_without_line_still_an_id(self):   # '- 회귀: tests/test_hotel.py'처럼 파일 단위 식별은 그대로
        import mr_check
        self.assertEqual(mr_check.test_ids("tests/test_hotel.py"), ["tests/test_hotel.py"])


class ItemSplitTest(unittest.TestCase):
    """E2(t4w1): 미확인 문구 속 쉼표가 한 항목을 둘로 쪼개 해소가 맞지 않았다 — 항목 구분은 ';'."""

    def test_comma_inside_item_kept(self):
        import mr_check
        self.assertEqual(mr_check._items("재무팀 ADR, 법인 할인 포함 여부"), ["재무팀 ADR, 법인 할인 포함 여부"])
        self.assertEqual(mr_check._items("A 확인; B 확인"), ["A 확인", "B 확인"])


class JsSemicolonTest(unittest.TestCase):
    """A14(A13-02 잔여): JS 이름 속 ';'에서도 자르지 않는다. 여러 식별자는 다음 JS 식별자 시작으로 나눈다."""

    def test_semicolon_in_name(self):
        import mr_check
        self.assertEqual(mr_check.test_ids("src/app.test.ts › Suite › handles A; B"), ["src/app.test.ts › Suite › handles A; B"])
        self.assertEqual(mr_check.test_ids("src/a.test.ts › x › y; src/b.test.ts › z (src/b.ts:3)"),
                         ["src/a.test.ts › x › y", "src/b.test.ts › z"])


class HumanIdsNeedBlockTest(unittest.TestCase):
    """A14-01: 사람 결정 줄의 ID 중 결정 블록에도 적힌 것만 지적을 닫는다."""

    def test_only_ids_in_decision_block(self):
        import tempfile
        import shutil
        import mr_check
        d = tempfile.mkdtemp(prefix="vf-a14-")
        old = os.getcwd()
        try:
            os.chdir(d)
            os.makedirs("docs")
            with open("docs/DECISIONS.md", "w", encoding="utf-8") as f:
                f.write("# 결정\n\n## D-123 G-001 보류 해제\n- F2 승인\n")
            mr = "## 리뷰 기록\n- 사람 결정: D-123 — F1 F2 (tree abcdef1)\n- 판정: 확정 (사람 판정 D-123)\n"
            self.assertEqual(mr_check.human_closed_ids(mr, {"base": "main", "handoff_dir": "docs"}), {"F2"})
        finally:
            os.chdir(old)
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
