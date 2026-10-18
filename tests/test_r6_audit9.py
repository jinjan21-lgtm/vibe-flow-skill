"""9차 감사(A9-01~A9-10) 회귀 시험. 실행: python -m unittest tests/test_r6_audit9.py -v (레포 루트)"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_r6_engine import Engine, R1, TEST_FILE, PY  # noqa: E402
from test_scripts import sh  # noqa: E402

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, SCRIPTS)


class A9Flow(Engine):
    def setUp(self):
        super().setUp()
        self.template("base", self.flow)

    def set_mr(self, old, new):
        self.edit(".vibe/mr-G-001.md", old, new)

    def merge(self):
        return self.run_py("mr_check.py", ".vibe/mr-G-001.md", "--stage", "merge")


class EmptyStateTest(A9Flow):
    """A9-01: 값이 비었거나 자리표시뿐인 미검증·미확인 줄은 '없음'이 아니다."""

    def test_empty_unverified_blocks(self):
        self.set_mr("- 미검증·생략 항목과 사유: 없음", "- 미검증·생략 항목과 사유:")
        r = self.merge()
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("UNVERIFIED (값 없음", r.stdout)

    def test_placeholder_unverified_blocks(self):
        self.set_mr("- 미검증·생략 항목과 사유: 없음", "- 미검증·생략 항목과 사유: <운영환경 미검증>")
        self.assertIn("UNVERIFIED (값 없음", self.merge().stdout)

    def test_placeholder_unknown_is_policy_pending(self):
        self.set_mr("- 미확인: 없음", "- 미확인: <권한 정책 미결>")
        r = self.merge()
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("POLICY-PENDING (「미확인」 값 없음", r.stdout)


class ResolutionTest(A9Flow):
    """A9-02: 해소 근거는 실재하고 QA에서 ok인 테스트·실재 파일:줄, 결정은 그 항목을 적은 블록, 항목은 전체 일치."""

    def test_ghost_test_does_not_resolve(self):
        self.set_mr("- 미확인: 없음", "- 미확인: 실서비스 결제 승인\n- 해소: 실서비스 결제 승인 — test_does_not_exist")
        self.assertIn("POLICY-PENDING 실서비스 결제 승인", self.merge().stdout)

    def test_real_ok_test_resolves(self):
        self.set_mr("- 미확인: 없음", "- 미확인: 빈 검색어\n- 해소: 빈 검색어 — test_app.T.test_partial")
        self.assertNotIn("POLICY-PENDING", self.merge().stdout)

    def test_partial_item_match_does_not_close(self):
        self.write("docs/DECISIONS.md", "# 결정\n\n## D-002 G-001 결제\n- 결제\n")
        self.set_mr("- 미확인: 없음", "- 미확인: 실서비스 결제 승인\n- 정책 결정: D-002 — 결제")
        self.assertIn("POLICY-PENDING 실서비스 결제 승인", self.merge().stdout)

    def test_decision_block_must_name_item(self):
        self.write("docs/DECISIONS.md", "# 결정\n\n## D-002 G-001 다른 정책\n- 환불 기준\n")
        self.set_mr("- 미확인: 없음", "- 미확인: 실서비스 결제 승인\n- 정책 결정: D-002 — 실서비스 결제 승인")
        self.assertIn("POLICY-PENDING 실서비스 결제 승인", self.merge().stdout)
        self.write("docs/DECISIONS.md", "# 결정\n\n## D-002 G-001 결제 정책\n- 실서비스 결제 승인: 다음 분기\n")
        self.assertNotIn("POLICY-PENDING", self.merge().stdout)


class CheckedIntegrityTest(A9Flow):
    """A9-03: '미충족' CHECKED·지워진 CHECKED로 근거 대조를 비켜 가지 못한다."""

    def test_unmet_without_finding_and_confirm_invalid_in_review(self):
        import review
        bad = review.checked_problems("CHECKED: 1 — 미충족 — F1\nVERDICT: CONFIRM\n", ["부분 일치 검색"])
        self.assertTrue(any("FINDING" in x for x in bad), bad)
        self.assertTrue(any("CONFIRM" in x for x in bad), bad)

    def test_deleted_checked_blocks_merge(self):
        p = ".vibe/review/r1.txt"
        self.write(p, re.sub(r"^CHECKED:.*\n", "", self.read(p), flags=re.M))
        r = self.merge()
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("CHECKED가 완료 조건 1~1을 한 번씩 덮지 않음", r.stdout)

    def test_unmet_checked_blocks_merge(self):
        p = ".vibe/review/r1.txt"
        self.write(p, self.read(p).replace("CHECKED: 1 — test_app.T.test_partial", "CHECKED: 1 — 미충족 — F9"))
        self.assertIn("'미충족'이 그 라운드의 FINDING id를 가리키지 않음", self.merge().stdout)   # 12차: 모든 라운드 이력 문구


class RoundsContiguousTest(A9Flow):
    """A9-09: 일반 확정도 유효 라운드가 r1부터 이어져야 한다."""

    def test_missing_r1_blocks(self):
        rv = os.path.join(self.d, ".vibe", "review")
        shutil.copyfile(os.path.join(rv, "r1.txt"), os.path.join(rv, "r2.txt"))
        shutil.copyfile(os.path.join(rv, "r1.tree"), os.path.join(rv, "r2.tree"))
        for f in ("r1.txt", "r1.tree"):
            os.remove(os.path.join(rv, f))
        r = self.merge()
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("r1부터 이어지지 않음", r.stdout)


class LocalSchemaTest(A9Flow):
    """A9-10: 로컬 merge도 낮은 판 증거를 막는다(재연은 LEGACY)."""

    def test_old_review_record_blocks_local(self):
        p = ".vibe/review/r1.tree"
        self.write(p, re.sub(r"^schema: \d+\n", "", self.read(p), flags=re.M))
        r = self.merge()
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("LEGACY 증거 판", r.stdout)


class RedSelectionTest(A9Flow):
    """A9-05·06: 무효 RED는 기록하지 않고, GREEN 뒤 RED는 증거가 아니며, export는 merge가 고른 RED를 내보낸다."""

    def reds(self):
        d = os.path.join(self.d, ".vibe", "qa")
        return sorted(f for f in os.listdir(d) if f.startswith("red-"))

    def test_command_error_not_recorded(self):
        before = self.reds()
        self.write(".vibe-flow.json", json.dumps({"base": "main", "test_cmd": f'"{PY}" -c "import sys; sys.exit(3)"'}))
        r = self.run_py("qa_run.py", "--red", "--mr", ".vibe/mr-G-001.md")
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertEqual(self.reds(), before)

    def test_red_after_green_is_not_evidence(self):
        for f in self.reds():
            self.edit_json(f".vibe/qa/{f}", started="2999-01-01T00:00:00+09:00")
        self.assertIn("RED 증거 없음", self.merge().stdout)

    def test_export_takes_selected_red_and_clone_agrees(self):
        good = self.reds()[0]
        decoy = {**json.loads(self.read(f".vibe/qa/{good}")), "tree": "d" * 40,
                 "tests": {"test_ghost (test_app.T.test_ghost)": "fail"}}
        self.write(f".vibe/qa/red-{'d' * 40}.json", json.dumps(decoy))   # 더 최근(이름순 뒤)이지만 GREEN에 없는 실패
        self.record()
        self.assertEqual(json.loads(self.read("docs/mr/G-001-red.json"))["tree"], json.loads(self.read(f".vibe/qa/{good}"))["tree"])
        self.same(*self.judge(), passed=True)


class ArtifactTreeTest(unittest.TestCase):
    """A9-07: 추적 중인 산출물(.pyc)만 바뀐 두 tree의 code_tree는 같다(code_diff와 같은 제외 집합)."""

    def test_pyc_excluded_from_code_tree(self):
        import qa_run
        import vf_git
        d = tempfile.mkdtemp(prefix="vf-a9-")
        old = os.getcwd()
        try:
            os.chdir(d)
            sh("git", "init", "-q", "-b", "main", cwd=d)
            os.makedirs("pkg/__pycache__")
            with open("pkg/m.py", "w") as f:
                f.write("x = 1\n")
            with open("pkg/__pycache__/m.pyc", "wb") as f:
                f.write(b"a")
            t1 = vf_git.snapshot()
            with open("pkg/__pycache__/m.pyc", "wb") as f:
                f.write(b"b")
            t2 = vf_git.snapshot()
            self.assertNotEqual(t1, t2)
            cfg = vf_git.config()
            self.assertEqual(qa_run.code_tree(t1, cfg), qa_run.code_tree(t2, cfg))
        finally:
            os.chdir(old)
            shutil.rmtree(d, ignore_errors=True)


class ZeroTestsTest(unittest.TestCase):
    """A9-08: 0건 실행·수를 읽을 수 없는 출력은 통과가 아니다."""

    def test_ok_needs_counts(self):
        import qa_run
        self.assertFalse(qa_run.ok({"exit": 0, "passed": 0, "total": 0, "skipped": 0}))
        self.assertFalse(qa_run.ok({"exit": 0}))
        self.assertTrue(qa_run.ok({"exit": 0, "passed": 2, "total": 2}))
        self.assertEqual(qa_run.parse_counts("[syntax] 3/3 통과\n"), (3, 3, 0))


class ForgedQaTest(A9Flow):
    """A9-04: 존재하지 않는 tree와 지금 코드의 code_tree를 적은 QA 기록 — 재연은 테스트를 다시 돌려 잡는다."""

    def test_forged_record_caught_by_rerun(self):
        self.write("app.py", "def search(q):\n    return []\n")   # 테스트가 깨지는 코드
        import qa_run
        import vf_git
        old = os.getcwd()
        os.chdir(self.d)
        try:
            code = qa_run.code_tree(vf_git.snapshot(), vf_git.config())
        finally:
            os.chdir(old)
        p = self.qa_rec()
        rec = json.loads(self.read(p))
        fake = "a" * 40
        rec.update(tree=fake, code_tree=code)
        os.remove(os.path.join(self.d, p))
        self.write(f".vibe/qa/{fake}.json", json.dumps(rec))
        mr = self.read(".vibe/mr-G-001.md")
        self.write(".vibe/mr-G-001.md", re.sub(r"대상 tree: [0-9a-f]{40}", f"대상 tree: {fake}", mr))
        for f in os.listdir(os.path.join(self.d, ".vibe", "review")):   # 리뷰 도장도 같은 위조(존재하지 않는 tree + 지금 code_tree)
            if f.endswith(".tree"):
                t = self.read(f".vibe/review/{f}")
                t = re.sub(r"^[0-9a-f]{40}$", "b" * 40, t, count=1, flags=re.M)
                self.write(f".vibe/review/{f}", re.sub(r"^code_tree: .*$", f"code_tree: {code}", t, flags=re.M))
        self.record()
        _, ver = self.judge()
        self.assertEqual(ver.returncode, 1, ver.stdout + ver.stderr)
        # 감사 10: 재실행은 재연 merge가 통과할 때만 — 여기선 그 전에 막힌다. export는 리뷰 도장의 code_tree를 기록의 자기 신고가
        # 아니라 실재하는 tree 객체에서만 다시 만들므로, 없는 tree(bbbb…)를 적은 리뷰 도장은 대조할 수 없어 실패한다
        self.assertIn("리뷰 기록 tree를 읽을 수 없음", ver.stdout)
        self.assertNotRegex(ver.stdout, r"PASS .*독립 재실행")

    def test_forged_qa_after_real_review_caught_by_rerun(self):
        # 리뷰는 진짜(깨진 코드를 r2가 확정), QA 기록만 위조(없는 tree + 지금 code_tree, exit 0) — 재연 merge는 통과하고
        # --run-tests 재실행이 커밋된 코드에서 테스트가 깨지는 것을 잡는다
        self.write("app.py", "def search(q):\n    return []\n")
        self.ok(self.run_py("review.py", "--round", "2", "--mr", ".vibe/mr-G-001.md",
                            reply="ROUND: 2\nRESOLVED: 없음\nVERDICT: CONFIRM\n"))
        import qa_run
        import vf_git
        old = os.getcwd()
        os.chdir(self.d)
        try:
            code = qa_run.code_tree(vf_git.snapshot(), vf_git.config())
        finally:
            os.chdir(old)
        p = self.qa_rec()
        rec = json.loads(self.read(p))
        fake = "a" * 40
        rec.update(tree=fake, code_tree=code)
        os.remove(os.path.join(self.d, p))
        self.write(f".vibe/qa/{fake}.json", json.dumps(rec))
        mr = self.read(".vibe/mr-G-001.md")
        self.write(".vibe/mr-G-001.md", re.sub(r"대상 tree: [0-9a-f]{40}", f"대상 tree: {fake}", mr))
        self.record()
        local, ver = self.judge()
        self.assertEqual(ver.returncode, 1, ver.stdout + ver.stderr)
        self.assertRegex(ver.stdout, r"PASS .*재연 merge 검사")
        self.assertRegex(ver.stdout, r"FAIL .*독립 재실행")


if __name__ == "__main__":
    unittest.main()
