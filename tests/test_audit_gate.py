"""외부 감사 지적(F-01~F-04) 회귀 테스트. 실행: python -m unittest tests/test_audit_gate.py -v (레포 루트)"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_scripts as ts  # noqa: E402
from test_scripts import GOAL, Repo, sh  # noqa: E402


class Mr(Repo):
    # MrCheckTest의 준비·도우미만 빌린다(상속하면 그 테스트가 여기서 다시 돈다)
    check, body, qa_body = ts.MrCheckTest.check, ts.MrCheckTest.body, ts.MrCheckTest.qa_body

    def setUp(self):
        super().setUp()
        sh("git", "checkout", "-q", "-b", "G-001/test", cwd=self.d)
        import vf_git
        self.vf = vf_git
        self.write("docs/DECISIONS.md", "# 결정\n\n## D-001 설계 판정\n- G-001 설계는 사람이 확정\n")   # MR_OK의 사람 판정 D-001
        self.write(".vibe-flow.json", '{"base": "%s"}' % vf_git.snapshot())


class SnapshotIgnoredTrackedTest(Repo):
    # F-01: 추적 중인데 .gitignore에 걸린 파일도 스냅숏에 들어가야 한다(빠지면 HEAD 대비 삭제로 보임)
    def test_snapshot_keeps_tracked_but_ignored_file(self):
        import vf_git
        self.write(".gitignore", "*.pyc\n")
        self.write("cache/a.pyc", "v1")
        self.write("app.py", "x = 1\n")
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "add", "-f", "cache/a.pyc", cwd=self.d)
        sh("git", "commit", "-qm", "c", cwd=self.d)
        head = sh("git", "rev-parse", "HEAD^{tree}", cwd=self.d).stdout.strip()
        self.assertEqual(vf_git.changed_files(head, vf_git.snapshot()), [])

    def test_snapshot_still_sees_deletion_and_new_file(self):
        import vf_git
        self.write("app.py", "x = 1\n")
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-qm", "c", cwd=self.d)
        head = sh("git", "rev-parse", "HEAD^{tree}", cwd=self.d).stdout.strip()
        os.remove("app.py")
        self.write("new.py", "y = 1\n")
        self.assertEqual(sorted(vf_git.changed_files(head, vf_git.snapshot())), ["app.py", "new.py"])


class QaTokenTest(Mr):
    # F-02: '통과하지 못함'은 통과가 아니다
    def test_code_not_passed_wording_blocks_merge(self):
        self.write(".gitignore", "mr.md\n")
        self.write("app.py", "x = 1\n")
        target = self.vf.snapshot()
        body = self.qa_body(target, browser="해당 없음 — 화면 없음").replace("코드: 통과 — 3/3", "코드: 통과하지 못함")
        r = self.check(body, "merge")
        self.assertIn("코드 단계가 '통과'가 아님", r.stdout)
        r = self.check(self.qa_body(target, browser="해당 없음 — 화면 없음"), "merge")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_browser_not_passed_wording_blocks_ui_merge(self):
        self.write(".gitignore", "mr.md\n")
        self.write("static/index.html", "<p>x</p>\n")
        target = self.vf.snapshot()
        r = self.check(self.qa_body(target, browser="통과하지 못함", extra="- 증거: ![A1](A1.png)"), "merge")
        self.assertIn("브라우저 단계 '통과' 필요", r.stdout)
        r = self.check(self.qa_body(target, browser="통과(검색 ✅)", extra="- 증거: ![A1](A1.png)"), "merge")
        self.assertEqual(r.returncode, 0, r.stdout)


class RootUiGlobTest(Mr):
    # F-03: '**/*.tsx'가 루트의 App.tsx에도 걸려야 한다
    def test_root_level_tsx_requires_browser(self):
        self.write(".gitignore", "mr.md\n")
        self.write("App.tsx", "export default 1\n")
        target = self.vf.snapshot()
        r = self.check(self.qa_body(target, browser="해당 없음 — 화면 없음"), "merge")
        self.assertIn("UI 파일 변경(App.tsx)", r.stdout)


class GoalIdBoundaryTest(Repo):
    # F-04: G-123은 G-1234 골 파일·브랜치로 충족되지 않는다
    def setUp(self):
        super().setUp()
        self.write("docs/goals/G-1234-other.md", GOAL.format(gid="G-1234", st="active"))
        import vf_git
        import mr_check
        self.vf, self.mc = vf_git, mr_check

    def test_goal_file_prefix_is_not_a_match(self):
        miss, _ = self.mc.goal_checks({"골": "G-123 시험"}, self.vf.config())
        self.assertIn("G-123 골 파일 없음 (docs/goals)", miss)
        miss, _ = self.mc.goal_checks({"골": "G-1234 시험"}, self.vf.config())
        self.assertEqual(miss, [])

    def test_branch_with_longer_id_is_not_a_match(self):
        sh("git", "checkout", "-q", "-b", "work/G-1234-x", cwd=self.d)
        self.assertTrue(any("이름에 골 ID" in m for m in self.mc.branch_checks(["G-123"], self.vf.config())))
        self.assertEqual(self.mc.branch_checks(["G-1234"], self.vf.config()), [])
        sh("git", "checkout", "-q", "-b", "work/G-123", cwd=self.d)
        self.assertEqual(self.mc.branch_checks(["G-123"], self.vf.config()), [])


if __name__ == "__main__":
    unittest.main()
