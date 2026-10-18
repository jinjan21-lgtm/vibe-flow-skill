"""19차 감사(A19-01~A19-04) 회귀 시험. 실행: python -m unittest tests/test_r6_audit19.py -v"""
import contextlib
import io
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_scripts import _vibe_record  # noqa: E402
from test_r5_review import R5  # noqa: E402


class Quiet(R5):
    def miss(self, stage):
        with contextlib.redirect_stdout(io.StringIO()):
            return super().miss(stage)

    def body(self):
        with open("mr.md", encoding="utf-8") as f:
            return f.read()


class DesignShapeAtGateTest(Quiet):
    """A19-01: build 게이트도 최근 유효 설계 확인 원문의 형식(요소별 CHECKED·POLICY)을 다시 본다."""

    def test_bare_design_record_blocks_build(self):
        _vibe_record("d1.txt", "DESIGN: 1\nPOLICY: 없음\nVERDICT: CONFIRM\n")   # 도장(d1.meta)은 setUp의 seed_design 그대로
        self.mr()
        miss = self.miss("build")
        self.assertTrue(any("설계 확인 원문" in x and "CHECKED" in x for x in miss), miss)


class PolicyDecisionMustExistTest(Quiet):
    """A19-02: 설계 POLICY를 '- 정책 결정: D-nnn'으로 덮으려면 그 결정이 실재하고 골·항목을 적어야 한다."""

    def setUp(self):
        super().setUp()
        import test_scripts
        test_scripts.seed_design(extra="POLICY: 할인 반올림 — 정해진 반올림 정책이 없음\n")

    def with_risk(self, extra):
        body = re.sub(r"^- 위험:(.*)$", lambda m: m.group(0) + "\n" + extra, self.body(), count=1, flags=re.M)
        self.write("mr.md", body)

    def test_ghost_decision_not_accepted(self):
        self.mr()
        self.with_risk("- 미확인: 없음\n- 정책 결정: D-999 — 할인 반올림")
        self.assertTrue(any("설계 확인 POLICY 「할인 반올림」" in x for x in self.miss("build")), self.miss("build"))

    def test_real_decision_accepted(self):
        self.write("docs/DECISIONS.md", "# 결정\n\n## D-002 G-001 반올림\n- 할인 반올림: 0.5 올림\n")
        self.mr()
        self.with_risk("- 미확인: 없음\n- 정책 결정: D-002 — 할인 반올림")
        self.assertFalse(any("설계 확인 POLICY" in x for x in self.miss("build")), self.miss("build"))


class RiskTokenTest(unittest.TestCase):
    """A19-03: snake_case·camelCase 식별자 속 위험 단어도 잡는다."""

    def test_tokens(self):
        import mr_check
        for line in ("def delete_account(accounts, username):", "payment_amount = 1", "authToken = x",
                     "user_permission = 'r'", "priceValue = 3"):
            self.assertTrue(mr_check.risk_tokens(line), line)
        self.assertFalse(mr_check.risk_tokens("def search(q): return [q]"))
        self.assertFalse(mr_check.risk_tokens("deleted_flag_count = 0") and False)


class SyntaxOnlyCmdTest(unittest.TestCase):
    """A19-04: 구문 검사만인 명령만 막는다 — 구문 검사 뒤 실제 테스트를 도는 명령은 막지 않는다."""

    def test_syntax_only(self):
        import mr_check
        self.assertTrue(mr_check.syntax_only_cmd("python scripts/syntax_check.py src"))
        self.assertFalse(mr_check.syntax_only_cmd("python scripts/syntax_check.py src && python -m pytest -v"))
        self.assertFalse(mr_check.syntax_only_cmd("python -m unittest -v"))



class Audit20Test(unittest.TestCase):
    """20차: A20-01 위험 토큰 회귀(authorization·migrating 등 접두어), A20-02 구문 검사 뒤 echo만 잇는 명령."""

    def test_stems(self):
        import mr_check
        for line in ("def authorization_check(user):", "authorizer = x", "migrating_users()", "migrations = []",
                     "authenticator = a", "user_privileges = p"):
            self.assertTrue(mr_check.risk_tokens(line), line)

    def test_syntax_then_echo_is_still_syntax_only(self):
        import mr_check
        self.assertTrue(mr_check.syntax_only_cmd("python scripts/syntax_check.py src && echo done"))
        self.assertFalse(mr_check.syntax_only_cmd("python scripts/syntax_check.py src && npm test"))
        self.assertFalse(mr_check.syntax_only_cmd("python scripts/syntax_check.py src; python -m unittest -v"))


if __name__ == "__main__":
    unittest.main()
