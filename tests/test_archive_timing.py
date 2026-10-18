"""archive 시점 함정 회귀: lint 경고를 따라 archive를 따로 커밋하거나 기록 뒤에 돌리면 check-record가 막히던 구조.
- archive는 이번 골의 방금 쓴 [x] 줄을 옮기지 않는다(기록 전·후 어느 쪽에 돌려도 같은 커밋에 합칠 수 있게)
- lint·precheck 경고는 「다음 작업 커밋에서」를 함께 말한다
- 이동만 담은 커밋의 check-record 실패는 되돌리는 방법을 알려 준다
실행: python -m unittest tests/test_archive_timing.py -v (레포 루트)"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_c2_record import MR_FILE, PersonalRepo, write  # noqa: E402
from test_scripts import GOAL, sh  # noqa: E402


def rem(d):
    return open(os.path.join(d, "docs/REMAINING.md"), encoding="utf-8").read()


class ArchiveTimingTest(PersonalRepo):
    def claim(self):
        self.assertEqual(self.ho("claim", "G-001", "거래처 검색", "feat/G-001-search").returncode, 0)

    def test_archive_after_record_keeps_this_goal_done_line(self):
        self.claim()
        self.work_and_record(mr=MR_FILE)
        r = self.ho("archive")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(rem(self.d), r"- \[x\] G-001")
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-q", "--amend", "--no-edit", cwd=self.d)
        r = self.ho("check-record")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_archive_before_amend_keeps_uncommitted_done_line(self):
        self.claim()
        write(self.d, "app.py", "x = 1\n", "a")
        sh("git", "commit", "-qam", "G-001 구현", cwd=self.d)
        t = re.sub(r"- \[~\] (G-001 [^(]*)\([^\n]*", r"- [x] \1(@alice 2026-10-17)", rem(self.d))
        write(self.d, "docs/REMAINING.md", t)
        self.ho("archive")
        self.assertRegex(rem(self.d), r"- \[x\] G-001")

    def test_older_goal_done_line_is_still_archived(self):
        self.claim()
        self.work_and_record(mr=MR_FILE)
        write(self.d, "docs/goals/G-002-next.md", GOAL.format(gid="G-002", st="active"))
        write(self.d, "docs/REMAINING.md", "- [ ] G-002 다음 일\n", "a")
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-qm", "G-002 골", cwd=self.d)
        self.ho("archive")
        self.assertNotRegex(rem(self.d), r"- \[x\] G-001")

    def test_lint_warning_says_next_work_commit(self):
        self.claim()
        self.work_and_record(mr=MR_FILE)
        write(self.d, "docs/REMAINING.md", "- [ ] G-002 다음 일\n", "a")
        sh("git", "commit", "-qam", "G-002 골", cwd=self.d)
        w = [l for l in self.ho("lint").stdout.splitlines() if "완료 항목" in l]
        self.assertEqual(len(w), 1, w)
        self.assertIn("다음 작업 커밋", w[0])

    def test_move_only_commit_tells_how_to_fold_it(self):
        self.claim()
        self.work_and_record(mr=MR_FILE)
        write(self.d, "docs/REMAINING.md", "- [ ] G-002 다음 일\n", "a")
        sh("git", "commit", "-qam", "G-002 골", cwd=self.d)
        self.ho("archive")
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-qm", "G-002 archive", cwd=self.d)
        r = self.ho("check-record")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("git reset --soft HEAD^", r.stdout)


if __name__ == "__main__":
    unittest.main()
