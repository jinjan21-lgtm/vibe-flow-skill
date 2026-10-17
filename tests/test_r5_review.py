"""R5: 리뷰 지적 장부(ledger), 사람 결정 재개 계약, --next DONE의 MR 사본 대조(H-04), '없음(…)' 위험(H-05),
위험 기반 강도(경량·강화). 실행: python -m unittest tests/test_r5_review.py -v (레포 루트)"""
import contextlib
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_scripts import SCRIPTS, seed_design, seed_review, sh  # noqa: E402
from test_c2_design import C2, IMPL, SKIP  # noqa: E402

R1_BLOCK = ("ROUND: 1\nRESOLVED: 없음\nCHECKED: 1 — 미충족 — F1\n"
            "FINDING: F1 | blocker | app.py:2 | 완료 조건 1 위반 | 고친다\nVERDICT: CHANGES\n")
R1_MAJOR = ("ROUND: 1\nRESOLVED: 없음\nCHECKED: 1 — app.py:2\n"
            "FINDING: F2 | major | app.py:1 | 정렬 중복 | 합친다\nVERDICT: CONFIRM\n")
F1 = "FINDING: F1 | blocker | app.py:2 | 완료 조건 1 위반 | 고친다\n"
DEC = "# 결정\n\n## D-005 F1 허용\n- G-001: F1(빈 결과 안내)은 다음 골에서\n"
HUMAN_RV = ("- 라운드 1: blocker 1\n- 라운드 2: blocker 1\n- 라운드 3: blocker 1\n"
            "- 사람 결정: D-005 — {ids}\n- 판정: 확정 (사람 판정 D-005)")


class R5(C2):
    def setUp(self):
        super().setUp()
        sys.path.insert(0, SCRIPTS)
        import mr_check
        import vf_git
        self.mc, self.vf = mr_check, vf_git

    def miss(self, stage):
        with open("mr.md", encoding="utf-8") as f:
            return self.mc.check(f.read(), stage, self.vf.config())

    def replace(self, old, new):
        with open("mr.md", encoding="utf-8") as f:
            body = f.read()
        self.assertIn(old, body)
        self.write("mr.md", body.replace(old, new))


class LedgerReviewTest(R5):
    """1. 라운드 N의 blocker·major는 뒤 라운드 RESOLVED(major는 CARRY 가능)로 닫혀야 CONFIRM이 유효."""

    def setUp(self):
        super().setUp()
        self.write("app.py", IMPL)
        self.mr()

    def test_r2_confirm_must_resolve_r1_blocker(self):
        r = self.codex("review.py", "--round", "1", "--mr", "mr.md", reply=R1_BLOCK)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self.codex("review.py", "--round", "2", "--mr", "mr.md", reply="ROUND: 2\nRESOLVED: 없음\nVERDICT: CONFIRM\n")
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("F1", r.stdout + r.stderr)
        self.assertTrue(os.path.exists(".vibe/review/r2.txt.failed"))
        self.assertFalse(os.path.exists(".vibe/review/r2.tree"))
        r = self.codex("review.py", "--round", "2", "--mr", "mr.md", reply="ROUND: 2\nRESOLVED: F1\nVERDICT: CONFIRM\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.exists(".vibe/review/r2.tree"))

    def test_blocker_cannot_be_carried(self):
        self.codex("review.py", "--round", "1", "--mr", "mr.md", reply=R1_BLOCK)
        r = self.codex("review.py", "--round", "2", "--mr", "mr.md",
                       reply="ROUND: 2\nRESOLVED: 없음\nCARRY: F1 — 골 후보 나중에\nVERDICT: CONFIRM\n")
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("blocker", r.stdout + r.stderr)

    def test_major_can_be_carried_to_goal_candidate(self):
        self.assertEqual(self.codex("review.py", "--round", "1", "--mr", "mr.md", reply=R1_MAJOR).returncode, 0)
        r = self.codex("review.py", "--round", "2", "--mr", "mr.md", reply="ROUND: 2\nRESOLVED: 없음\nVERDICT: CONFIRM\n")
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("F2", r.stdout + r.stderr)
        r = self.codex("review.py", "--round", "2", "--mr", "mr.md",
                       reply="ROUND: 2\nRESOLVED: 없음\nCARRY: F2 — 골 후보 정렬 공통화는 범위 밖\nVERDICT: CONFIRM\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_payload_lists_open_findings(self):
        self.codex("review.py", "--round", "1", "--mr", "mr.md", reply=R1_BLOCK)
        r = self.codex("review.py", "--round", "2", "--mr", "mr.md", "--dry")
        with open(".vibe/review/r2.txt.in", encoding="utf-8") as f:
            self.assertIn("[열린 지적 — RESOLVED 또는 CARRY로 닫는다]\nF1 (blocker, 라운드 1)", f.read())
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_mr_check_catches_open_blocker_even_if_mr_says_confirmed(self):
        seed_review(n=1, verdict="CHANGES", extra=F1)
        seed_review(n=2, extra="RESOLVED: 없음\n")          # 손으로 만든 r2: CONFIRM인데 F1을 닫지 않음
        self.mr(review="- 라운드 1: blocker 1\n- 라운드 2: blocker 0\n- 판정: 확정")
        miss = self.miss("qa")
        self.assertTrue(any("F1" in x and "열린 blocker" in x for x in miss), miss)
        self.assertTrue(any("F1" in x for x in self.miss("merge")))
        seed_review(n=2, extra="RESOLVED: F1\n")
        self.assertFalse(any("열린 blocker" in x for x in self.miss("qa")), self.miss("qa"))


class HumanDecisionTest(R5):
    """2. 3라운드(설계 2회) 뒤 사람 결정 D-nnn — 결정 블록이 골 ID와 남은 blocker ID를 모두 적어야 한다."""

    def setUp(self):
        super().setUp()
        self.write("app.py", IMPL)
        seed_review(n=1, verdict="CHANGES", extra="RESOLVED: 없음\n" + F1)
        seed_review(n=2, verdict="CHANGES", extra="RESOLVED: 없음\n" + F1)
        seed_review(n=3, verdict="CHANGES", extra="RESOLVED: 없음\n" + F1)
        self.write("docs/DECISIONS.md", DEC)

    def test_human_decision_after_round_three_is_accepted(self):
        with open(".vibe/review/r3.tree", encoding="utf-8") as f:
            r3 = f.readline().strip()
        self.mr(review=HUMAN_RV.format(ids=f"F1 (tree {r3[:7]})"))
        self.assertEqual(self.miss("qa"), [])
        self.write("app.py", IMPL + "# 결정에 따른 수정\n")     # 결정 뒤 코드 변경은 새 사람 판정(HumanDecisionTreeTest)
        self.assertTrue(any("사람 재판정" in x for x in self.miss("qa")), self.miss("qa"))

    def test_missing_finding_id_is_a_miss(self):
        self.mr(review=HUMAN_RV.format(ids="F9"))
        miss = self.miss("qa")
        self.assertTrue(any("F1" in x and "사람 결정" in x for x in miss), miss)
        self.write("docs/DECISIONS.md", "# 결정\n\n## D-005 F 허용\n- G-001: 나중에\n")   # 결정 블록에 F1 없음
        self.mr(review=HUMAN_RV.format(ids="F1"))
        miss = self.miss("merge")
        self.assertTrue(any("F1" in x and "D-005" in x for x in miss), miss)

    def test_human_decision_needs_round_three(self):
        os.remove(".vibe/review/r3.txt")
        os.remove(".vibe/review/r3.tree")
        self.mr(review=HUMAN_RV.format(ids="F1"))
        miss = self.miss("qa")
        self.assertTrue(any("3라운드" in x for x in miss), miss)

    def test_decision_must_exist_and_name_goal(self):
        self.write("docs/DECISIONS.md", "# 결정\n\n## D-005 F1 허용\n- G-002: F1\n")
        self.mr(review=HUMAN_RV.format(ids="F1"))
        self.assertTrue(any("D-005" in x and "G-001" in x for x in self.miss("qa")), self.miss("qa"))

    def test_design_human_decision_after_two_checks(self):
        d1 = "FINDING: D1 | blocker | 접근 방식 | 완료 조건 2 누락 | 보탠다\n"
        seed_design(n=1, verdict="CHANGES", extra=d1)
        self.write("docs/DECISIONS.md", "# 결정\n\n## D-003 D1 허용\n- G-001: D1은 범위 밖으로\n")
        conf = "- 확인 1: blocker 1\n- 확인 2: blocker 1\n- 사람 결정: D-003 — {ids}\n- 판정: 확정 (사람 판정 D-003)"
        self.mr(confirm=conf.format(ids="D1"))
        self.assertTrue(any("2회" in x for x in self.miss("build")), self.miss("build"))   # 2회차 없이 사람 판정
        seed_design(n=2, verdict="CHANGES", extra=d1)
        self.assertEqual(self.miss("build"), [])
        self.mr(confirm=conf.format(ids="D9"))
        self.assertTrue(any("D1" in x for x in self.miss("build")), self.miss("build"))

    def test_design_human_decision_without_any_check_is_a_miss(self):
        # 설계 확인을 한 번도 안 돌리고 결정 문서만 쓴 우회
        import glob
        for f in glob.glob(os.path.join(".vibe", "review", "d*")):
            os.remove(f)
        self.write("docs/DECISIONS.md", "# 결정\n\n## D-004 설계 허용\n- G-001 설계는 사람이 확정\n")
        self.mr(confirm="- 사람 결정: D-004 — 없음\n- 판정: 확정 (사람 판정 D-004)")
        self.assertTrue(any("설계 확인 기록(d1·d2) 없음" in x for x in self.miss("build")), self.miss("build"))


class NextMrCopyTest(R5):
    """3. H-04: --next DONE은 커밋된 MR 사본의 골·완료 조건·제외 범위가 작업 MR과 같을 때만."""

    def next_out(self):
        old = (self.mc.next_stage, self.mc.record_check, sys.argv)
        self.mc.next_stage = lambda text, cfg: ("record", "vibe-record", [])
        self.mc.record_check = lambda: (True, [])
        sys.argv = ["mr_check.py", "mr.md", "--next"]
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                self.mc.main()
        finally:
            self.mc.next_stage, self.mc.record_check, sys.argv = old
        return buf.getvalue()

    def commit_copy(self, body):
        self.write("docs/mr/G-001.md", body)
        sh("git", "add", "docs/mr/G-001.md", cwd=self.d)
        sh("git", "commit", "-qm", "G-001 기록", cwd=self.d)

    def test_done_only_when_copy_matches(self):
        self.mr()
        with open("mr.md", encoding="utf-8") as f:
            body = f.read()
        self.commit_copy(body.replace("- [x] 부분 일치 검색", "- [x] 아무 결과"))
        out = self.next_out()
        self.assertNotIn("DONE", out)
        self.assertIn("완료 조건", out)
        self.commit_copy(body.replace("- [x] 부분 일치 검색", "- [ ]   부분 일치   검색"))   # 체크·공백만 다름
        self.assertIn("DONE", self.next_out())

    def test_missing_copy_is_not_done(self):
        self.mr()
        out = self.next_out()
        self.assertNotIn("DONE", out)
        self.assertIn("docs/mr/G-001.md", out)


class NoneRiskTest(R5):
    """4. H-05: '없음(…실제 위험…)'은 없음이 아니다."""

    def test_none_with_explanation_is_a_risk(self):
        self.mr(confirm=SKIP)
        self.assertEqual(self.miss("build"), [])
        self.replace("- 위험: 없음", "- 위험: 없음(권한 검사 순서가 바뀜)")
        self.assertTrue(any("위험 표식" in x for x in self.miss("build")), self.miss("build"))
        self.mr(confirm=SKIP)
        self.replace("- 위험: 없음", "- 위험: 없음.")
        self.assertEqual(self.miss("build"), [])


class ProfileTest(R5):
    """5. 위험 기반 강도: 경량(위험 없음·작음) / 강화(금액·결제·권한·인증·개인정보·삭제·마이그레이션·외부 API 계약)."""

    def test_profile_classification(self):
        self.mr(confirm=SKIP)
        with open("mr.md", encoding="utf-8") as f:
            s = self.mc.sections(f.read())
        self.assertEqual(self.mc.profile(s), "경량")
        self.replace("- 위험: 없음", "- 위험: 화면 문구 변경")
        with open("mr.md", encoding="utf-8") as f:
            self.assertEqual(self.mc.profile(self.mc.sections(f.read())), "표준")
        for word in ("결제 금액 계산", "권한 검사", "개인정보 마스킹"):
            self.mr()
            self.replace("- 위험: 없음", f"- 위험: {word}")
            with open("mr.md", encoding="utf-8") as f:
                self.assertEqual(self.mc.profile(self.mc.sections(f.read())), "강화", word)
        self.mr()
        self.replace("- 데이터·API 변경: 없음", "- 데이터·API 변경: 컬럼 삭제 마이그레이션")
        with open("mr.md", encoding="utf-8") as f:
            self.assertEqual(self.mc.profile(self.mc.sections(f.read())), "강화")

    def test_strong_needs_regression_test_in_plan(self):
        self.mr()
        self.replace("- 위험: 없음", "- 위험: 결제 금액 반올림 변경")
        self.replace("- 코드: unittest", "- 코드: 수동 확인")
        self.assertTrue(any("회귀 테스트" in x for x in self.miss("draft")), self.miss("draft"))
        self.replace("- 코드: 수동 확인", "- 코드: test_payment_rounding 회귀 테스트 + 전체 unittest")
        self.assertFalse(any("회귀 테스트" in x for x in self.miss("draft")), self.miss("draft"))

    def test_strong_needs_regression_line_in_qa(self):
        self.mr(qa="- 대상 tree: 0000000\n- 코드: 통과\n- 브라우저: 해당 없음 — 서버만")
        self.replace("- 위험: 없음", "- 위험: 권한 검사 변경")
        self.replace("- 코드: unittest", "- 코드: test_admin_only")
        self.write("tests/test_perm.py", "def test_admin_only():\n    pass\n\n\ndef test_guest_denied():\n    pass\n")
        self.assertTrue(any("- 회귀:" in x for x in self.miss("merge")), self.miss("merge"))
        self.replace("- 브라우저: 해당 없음 — 서버만", "- 브라우저: 해당 없음 — 서버만\n- 회귀: test_admin_only, test_guest_denied")
        self.assertFalse(any("- 회귀:" in x for x in self.miss("merge")), self.miss("merge"))

    def test_light_profile_has_no_extra_requirements(self):
        self.mr(confirm=SKIP, qa="- 대상 tree: 0000000\n- 코드: 통과\n- 브라우저: 해당 없음 — 서버만")
        self.replace("- 코드: unittest", "- 코드: 수동 확인")
        self.assertFalse(any("회귀" in x for x in self.miss("merge")), self.miss("merge"))


class QaTargetCommentTest(R5):
    """H-01 짝: merge_checks의 QA 대상은 qa_run.target(주석 안 예시 sha 제외)으로 읽는다."""

    def test_comment_sha_is_not_the_target(self):
        self.write("app.py", IMPL)
        real = self.vf.snapshot()
        qa = f"<!-- - 대상 tree: deadbeef00 -->\n- 대상 tree: {real}\n- 코드: 통과\n- 브라우저: 해당 없음 — 서버만\n"
        miss = self.mc.merge_checks(qa, self.vf.config())
        self.assertFalse(any("deadbeef" in x for x in miss), miss)
        self.assertFalse(any("이후 바뀐 파일" in x for x in miss), miss)


class AuditFixTest(R5):
    """외부 감사 G-03·G-04·G-05·G-07·J-06."""

    def setUp(self):
        super().setUp()
        self.write("app.py", IMPL)
        self.mr()

    # G-03: RESOLVED 값은 정확히 '없음' 또는 ID 목록만
    def test_g03_resolved_grammar(self):
        self.assertEqual(self.mc.resolved_ids("RESOLVED: 없음 (F1 미해결)\n"), set())
        self.assertEqual(self.mc.resolved_ids("RESOLVED: 없음.\n"), set())
        self.assertEqual(self.mc.resolved_ids("RESOLVED: F1, F2 B-3\n"), {"F1", "F2", "B-3"})
        self.assertEqual(self.mc.resolved_ids("RESOLVED: F1은 고침\n"), set())
        self.assertTrue(self.mc.resolved_problems("RESOLVED: 없음 (F1 미해결)\n"))
        self.assertFalse(self.mc.resolved_problems("RESOLVED: F1, F2\nRESOLVED: 없음 \n"))

    def test_g03_review_rejects_malformed_resolved(self):
        self.codex("review.py", "--round", "1", "--mr", "mr.md", reply=R1_BLOCK)
        r = self.codex("review.py", "--round", "2", "--mr", "mr.md",
                       reply="ROUND: 2\nRESOLVED: 없음 (F1 미해결)\nVERDICT: CHANGES\n")
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("RESOLVED", r.stdout + r.stderr)
        self.assertTrue(os.path.exists(".vibe/review/r2.txt.failed"))

    def test_g03_mr_check_malformed_resolved_is_miss(self):
        seed_review(n=1, verdict="CHANGES", extra=F1)
        seed_review(n=2, extra="RESOLVED: F1 고침\n")
        self.mr(review="- 라운드 1: blocker 1\n- 라운드 2: blocker 0\n- 판정: 확정")
        self.assertTrue(any("F1" in x for x in self.miss("qa")), self.miss("qa"))

    # G-04: 열린 major도 장부가 막는다(CARRY는 허용)
    def test_g04_open_major_blocks_qa(self):
        seed_review(n=1, extra="RESOLVED: 없음\nFINDING: M1 | major | app.py:1 | 중복 | 합친다\n")
        self.mr(review="- 라운드 1: major 1\n- 판정: 확정")
        self.assertTrue(any("M1" in x for x in self.miss("qa")), self.miss("qa"))
        seed_review(n=2, extra="RESOLVED: 없음\nCARRY: M1 — 골 후보 공통화\n")
        self.mr(review="- 라운드 1: major 1\n- 라운드 2: 0\n- 판정: 확정")
        self.assertFalse(any("M1" in x for x in self.miss("qa")), self.miss("qa"))

    # G-05: 사람 판정에는 '- 사람 결정: D-nnn — <ID들>' 줄이 늘 있어야
    def test_g05_review_human_needs_decision_line(self):
        for n in (1, 2, 3):
            seed_review(n=n, verdict="CHANGES", extra="RESOLVED: 없음\n")
        self.write("docs/DECISIONS.md", DEC)
        rv = "- 라운드 1: 0\n- 라운드 2: 0\n- 라운드 3: 0\n{line}- 판정: 확정 (사람 판정 D-005)"
        self.mr(review=rv.format(line=""))
        self.assertTrue(any("사람 결정" in x for x in self.miss("qa")), self.miss("qa"))
        with open(".vibe/review/r3.tree", encoding="utf-8") as f:
            r3 = f.readline().strip()
        self.mr(review=rv.format(line=f"- 사람 결정: D-005 — 없음 (tree {r3[:7]})\n"))
        self.assertEqual(self.miss("qa"), [])

    def test_g05_design_human_needs_decision_line(self):
        seed_design(n=1, verdict="CHANGES")
        seed_design(n=2, verdict="CHANGES")
        self.write("docs/DECISIONS.md", "# 결정\n\n## D-003 설계 허용\n- G-001: 사람이 확정\n")
        conf = "- 확인 1: 0\n- 확인 2: 0\n{line}- 판정: 확정 (사람 판정 D-003)"
        self.mr(confirm=conf.format(line=""))
        self.assertTrue(any("사람 결정" in x for x in self.miss("build")), self.miss("build"))
        self.mr(confirm=conf.format(line="- 사람 결정: D-003 — 없음\n"))
        self.assertEqual(self.miss("build"), [])

    # G-07: 강화 프로필은 테스트 식별자를 이름으로
    def test_g07_strong_plan_needs_test_identifier(self):
        self.replace("- 위험: 없음", "- 위험: 결제 금액 반올림 변경")
        self.replace("- 코드: unittest", "- 코드: 테스트는 나중에")
        self.assertTrue(any("회귀 테스트" in x for x in self.miss("draft")), self.miss("draft"))
        for ok in ("PayTest.test_round", "tests/test_pay.py::test_round", "tests/test_pay.py"):
            self.mr()
            self.replace("- 위험: 없음", "- 위험: 결제 금액 반올림 변경")
            self.replace("- 코드: unittest", f"- 코드: {ok}")
            self.assertFalse(any("회귀 테스트" in x for x in self.miss("draft")), (ok, self.miss("draft")))

    def test_g07_strong_qa_regression_must_exist_in_tests(self):
        self.mr(qa="- 대상 tree: 0000000\n- 코드: 통과\n- 브라우저: 해당 없음 — 서버만\n- 회귀: 예정")
        self.replace("- 위험: 없음", "- 위험: 권한 검사 변경")
        self.replace("- 코드: unittest", "- 코드: test_month_boundary")
        self.assertTrue(any("회귀" in x for x in self.miss("merge")), self.miss("merge"))
        self.replace("- 회귀: 예정", "- 회귀: test_month_boundary")
        self.assertTrue(any("test_month_boundary" in x for x in self.miss("merge")), self.miss("merge"))
        self.write("tests/test_perm.py", "def test_month_boundary():\n    pass\n")   # 실행 증거는 RegressionEvidenceTest
        self.assertFalse(any("회귀" in x and "실행 증거" not in x for x in self.miss("merge")), self.miss("merge"))

    # J-06: conds 없는 확정 기록은 통과 못 함
    def test_j06_record_without_conds_is_miss(self):
        seed_review(n=1, extra="RESOLVED: 없음\n")
        with open(".vibe/review/r1.tree", encoding="utf-8") as f:
            rec = f.read()
        self.write(".vibe/review/r1.tree", "".join(x for x in rec.splitlines(True) if not x.startswith("conds:")))
        self.mr(review="- 라운드 1: 0\n- 판정: 확정")
        self.assertTrue(any("완료 조건 해시 없음" in x for x in self.miss("qa")), self.miss("qa"))


class NextUserValueTest(NextMrCopyTest):
    """H-04 잔여: --next DONE은 「사용자 가치」도 대조."""

    def test_user_value_change_is_not_done(self):
        self.mr()
        with open("mr.md", encoding="utf-8") as f:
            body = f.read()
        self.commit_copy(body.replace("영업팀이 검색한다", "재무팀이 본다"))
        out = self.next_out()
        self.assertNotIn("DONE", out)
        self.assertIn("사용자 가치", out)
        self.commit_copy(body.replace("영업팀이 검색한다", "영업팀이   검색한다"))
        self.assertIn("DONE", self.next_out())


class HumanDecisionTreeTest(R5):
    """사람 판정 뒤 코드 변경: '- 사람 결정: D-nnn — <IDs> (tree <sha>)'는 r3 tree에 묶인다."""

    def setUp(self):
        super().setUp()
        self.write("app.py", IMPL)
        for n in (1, 2, 3):
            seed_review(n=n, verdict="CHANGES", extra="RESOLVED: 없음\n" + F1)
        self.write("docs/DECISIONS.md", DEC)
        with open(".vibe/review/r3.tree", encoding="utf-8") as f:
            self.r3 = f.readline().strip()

    def rv(self, tree):
        return HUMAN_RV.format(ids="F1" + (f" (tree {tree})" if tree else ""))

    def test_decision_without_tree_is_miss(self):
        self.mr(review=self.rv(""))
        self.assertTrue(any("tree" in x and "D-005" in x for x in self.miss("qa")), self.miss("qa"))

    def test_decision_tree_must_be_r3_tree(self):
        self.mr(review=self.rv("abcdef1"))
        self.assertTrue(any("r3" in x and "D-005" in x for x in self.miss("qa")), self.miss("qa"))

    def test_code_change_after_decision_needs_new_decision(self):
        self.mr(review=self.rv(self.r3[:7]))
        self.assertEqual(self.miss("qa"), [])
        self.write("app.py", IMPL + "# 결정 뒤 수정\n")
        miss = self.miss("qa")
        self.assertTrue(any("사람 판정 뒤 코드 변경(app.py)" in x and "사람 재판정" in x for x in miss), miss)
        self.assertTrue(any("사람 판정 뒤 코드 변경" in x for x in self.miss("merge")))


class DesignHashTest(R5):
    """설계 확인 기록(d<N>.meta)은 「설계」 문구 해시에 묶인다 — 확인 뒤 설계가 바뀌면 stale."""

    def test_design_changed_after_confirm_is_stale(self):
        self.mr()
        self.assertFalse(any("설계가 확인 뒤 바뀜" in x for x in self.miss("build")), self.miss("build"))
        self.replace("- 접근 방식: 검색 함수 추가", "- 접근 방식: 전문 검색 엔진 도입")
        self.assertTrue(any("설계가 확인 뒤 바뀜" in x for x in self.miss("build")), self.miss("build"))

    def test_whitespace_only_change_is_same_design(self):
        self.mr()
        self.replace("- 접근 방식: 검색 함수 추가", "- 접근 방식:   검색 함수 추가  ")
        self.assertFalse(any("설계가 확인 뒤 바뀜" in x for x in self.miss("build")), self.miss("build"))

    def test_meta_without_design_hash_is_stale(self):
        self.mr()
        with open(".vibe/review/d1.meta", encoding="utf-8") as f:
            rec = f.read()
        self.write(".vibe/review/d1.meta", "".join(x for x in rec.splitlines(True) if not x.startswith("design:")))
        self.assertTrue(any("설계가 확인 뒤 바뀜" in x for x in self.miss("build")), self.miss("build"))

    def test_review_design_writes_hash(self):
        os.remove(".vibe/review/d1.meta")
        os.remove(".vibe/review/d1.txt")
        self.mr()
        r = self.codex("review.py", "--design", "1", "--mr", "mr.md")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(".vibe/review/d1.meta", encoding="utf-8") as f:
            self.assertIn("design: ", f.read())
        self.assertFalse(any("설계가 확인 뒤 바뀜" in x for x in self.miss("build")), self.miss("build"))


class ContractHashTest(R5):
    """r<N>.tree 'contract:' — 완료 조건·제외 범위·사용자 가치·영향·위험이 리뷰 뒤 바뀌면 리뷰 재실행."""

    def setUp(self):
        super().setUp()
        self.write("app.py", IMPL)
        seed_review(n=1, extra="RESOLVED: 없음\n")
        self.mr(review="- 라운드 1: 0\n- 판정: 확정")

    def test_contract_change_after_review_is_miss(self):
        self.assertFalse(any("계약" in x for x in self.miss("qa")), self.miss("qa"))
        for old, new in (("- 엑셀", "- 엑셀\n- PDF"), ("영업팀이 검색한다", "재무팀이 본다"),
                         ("- 위험: 없음", "- 위험: 성능 저하")):
            self.replace(old, new)
            miss = self.miss("qa")
            self.assertTrue(any("리뷰 뒤 계약" in x and "리뷰 재실행" in x for x in miss), (old, miss))
            self.assertTrue(any("리뷰 뒤 계약" in x for x in self.miss("merge")))
            self.replace(new, old)

    def test_record_without_contract_is_stale(self):
        with open(".vibe/review/r1.tree", encoding="utf-8") as f:
            rec = f.read()
        self.write(".vibe/review/r1.tree", "".join(x for x in rec.splitlines(True) if not x.startswith("contract:")))
        self.assertTrue(any("계약" in x and "리뷰 재실행" in x for x in self.miss("qa")), self.miss("qa"))

    def test_review_round_writes_contract(self):
        r = self.codex("review.py", "--round", "1", "--mr", "mr.md", reply="ROUND: 1\nCHECKED: 1 — app.py:2\nVERDICT: CONFIRM\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(".vibe/review/r1.tree", encoding="utf-8") as f:
            self.assertIn(f"contract: {self.mc.contract_hash(open('mr.md', encoding='utf-8').read())}", f.read())


class RegressionEvidenceTest(R5):
    """강화 프로필 merge: '- 회귀:' 식별자마다 QA 기록 tests에 ok가 있어야 한다."""

    def setUp(self):
        super().setUp()
        import json
        self.json = json
        self.write("tests/test_perm.py", "def test_month_boundary():\n    pass\n")
        self.mr(qa="- 대상 tree: 0000000\n- 코드: 통과\n- 브라우저: 해당 없음 — 서버만\n- 회귀: test_month_boundary")
        self.replace("- 위험: 없음", "- 위험: 권한 검사 변경")
        self.replace("- 코드: unittest", "- 코드: test_month_boundary")
        self.tree = self.vf.snapshot()
        self.replace("- 대상 tree: 0000000", f"- 대상 tree: {self.tree}")

    def record(self, tests):
        os.makedirs(".vibe/qa", exist_ok=True)
        rec = {"tree": self.tree, "cmd": "", "exit": 0}
        if tests is not None:
            rec["tests"] = tests
        with open(f".vibe/qa/{self.tree}.json", "w", encoding="utf-8") as f:
            self.json.dump(rec, f)

    def test_missing_tests_dict_is_no_evidence(self):
        self.record(None)
        self.assertTrue(any("회귀 테스트 실행 증거 없음" in x and "-v" in x for x in self.miss("merge")), self.miss("merge"))

    def test_regression_must_be_ok_in_record(self):
        self.record({"test_month_boundary (tests.test_perm.Perm.test_month_boundary)": "fail"})
        self.assertTrue(any("test_month_boundary" in x and "실행 증거" in x for x in self.miss("merge")), self.miss("merge"))
        self.record({"tests.test_other.test_x": "ok"})
        self.assertTrue(any("test_month_boundary" in x and "실행 증거" in x for x in self.miss("merge")), self.miss("merge"))
        self.record({"tests/test_perm.py::test_month_boundary": "ok"})
        self.assertFalse(any("실행 증거" in x for x in self.miss("merge")), self.miss("merge"))


class UnverifiedItemsTest(R5):
    """1. 「QA 결과」 '- 미검증·생략 항목과 사유:'는 merge에 필수 — '없음'이거나 항목마다 사람 승인(D-nnn)."""
    QA = "- 대상 tree: 0000000\n- 코드: 통과\n- 브라우저: 해당 없음 — 서버만\n"
    MSG = "미검증 항목이 남음"

    def hit(self):
        return [x for x in self.miss("merge") if self.MSG in x or "미검증·생략" in x]

    def test_missing_line_blocks(self):
        self.mr(qa=self.QA)
        self.assertTrue(self.hit(), self.miss("merge"))

    def test_none_passes(self):
        self.mr(qa=self.QA + "- 미검증·생략 항목과 사유: 없음")
        self.assertFalse(self.hit(), self.miss("merge"))

    def test_listed_item_blocks_without_approval(self):
        self.mr(qa=self.QA + "- 미검증·생략 항목과 사유: 엑셀 내보내기 — 환경 없음")
        self.assertTrue(any(self.MSG in x and "D-nnn" in x for x in self.miss("merge")), self.miss("merge"))

    def test_approval_with_decision_covers_item(self):
        self.write("docs/DECISIONS.md", "# 결정\n\n## D-007 엑셀 생략\n- G-001: 엑셀 내보내기는 다음에\n")
        self.mr(qa=self.QA + "- 미검증·생략 항목과 사유: 엑셀 내보내기\n- 사람 승인: D-007 — 엑셀 내보내기")
        self.assertFalse(self.hit(), self.miss("merge"))

    def test_approval_needs_real_decision_naming_goal(self):
        self.write("docs/DECISIONS.md", "# 결정\n\n## D-007 엑셀 생략\n- G-999: 다른 골\n")
        self.mr(qa=self.QA + "- 미검증·생략 항목과 사유: 엑셀 내보내기\n- 사람 승인: D-007 — 엑셀 내보내기")
        self.assertTrue(any(self.MSG in x for x in self.miss("merge")), self.miss("merge"))
        self.replace("- 사람 승인: D-007", "- 사람 승인: D-008")
        self.assertTrue(any(self.MSG in x for x in self.miss("merge")), self.miss("merge"))


class TrackedIgnoredCodeTest(R5):
    """2. 무시 규칙에 걸려도 추적 중인 코드(.py·.js)는 QA 비교에 넣는다 — 캐시 산출물·qa_ignore_tracked만 뺀다."""

    def setUp(self):
        super().setUp()
        self.write(".gitignore", "mr.md\n.vibe/\ngen/\n")
        self.write("gen/api.js", "v1\n")
        self.write("gen/x.py", "v1\n")
        self.write("gen/__pycache__/x.cpython-312.pyc", "v1")
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "add", "-f", "gen/api.js", "gen/x.py", "gen/__pycache__/x.cpython-312.pyc", cwd=self.d)
        sh("git", "commit", "-qm", "G-001 구현", cwd=self.d)
        self.head = sh("git", "rev-parse", "HEAD^{tree}", cwd=self.d).stdout.strip()

    def diff(self):
        self.write("gen/api.js", "v2\n")
        self.write("gen/x.py", "v2\n")
        self.write("gen/__pycache__/x.cpython-312.pyc", "v2")
        sh("git", "add", "-f", "gen", ".vibe-flow.json", cwd=self.d)
        sh("git", "commit", "-qm", "G-001 바꿈", cwd=self.d)
        return self.mc.code_diff(self.head, sh("git", "rev-parse", "HEAD^{tree}", cwd=self.d).stdout.strip(),
                                 self.vf.config())

    def test_tracked_ignored_code_change_is_code(self):
        code, ignored = self.diff()
        self.assertIn("gen/api.js", code)
        self.assertIn("gen/x.py", code)
        self.assertNotIn("gen/__pycache__/x.cpython-312.pyc", code)

    def test_config_globs_exclude_tracked(self):
        self.write(".vibe-flow.json", '{"base": "main", "qa_ignore_tracked": ["gen/*.js"]}')
        code, ignored = self.diff()
        self.assertNotIn("gen/api.js", code)
        self.assertIn("gen/x.py", code)

    def test_tracked_ignored_change_after_qa_blocks_merge(self):
        target = sh("git", "rev-parse", "HEAD", cwd=self.d).stdout.strip()
        self.mr(qa=f"- 대상 commit: {target}\n- 코드: 통과\n- 브라우저: 해당 없음 — 서버만\n- 미검증·생략 항목과 사유: 없음")
        self.write("gen/api.js", "v2\n")
        sh("git", "add", "-f", "gen/api.js", cwd=self.d)
        sh("git", "commit", "-qm", "G-001 QA 뒤 변경", cwd=self.d)
        self.assertTrue(any("재검증" in x and "gen/api.js" in x for x in self.miss("merge")), self.miss("merge"))


class RedEvidenceTest(R5):
    """3. 표준·강화 merge는 이 브랜치의 RED 기록(red-<tree>.json, exit≠0)과 RED→GREEN 테스트가 있어야 한다."""
    MSG = "RED 증거 없음"

    def setUp(self):
        super().setUp()
        import json
        self.json = json
        self.mr(qa="- 대상 tree: 0000000\n- 코드: 통과\n- 브라우저: 해당 없음 — 서버만\n- 미검증·생략 항목과 사유: 없음")
        self.replace("- 위험: 없음", "- 위험: 정렬 순서 변경")
        self.tree = self.vf.snapshot()
        self.replace("- 대상 tree: 0000000", f"- 대상 tree: {self.tree}")

    def dump(self, name, rec):
        os.makedirs(".vibe/qa", exist_ok=True)
        with open(f".vibe/qa/{name}.json", "w", encoding="utf-8") as f:
            self.json.dump(rec, f)

    def qa(self, tests=None):
        rec = {"tree": self.tree, "cmd": "", "exit": 0}
        if tests is not None:
            rec["tests"] = tests
        self.dump(self.tree, rec)

    def red(self, tests=None, exit=1, branch=None):
        rec = {"tree": "a" * 40, "cmd": "", "exit": exit, "branch": branch or self.vf.current_branch()}
        if tests is not None:
            rec["tests"] = tests
        self.dump("red-" + "a" * 40, rec)

    def red_miss(self):
        return [x for x in self.miss("merge") if self.MSG in x]

    def test_standard_without_red_blocks(self):
        self.qa({"t.A.test_x": "ok"})
        self.assertTrue(any("qa_run.py --red" in x for x in self.red_miss()), self.miss("merge"))

    def test_red_to_green_passes(self):
        self.qa({"t.A.test_x": "ok", "t.A.test_y": "ok"})
        self.red({"t.A.test_x": "fail", "t.A.test_y": "ok"})
        self.assertFalse(self.red_miss(), self.miss("merge"))

    def test_red_failure_must_be_green_in_qa(self):
        self.qa({"t.A.test_y": "ok"})
        self.red({"t.A.test_x": "fail"})
        self.assertTrue(self.red_miss(), self.miss("merge"))

    def test_red_must_fail_and_be_this_branch(self):
        self.qa()
        self.red(exit=0)
        self.assertTrue(self.red_miss(), self.miss("merge"))
        self.red(branch="G-999/other")
        self.assertTrue(self.red_miss(), self.miss("merge"))
        self.red()
        self.assertFalse(self.red_miss(), self.miss("merge"))   # QA 기록에 tests가 없으면 exit≠0인 RED 기록만

    def test_light_needs_no_red(self):
        self.replace("- 위험: 정렬 순서 변경", "- 위험: 없음")
        self.qa({"t.A.test_x": "ok"})
        self.assertFalse(self.red_miss(), self.miss("merge"))


class QualifiedRegressionTest(RegressionEvidenceTest):
    """4. 회귀 식별자가 한정형(Class.test_x · path::test_x)이면 기록 이름 끝이 그 한정형과 같아야 한다."""

    def setUp(self):
        super().setUp()
        self.write("tests/test_perm.py", "class Perm:\n    def test_month_boundary(self):\n        pass\n")
        self.cur = "- 회귀: test_month_boundary"

    def ev(self, rid, tests):
        self.replace(self.cur, rid)
        self.cur = rid
        self.record(tests)
        return [x for x in self.miss("merge") if "실행 증거" in x]

    def test_qualified_ids(self):
        self.assertTrue(self.ev("- 회귀: Perm.test_month_boundary",
                                {"tests.test_perm.Other.test_month_boundary": "ok"}))
        self.assertFalse(self.ev("- 회귀: Perm.test_month_boundary",
                                 {"test_month_boundary (tests.test_perm.Perm.test_month_boundary)": "ok"}))
        self.assertTrue(self.ev("- 회귀: tests/test_perm.py::test_month_boundary",
                                {"tests/test_other.py::test_month_boundary": "ok"}))
        self.assertFalse(self.ev("- 회귀: tests/test_perm.py::test_month_boundary",
                                 {"tests/test_perm.py::test_month_boundary": "ok"}))
        self.assertFalse(self.ev("- 회귀: test_month_boundary", {"tests.test_other.X.test_month_boundary": "ok"}))



if __name__ == "__main__":
    unittest.main()
