"""골 등록 커밋 회귀: judge --apply로 만든 골 여러 개를 claim 전에 등록만 하는 커밋이 check-record에 막히던 구조.
- 새 골 파일(judge CREATE 기록)만 더하는 커밋은 「등록」 — 작업 파일·그 골의 MR을 요구하지 않는다
- 기록(WORKLOG·REMAINING [x])은 등록이 아닌 골 ID(보통 G-000)로 남긴다
- judge CREATE 기록이 없는 손으로 쓴 골 파일은 등록으로 치지 않는다
- claim은 judge가 붙인 goals/INDEX.md 줄도 같이 커밋한다
실행: python -m unittest tests/test_goal_registration.py -v (레포 루트)"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_c2_record import PersonalRepo, TeamRecordMrFileTest, write  # noqa: E402
from test_scripts import sh  # noqa: E402

JUDGED = "# {gid} 다음 일\n<!--\nid: {gid}\nstatus: active\ncreated: 2026-10-18\njudge: codex 2026-10-18 CREATE — 목적에 연결\n-->\n\n## 완료 조건\n- x\n"
HAND = "# {gid} 다음 일\n<!--\nid: {gid}\nstatus: active\ncreated: 2026-10-18\n-->\n"


class GoalRegistrationTest(PersonalRepo):
    def register(self, body, msg, record=True):
        write(self.d, "docs/goals/G-002-next.md", body.format(gid="G-002"))
        write(self.d, "docs/goals/G-003-more.md", body.format(gid="G-003"))
        if record:
            write(self.d, "docs/WORKLOG.md", "\n## 2026-10-18 G-000 골 등록 G-002·G-003\n- 등록\n", "a")
            write(self.d, "docs/REMAINING.md", "- [ ] G-002 다음 일\n- [ ] G-003 더\n- [x] G-000 골 등록 (@alice 2026-10-18)\n", "a")
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-qm", msg, cwd=self.d)
        return self.ho("check-record")

    def test_registration_commit_passes(self):
        r = self.register(JUDGED, "G-000 골 등록 G-002 G-003")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("등록", r.stdout)

    def test_registration_with_work_file_does_not_need_new_goal_mr(self):
        # 같은 커밋에 작업 파일(예: 스킬 갱신)이 있어도 새로 등록한 골은 완료가 아니다 — 그 골의 MR을 요구하지 않는다
        write(self.d, "tool.py", "x = 1\n")
        r = self.register(JUDGED, "G-000 골 등록 G-002 G-003 + 도구")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_hand_written_goal_is_not_registration(self):
        r = self.register(HAND, "G-000 골 등록 G-002 G-003")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("judge", r.stdout)

    def test_registration_needs_a_record_goal(self):
        r = self.register(JUDGED, "G-002 G-003 골 등록", record=False)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("G-000", r.stdout)

    def test_registration_with_existing_goal_work_still_needs_its_mr(self):
        # 이미 있던 골(G-001)을 메시지에 넣고 작업 없이 등록만 하면 G-001 완료로 보지 않는다 — 기록 골로만 요구
        r = self.register(JUDGED, "G-000 골 등록 G-002 G-003 (G-001 관련)")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("G-001", r.stdout)


class ClaimCommitsGoalIndexTest(TeamRecordMrFileTest):
    def test_claim_commits_judge_index_line(self):
        idx = os.path.join(self.a, "docs/handoff/goals/INDEX.md")
        write(self.a, "docs/handoff/goals/INDEX.md", "<!-- vibe-index: GOALS -->\n# 골 INDEX\n\n")
        sh("git", "add", "-A", cwd=self.a)
        sh("git", "commit", "-qm", "G-001 골 INDEX", cwd=self.a)
        sh("git", "push", "-q", "origin", "HEAD:main", cwd=self.a)
        write(self.a, "docs/handoff/goals/G-002-next.md", JUDGED.format(gid="G-002"))
        write(self.a, "docs/handoff/goals/INDEX.md", "- G-002 다음 일 · active → [G-002-next.md](G-002-next.md)\n", "a")
        r = PersonalRepo.ho(self, "claim", "G-002", "다음 일", "proto/G-002-next", cwd=self.a)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        st = sh("git", "status", "--porcelain", cwd=self.a).stdout
        self.assertNotIn("INDEX.md", st)
        self.assertTrue(re.search(r"G-002", open(idx, encoding="utf-8").read()))


if __name__ == "__main__":
    unittest.main()
