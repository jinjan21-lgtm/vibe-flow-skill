"""외부 감사(F-13·F-15·F-16·F-17) 회귀 테스트. 실행: python -m unittest tests/test_audit_index.py -v (레포 루트)

임시 git 레포에서 시험한다. 실제 gh·glab은 부르지 않는다(subprocess.run·shutil.which를 가짜로 바꾼다).
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, SCRIPTS)


def sh(*args, cwd, ok=True):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    if ok and r.returncode:
        raise AssertionError(f"{args}: {r.stdout}{r.stderr}")
    return r


class TmpRepo(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="vf-audit-")
        self.old = os.getcwd()
        os.chdir(self.d)
        sh("git", "init", "-q", "-b", "main", cwd=self.d)
        for k, v in (("user.email", "t@t"), ("user.name", "me"), ("core.autocrlf", "false")):
            sh("git", "config", k, v, cwd=self.d)
        self.write(".vibe-flow.json", '{"base": "main"}')

    def tearDown(self):
        os.chdir(self.old)
        shutil.rmtree(self.d, ignore_errors=True)

    def write(self, p, text):
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def read(self, p):
        with open(p, encoding="utf-8", newline="") as f:
            return f.read()

    def commit(self, msg="base"):
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-qm", msg, cwd=self.d)

    def cfg(self):
        import vf_git
        return vf_git.config()


DEC_HEADER = "# 결정 기록\n\n> 정책: 결정은 지우지 않는다. 이 머리말도 보존돼야 한다.\n"


class MigrateHeaderTest(TmpRepo):
    """F-13: 결정이 없는 DECISIONS.md의 머리말이 migrate 뒤에 사라지지 않아야 한다."""

    def migrate(self):
        import hindex
        self.commit()
        snap, _ = hindex.migrate(self.cfg())
        return hindex.verify(snap)

    def test_header_only_decisions_survive_migration(self):
        self.write("docs/handoff/DECISIONS.md", DEC_HEADER)
        ok, rep = self.migrate()
        self.assertTrue(ok, "\n".join(rep))
        bodies = [f for f in os.listdir("docs/handoff") if re.match(r"DECISIONS-\d{4}-\d{2}", f)]
        self.assertEqual(len(bodies), 1, bodies)
        self.assertEqual(self.read(f"docs/handoff/{bodies[0]}"), DEC_HEADER)
        self.assertIn(bodies[0], self.read("docs/handoff/DECISIONS.md"))   # INDEX 「본문:」에서 링크
        import hindex
        self.assertEqual(hindex.lint(self.cfg())[0], [])

    def test_header_kept_when_there_are_blocks(self):
        blk = "## D-001 첫 결정\n- 날짜 2026-10-01 · 결정자 @me · 상태 유효\n"
        self.write("docs/handoff/DECISIONS.md", DEC_HEADER + "\n" + blk)
        ok, rep = self.migrate()
        self.assertTrue(ok, "\n".join(rep))
        self.assertEqual(self.read("docs/handoff/DECISIONS-2026-10.md"), DEC_HEADER + "\n" + blk)


TOPIC = "# WORKLOG — ui\n\n" + "".join(f"## 2026-10-{d:02d} 항목 {d} {{#u{d}}}\n- [x] 일 " + "가" * 80 + "\n\n"
                                         for d in range(1, 29))


class ArchiveTopicTest(TmpRepo):
    """F-17: 이미 보관한 월 파일(ui-2026-10.md)을 다시 토픽으로 보고 ui-2026-10-2026-10.md를 만들면 안 된다."""

    def test_repeated_archive_is_idempotent(self):
        import hindex
        self.write(".vibe-flow.json", '{"base": "main", "index": {"topic_max_chars": 2000}}')
        self.write("docs/handoff/WORKLOG/INDEX.md", "# INDEX\n")
        self.write("docs/handoff/WORKLOG/ui.md", TOPIC)
        self.assertTrue(any("토픽 ui.md" in a for a in hindex.archive(self.cfg())))
        self.assertEqual(self.read("docs/handoff/WORKLOG/ui-2026-10.md"), TOPIC)
        self.assertEqual(hindex.archive(self.cfg()), [])
        self.assertEqual(sorted(os.listdir("docs/handoff/WORKLOG")), ["INDEX.md", "ui-2026-10.md", "ui.md"])
        self.assertFalse([x for x in hindex.lint(self.cfg())[1] if "ui-2026-10.md" in x])   # 보관 파일은 임계값 경고 대상이 아니다

    def test_topic_with_month_like_name_and_no_parent_stays_active(self):
        import hindex, vf_git
        self.write("docs/handoff/WORKLOG/sprint-2026-10.md", "# s\n")
        self.assertIn("docs/handoff/WORKLOG/sprint-2026-10.md", hindex.topic_files(hindex.layout(vf_git.config())))


class RemoteMrsTest(TmpRepo):
    """F-15: gh가 깔려 있어도 GitLab 원격이면 glab을 써야 하고, gh가 실패하면 glab으로 넘어가야 한다."""

    GLAB_OUT = json.dumps([{"iid": 5, "title": "G-123 검색", "source_branch": "feat/G-123-x", "description": ""}])
    GH_OUT = json.dumps([{"number": 9, "title": "G-123 gh", "headRefName": "feat/G-123-y", "body": ""}])

    def fake(self, gh_rc):
        real = subprocess.run
        calls = []

        def run(args, *a, **kw):
            if args and args[0] in ("gh", "glab"):
                calls.append(args[0])
                if args[0] == "gh":
                    return subprocess.CompletedProcess(args, gh_rc, self.GH_OUT if gh_rc == 0 else "", "not a github repo")
                return subprocess.CompletedProcess(args, 0, self.GLAB_OUT, "")
            return real(args, *a, **kw)
        return run, calls

    def remote_mrs(self, url, gh_rc=0):
        import dupe
        sh("git", "remote", "add", "origin", url, cwd=self.d)
        run, calls = self.fake(gh_rc)
        with mock.patch.object(dupe.shutil, "which", lambda n: f"/fake/{n}" if n in ("gh", "glab") else None), \
                mock.patch.object(dupe.subprocess, "run", run):
            return dupe.remote_mrs(), calls

    def test_gitlab_remote_uses_glab_even_if_gh_installed(self):
        mrs, calls = self.remote_mrs("https://gitlab.com/acme/app.git")
        self.assertEqual([m["id"] for m in mrs], ["!5"])
        self.assertNotIn("gh", calls)

    def test_gh_failure_falls_back_to_glab(self):
        mrs, calls = self.remote_mrs("git@code.example.com:acme/app.git", gh_rc=1)
        self.assertEqual([m["id"] for m in mrs], ["!5"])
        self.assertEqual(calls, ["gh", "glab"])

    def test_github_remote_uses_gh(self):
        mrs, calls = self.remote_mrs("https://github.com/acme/app.git")
        self.assertEqual([m["id"] for m in mrs], ["#9"])
        self.assertEqual(calls, ["gh"])


class ClaimKeyTest(TmpRepo):
    """F-16: 같은 사람·같은 날·같은 할 일이라도 브랜치가 다르면 다른 착수 표시다."""

    def setUp(self):
        super().setUp()
        self.write("docs/handoff/REMAINING.md",
                   "# 남은 일\n- [~] G-123 검색 (착수 @bob 2026-09-01) → feat/G-123-a\n"
                   "- [~] G-123 검색 (착수 @bob 2026-09-01) → feat/G-123-b\n")
        self.commit()
        sh("git", "branch", "feat/G-123-a", cwd=self.d)
        sh("git", "branch", "feat/G-123-b", cwd=self.d)

    def test_claims_keep_both_branches(self):
        import dupe, vf_git
        tasks = sorted(c[1] for c in dupe.claims(vf_git.config()) if c[4] == "작업 트리")
        self.assertEqual(tasks, ["G-123 검색 → feat/G-123-a", "G-123 검색 → feat/G-123-b"])

    def test_expired_claims_apply_to_both_branches(self):
        import dupe, vf_git
        b, w = dupe.find("## 골\nG-123\n## 사용자 가치\nx\n", vf_git.config(), remotes=[],
                         today=datetime.date(2026, 10, 17))
        self.assertEqual(b, [])
        self.assertTrue(any("feat/G-123-b" in x and "기간을 넘김" in x for x in w), w)


if __name__ == "__main__":
    unittest.main()
