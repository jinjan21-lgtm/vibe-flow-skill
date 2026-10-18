"""런 6: 리뷰 라운드 상한은 계약 변경 재시작으로 초기화되지 않는다(B), 설계 확인은 칸마다 근거를 남긴다(E).
실행: python -m unittest tests/test_r6_design_cycle.py -v (레포 루트)

B: review.py가 받아들인 라운드를 .vibe/review/cycles.log에 쌓고, 같은 골·브랜치·기준에서 3라운드를 쓰면
   계약 변경 뒤 1라운드 재시작도 막는다. 사람 판정(D-nnn, 리뷰에 관한 결정) 뒤 --after-decision으로만 새 사이클.
E: 설계 확인 응답은 설계 다섯 칸마다 'CHECKED: <요소> — <근거>'와 'POLICY:' 줄이 있어야 유효하다.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_r6_engine import IMPL, R1, TEST_FILE, Engine  # noqa: E402
from test_scripts import DESIGN_CHECKED, DESIGN_OK, sh  # noqa: E402

import review  # noqa: E402  (test_scripts가 scripts/를 sys.path에 넣는다)

MRP = ".vibe/mr-G-001.md"
LOG = ".vibe/review/cycles.log"
CAP = "리뷰 3라운드를 이미 썼다"
DEC_OK = "# 결정\n\n## D-005 G-001 리뷰 새 사이클\n- 결정자 @t · 계약 변경 뒤 리뷰를 1라운드부터 다시 받는다\n"


class Cycle(Engine):
    def prep(self):
        """설계 확인 → RED → 구현 커밋까지(리뷰 직전)."""
        self.mr()
        self.ok(self.run_py("review.py", "--design", "1", "--mr", MRP, reply=DESIGN_OK))
        self.write("test_app.py", TEST_FILE)
        self.ok(self.run_py("qa_run.py", "--red", "--mr", MRP))
        self.write("app.py", IMPL)
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-qm", "G-001 거래처 부분 검색", cwd=self.d)

    def r1(self, *extra, reply=R1):
        return self.run_py("review.py", "--round", "1", "--mr", MRP, *extra, reply=reply)

    def contract_change(self, i):
        self.edit(MRP, "- 엑셀\n", f"- 엑셀\n- PDF{i}\n")

    def spend_three(self):
        """계약을 바꿔 가며 1라운드를 세 번 — 누적 3라운드."""
        self.ok(self.r1())
        for i in range(2):
            self.contract_change(i)
            self.ok(self.r1())

    def log_lines(self):
        return self.read(LOG).splitlines()


class RoundCapTest(Cycle):
    def setUp(self):
        super().setUp()
        self.prep()

    def test_accepted_round_is_logged(self):
        self.ok(self.r1())
        lines = self.log_lines()
        self.assertEqual(len(lines), 1, lines)
        self.assertRegex(lines[0], r"goal=G-001 branch=feat/G-001-search base=[0-9a-f]+ round=1 verdict=CONFIRM")

    def test_contract_change_rerun_allowed_under_cap(self):
        self.ok(self.r1())
        self.contract_change(0)
        self.ok(self.r1())
        self.assertEqual(len(self.log_lines()), 2)

    def test_contract_change_rerun_refused_after_three(self):
        self.spend_three()
        before = self.read(".vibe/review/r1.txt")
        self.contract_change(9)
        r = self.r1()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(CAP, r.stderr)
        self.assertIn("--after-decision", r.stderr)
        self.assertEqual(self.read(".vibe/review/r1.txt"), before)   # Codex를 부르지 않았고 기록도 그대로
        self.assertEqual(len(self.log_lines()), 3)

    def test_cap_counts_rounds_2_3_too(self):
        self.ok(self.r1())
        self.ok(self.run_py("review.py", "--round", "2", "--mr", MRP, reply="ROUND: 2\nRESOLVED: 없음\nVERDICT: CONFIRM\n"))
        self.ok(self.run_py("review.py", "--round", "3", "--mr", MRP, "--files", "app.py",
                            reply="ROUND: 3\nRESOLVED: 없음\nVERDICT: CONFIRM\n"))
        self.contract_change(0)
        r = self.r1()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(CAP, r.stderr)

    def test_invalid_response_is_not_counted(self):
        r = self.r1(reply="ROUND: 1\n판정 없음\n")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.d, LOG)) and self.log_lines())

    def test_after_decision_starts_new_cycle(self):
        self.spend_three()
        self.write("docs/DECISIONS.md", DEC_OK)
        self.contract_change(9)
        self.ok(self.r1("--after-decision", "D-005"))
        lines = self.log_lines()
        self.assertRegex(lines[3], r"^cycle=D-005 goal=G-001 ")
        self.assertRegex(lines[4], r"round=1 verdict=CONFIRM")
        self.contract_change(10)
        self.ok(self.r1())   # 새 사이클 안에서는 1라운드째를 썼을 뿐

    def test_same_decision_cannot_reopen_twice(self):
        self.spend_three()
        self.write("docs/DECISIONS.md", DEC_OK)
        self.ok(self.r1("--after-decision", "D-005"))
        r = self.r1("--after-decision", "D-005")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("D-005", r.stderr)

    def test_after_decision_requires_valid_decision(self):
        self.spend_three()
        cases = {"없는 결정": None,
                 "다른 골": "# 결정\n\n## D-005 G-002 리뷰 새 사이클\n- 결정자 @t\n",
                 "리뷰 결정 아님": "# 결정\n\n## D-005 G-001 할인 정책\n- 결정자 @t · 법인 할인 포함\n"}
        for name, dec in cases.items():
            with self.subTest(name):
                p = os.path.join(self.d, "docs", "DECISIONS.md")
                if dec is None:
                    if os.path.exists(p):
                        os.remove(p)
                else:
                    self.write("docs/DECISIONS.md", dec)
                r = self.r1("--after-decision", "D-005")
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn("D-005", r.stderr)
                self.assertNotIn("cycle=", self.read(LOG))


class DesignShapeUnitTest(unittest.TestCase):
    def test_valid_reply(self):
        self.assertEqual(review.design_problems(DESIGN_OK), [])

    def test_missing_element(self):
        text = DESIGN_OK.replace("CHECKED: 테스트 계획 — 부분 일치 테스트를 먼저 RED로 확인하는 계획이 있다\n", "")
        bad = review.design_problems(text)
        self.assertTrue(any("테스트 계획" in b for b in bad), bad)

    def test_duplicate_element(self):
        text = DESIGN_OK.replace("POLICY:", "CHECKED: 접근 방식 — 한 번 더 적은 근거 문장입니다\nPOLICY:")
        self.assertTrue(any("접근 방식" in b for b in review.design_problems(text)))

    def test_short_evidence(self):
        text = DESIGN_OK.replace("search(q) 시그니처와 반환 형태가 그대로다", "없음")
        bad = review.design_problems(text)
        self.assertTrue(any("데이터·API 변경" in b for b in bad), bad)

    def test_unknown_element(self):
        text = DESIGN_OK.replace("POLICY:", "CHECKED: 성능 — 큰 데이터에서 느려질 수 있음을 봤다\nPOLICY:")
        self.assertTrue(review.design_problems(text))

    def test_missing_policy(self):
        bad = review.design_problems(DESIGN_OK.replace("POLICY: 없음\n", ""))
        self.assertTrue(any("POLICY" in b for b in bad), bad)

    def test_policy_without_reason(self):
        self.assertTrue(review.design_problems(DESIGN_OK.replace("POLICY: 없음", "POLICY: 반올림 규칙")))

    def test_policy_none_mixed_with_items(self):
        text = DESIGN_OK.replace("POLICY: 없음", "POLICY: 없음\nPOLICY: 반올림 규칙 — 요청이 정하지 않음")
        self.assertTrue(review.design_problems(text))

    def test_policy_items_valid(self):
        text = DESIGN_OK.replace("POLICY: 없음", "POLICY: 반올림 규칙 — 요청이 소수점 처리를 정하지 않음\n"
                                                 "POLICY: 법인 할인 대상 — 누가 받는지 영업팀이 정해야 함")
        self.assertEqual(review.design_problems(text), [])
        self.assertEqual(review.design_policies(text), ["반올림 규칙", "법인 할인 대상"])

    def test_policies_none(self):
        self.assertEqual(review.design_policies(DESIGN_OK), [])
        self.assertEqual(review.design_policies("VERDICT: CONFIRM\n"), [])


class DesignShapeFlowTest(Cycle):
    def setUp(self):
        super().setUp()
        self.mr()

    def design(self, reply):
        return self.run_py("review.py", "--design", "1", "--mr", MRP, reply=reply)

    def test_structured_reply_accepted(self):
        self.ok(self.design(DESIGN_OK))
        self.assertTrue(os.path.exists(os.path.join(self.d, ".vibe/review/d1.meta")))

    def test_bare_verdict_is_invalid(self):
        r = self.design("DESIGN: 1\nVERDICT: CONFIRM\n")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("CHECKED", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.d, ".vibe/review/d1.meta")))
        self.assertFalse(os.path.exists(os.path.join(self.d, ".vibe/review/d1.txt")))
        self.assertTrue(os.path.exists(os.path.join(self.d, ".vibe/review/d1.txt.failed")))

    def test_missing_policy_is_invalid(self):
        r = self.design("DESIGN: 1\n" + DESIGN_CHECKED + "VERDICT: CONFIRM\n")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("POLICY", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.d, ".vibe/review/d1.meta")))


if __name__ == "__main__":
    unittest.main()
