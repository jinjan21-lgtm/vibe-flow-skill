"""런 6 진단 평가 C6 감점 처리(mr_check 쪽). 실행: python -m unittest tests/test_r6_c6.py -v

- 위험 자기 분류 교차 확인: '위험: 없음'인데 바뀐 코드에 금액·권한·삭제 식별자가 있으면 판단 근거를 적게 한다
- 자동 테스트 없이 구문 검사만(test_cmd=syntax_check)으로는 표준·강화 merge 불가
- 설계 확인의 POLICY 항목은 MR 「영향·위험」 미확인(또는 정책 결정)에 있어야 한다
- 시뮬레이션 결정은 상태로 표시(운영 승인 아님)
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_scripts import seed_design, seed_review  # noqa: E402
from test_r5_review import R5  # noqa: E402


class Quiet(R5):
    def miss(self, stage):   # review 단계는 [profile]·[size] 줄을 찍는다 — 콘솔 인코딩과 무관하게
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            return super().miss(stage)


class RiskCrossCheckTest(Quiet):
    def setUp(self):
        super().setUp()
        self.mr()
        if "- 위험: 정렬 순서 변경" in self.body():
            self.replace("- 위험: 정렬 순서 변경", "- 위험: 없음")

    def body(self):
        with open("mr.md", encoding="utf-8") as f:
            return f.read()

    def test_money_code_with_no_risk_needs_judgement(self):
        self.assertIn("- 위험: 없음", self.body())
        self.write("app.py", "def total(price, tax):\n    return price + tax\n")
        miss = self.miss("review")
        self.assertTrue(any("위험 판단" in x for x in miss), miss)
        self.replace("- 위험: 없음", "- 위험: 없음\n- 위험 판단: 표시용 합계 함수만 — 청구·저장 금액에 쓰이지 않음")
        self.assertFalse(any("위험 판단" in x for x in self.miss("review")), self.miss("review"))

    def test_plain_code_no_judgement_needed(self):
        self.write("app.py", "def search(q):\n    return [q]\n")
        self.assertFalse(any("위험 판단" in x for x in self.miss("review")), self.miss("review"))


class SyntaxOnlyTest(Quiet):
    def test_syntax_check_cmd_not_enough_for_standard(self):
        import json
        self.write(".vibe-flow.json", json.dumps({"base": "main", "test_cmd": "python syntax_check.py src"}))
        self.mr()
        with open("mr.md", encoding="utf-8") as f:
            body = f.read()
        if "- 위험: 없음" in body:
            self.replace("- 위험: 없음", "- 위험: 정렬 순서 변경")
        miss = self.miss("merge")
        self.assertTrue(any("구문 검사만" in x for x in miss), miss)


class DesignPolicyLinkTest(Quiet):
    def test_policy_from_design_must_be_in_unknowns(self):
        seed_design(extra="POLICY: ADR 법인 할인 포함 여부 — 보고 수치 정의가 바뀜\n")
        self.mr()
        miss = self.miss("build")
        self.assertTrue(any("ADR 법인 할인 포함 여부" in x and "설계 확인 POLICY" in x for x in miss), miss)
        with open("mr.md", encoding="utf-8") as f:
            body = f.read()
        body = re.sub(r"^- 위험:(.*)$", lambda m: m.group(0) + "\n- 미확인: ADR 법인 할인 포함 여부", body, count=1, flags=re.M)
        self.write("mr.md", body)
        self.assertFalse(any("설계 확인 POLICY" in x for x in self.miss("build")), self.miss("build"))

    def test_design_policy_not_closed_by_self_resolution(self):   # E2E S6 t4s2: 테스트 이름만 적어도 닫힐 수 있었다
        import mr_check
        seed_design(extra="POLICY: ADR 법인 할인 포함 여부 — 보고 수치 정의가 바뀜\n")
        self.mr()
        with open("mr.md", encoding="utf-8") as f:
            s = mr_check.sections(f.read())
        s["영향·위험"] = "- 위험: 정렬 순서 변경\n- 미확인: ADR 법인 할인 포함 여부\n- 해소: ADR 법인 할인 포함 여부 — app.py:1\n"
        self.write("app.py", "x = 1\n")
        st = mr_check.verification_states(s, ["G-001"], self.vf.config(),
                                          design_items=mr_check.design_policy_items("G-001", self.vf.config()))
        self.assertTrue(any(k == "POLICY-PENDING" and "ADR" in x for k, x, _ in st), st)

    def test_policy_none_ok(self):
        seed_design(extra="POLICY: 없음\n")
        self.mr()
        self.assertFalse(any("설계 확인 POLICY" in x for x in self.miss("build")))


class SimulatedDecisionTest(unittest.TestCase):
    def test_simulated_marker(self):
        import mr_check
        self.assertTrue(mr_check.simulated_block("## D-001 x\n- 시뮬레이션 사용자 결정(E2E)\n"))
        self.assertFalse(mr_check.simulated_block("## D-001 x\n- 결정자 @alice\n"))


if __name__ == "__main__":
    unittest.main()
