"""감사 지적(F-08~F-11) 회귀 테스트: handoff.py claim·check-record. 실행: python -m unittest tests/test_audit_handoff.py -v"""
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_scripts import GOAL, PY, SCRIPTS, sh  # noqa: E402


class AuditHandoffTest(unittest.TestCase):
    """team 모드 레포 + 로컬 bare 원격."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="vf-audit-")
        seed = os.path.join(self.root, "seed")
        os.makedirs(seed)
        sh("git", "init", "-q", "-b", "main", cwd=seed)
        for k, v in (("user.email", "s@s"), ("user.name", "seed"), ("core.autocrlf", "false")):
            sh("git", "config", k, v, cwd=seed)
        files = {
            ".claude/skills/team-handoff/SKILL.md": "# team-handoff\n",
            "docs/handoff/REMAINING.md": "# 남은 업무\n\n- [ ] G-001 거래처 검색 → 링크\n",
            "docs/handoff/WORKLOG/INDEX.md": "# INDEX\n",
            "docs/handoff/WORKLOG/proto.md": "# proto\n",
            "docs/handoff/NORTHSTAR.md": "# 노스스타\n<!-- status: confirmed -->\n## 목적\n검색\n",
            "docs/handoff/goals/G-001-search.md": GOAL.format(gid="G-001", st="active"),
            "docs/handoff/goals/G-1000-big.md": GOAL.format(gid="G-1000", st="active"),
            "docs/handoff/goals/G-002-old.md": GOAL.format(gid="G-002", st="done"),
            ".vibe-flow.json": '{"base": "main", "branch_prefixes": ["proto", "chore"]}',
            "app.js": "// app\n",
        }
        for p, t in files.items():
            os.makedirs(os.path.join(seed, os.path.dirname(p)), exist_ok=True)
            with open(os.path.join(seed, p), "w", encoding="utf-8", newline="\n") as f:
                f.write(t)
        sh("git", "add", "-A", cwd=seed)
        sh("git", "commit", "-qm", "seed", cwd=seed)
        self.bare = os.path.join(self.root, "origin.git")
        sh("git", "clone", "-q", "--bare", seed, self.bare, cwd=self.root)
        self.a = os.path.join(self.root, "A")
        sh("git", "clone", "-q", "-c", "core.autocrlf=false", self.bare, self.a, cwd=self.root)
        for k, v in (("user.email", "alice@x"), ("user.name", "alice"), ("core.autocrlf", "false")):
            sh("git", "config", k, v, cwd=self.a)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def ho(self, *args):
        return subprocess.run([PY, os.path.join(SCRIPTS, "handoff.py"), *args], cwd=self.a,
                              capture_output=True, text=True, encoding="utf-8")

    def w(self, p, t):
        with open(os.path.join(self.a, p), "w", encoding="utf-8", newline="\n") as f:
            f.write(t)

    # F-08: 훅이 커밋을 거부하면 claim은 실패하고 push하지 않는다
    def test_claim_fails_and_does_not_push_when_hook_rejects_commit(self):
        hook = os.path.join(self.a, ".git", "hooks", "pre-commit")
        self.w(hook, "#!/bin/sh\necho 'hook says no' >&2\nexit 1\n")
        os.chmod(hook, os.stat(hook).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        r = self.ho("claim", "G-001", "거래처 검색", "proto/G-001-search")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("선점 완료", r.stdout)
        self.assertIn("hook says no", r.stderr)
        self.assertEqual(sh("git", "branch", "--list", "proto/G-001-search", cwd=self.bare).stdout.strip(), "")

    def test_claim_no_push_fails_when_hook_rejects_commit(self):
        hook = os.path.join(self.a, ".git", "hooks", "pre-commit")
        self.w(hook, "#!/bin/sh\nexit 1\n")
        os.chmod(hook, os.stat(hook).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        r = self.ho("claim", "G-001", "거래처 검색", "proto/G-001-search", "--no-push")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("선점 커밋 완료", r.stdout)

    # F-09: 미리 staged된 다른 파일은 선점 커밋에 들어가지 않고 staged 그대로 남는다
    def test_claim_commit_excludes_unrelated_staged_file(self):
        self.w("secret.txt", "token=abc\n")
        sh("git", "add", "secret.txt", cwd=self.a)
        r = self.ho("claim", "G-001", "거래처 검색", "proto/G-001-search", "--no-push")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        committed = sh("git", "show", "--name-only", "--format=", "HEAD", cwd=self.a).stdout.split()
        self.assertIn("docs/handoff/REMAINING.md", committed)
        self.assertNotIn("secret.txt", committed)
        staged = sh("git", "diff", "--cached", "--name-only", cwd=self.a).stdout.split()
        self.assertEqual(staged, ["secret.txt"])

    def test_claim_still_commits_new_goal_file(self):
        self.w("docs/handoff/goals/G-003-new.md", GOAL.format(gid="G-003", st="active"))
        r = self.ho("claim", "G-003", "새 골", "proto/G-003-new", "--no-push")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        committed = sh("git", "show", "--name-only", "--format=", "HEAD", cwd=self.a).stdout.split()
        self.assertIn("docs/handoff/goals/G-003-new.md", committed)

    # F-10: 골 ID는 경계까지 일치해야 하고 status: active여야 한다
    def test_claim_rejects_id_prefix_of_other_goal(self):
        r = self.ho("claim", "G-100", "x", "proto/G-100-x", "--no-push")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("골 파일", r.stderr)

    def test_claim_rejects_branch_with_longer_id(self):
        r = self.ho("claim", "G-001", "x", "proto/G-0012-x", "--no-push")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("브랜치 이름에 골 ID가 없음", r.stderr)

    def test_claim_rejects_inactive_goal(self):
        r = self.ho("claim", "G-002", "x", "proto/G-002-x", "--no-push")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("active", r.stderr)

    # F-11: REMAINING 완료 줄의 골 ID는 경계까지 일치해야 한다
    def test_check_record_rejects_done_line_of_longer_id(self):
        self.assertEqual(self.ho("claim", "G-001", "거래처 검색", "proto/G-001-search", "--no-push").returncode, 0)
        self.w("app.js", "function search(q) { return q; }\n")
        with open(os.path.join(self.a, "docs/handoff/WORKLOG/proto.md"), "a", encoding="utf-8", newline="\n") as f:
            f.write("\n## 2026-10-17 G-001 거래처 검색 @alice #proto {#2026-10-17-search-alice}\n- [x] 검색\n")
        with open(os.path.join(self.a, "docs/handoff/WORKLOG/INDEX.md"), "a", encoding="utf-8", newline="\n") as f:
            f.write("- 2026-10-17 [proto] @alice G-001 거래처 검색 → [proto.md](proto.md#2026-10-17-search-alice)\n")
        p = os.path.join(self.a, "docs/handoff/REMAINING.md")
        t = open(p, encoding="utf-8").read()
        t = re.sub(r"- \[~\] G-001 [^\n]*", "- [x] G-0012 다른 일 (@alice 2026-10-17)", t)
        self.w("docs/handoff/REMAINING.md", t)
        sh("git", "add", "-A", cwd=self.a)
        sh("git", "commit", "-qm", "G-001 거래처 검색", cwd=self.a)
        r = self.ho("check-record")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("[x] 완료 줄 없음", r.stdout)


if __name__ == "__main__":
    unittest.main()
