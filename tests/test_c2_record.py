"""외부 평가 지적 회귀: 로컬 모드 선점, 기록 커밋의 MR 파일(검증 증거), 방금 쓴 완료 줄 lint 소음.
실행: python -m unittest tests/test_c2_record.py -v (레포 루트)"""
import datetime
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_scripts import GOAL, MR_OK, PY, SCRIPTS, sh  # noqa: E402

MR_FILE = MR_OK.replace("G-001 시험 골", "G-001 거래처 검색").format(
    plan="같음", review="- 라운드 1 (전체): blocker 0 · major 0 — 문제 없음\n- 판정: 확정",
    qa="- 대상 tree: {tree}\n- 코드: 통과 — unittest 3/3\n- 브라우저: 해당 없음 — 검색 함수만, 화면 없음")


def write(root, p, t, mode="w"):
    full = os.path.join(root, p)
    os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
    with open(full, mode, encoding="utf-8", newline="\n") as f:
        f.write(t)


def init_repo(d, user="alice"):
    sh("git", "init", "-q", "-b", "main", cwd=d)
    for k, v in (("user.email", f"{user}@x"), ("user.name", user), ("core.autocrlf", "false")):
        sh("git", "config", k, v, cwd=d)


class PersonalRepo(unittest.TestCase):
    """개인 모드(docs/) 레포. 원격 없음."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="vf-c2-")
        self.d = os.path.join(self.root, "repo")
        os.makedirs(self.d)
        init_repo(self.d)
        for p, t in {
            "docs/REMAINING.md": "# 남은 업무\n\n- [ ] G-001 거래처 검색\n",
            "docs/WORKLOG.md": "# 작업 기록\n",
            "docs/NORTHSTAR.md": "# 노스스타\n<!-- status: confirmed -->\n## 목적\n검색\n",
            "docs/goals/G-001-search.md": GOAL.format(gid="G-001", st="active"),
            "app.py": "# app\n",
            ".gitignore": ".vibe/\n",
        }.items():
            write(self.d, p, t)
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-qm", "seed", cwd=self.d)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def ho(self, *args, cwd=None):
        return subprocess.run([PY, os.path.join(SCRIPTS, "handoff.py"), *args], cwd=cwd or self.d,
                              capture_output=True, text=True, encoding="utf-8")

    def git(self, *args, cwd=None):
        return sh("git", *args, cwd=cwd or self.d).stdout.strip()

    def work_and_record(self, mr=None, hdir="docs", cwd=None, user="alice"):
        """작업 커밋 → (QA) → 기록을 같은 커밋에 amend. mr=None이면 MR 파일을 넣지 않는다."""
        cwd = cwd or self.d
        write(cwd, "app.py", "def search(q):\n    return q\n", "a")
        sh("git", "commit", "-qam", "G-001 거래처 검색", cwd=cwd)
        tree = self.git("rev-parse", "HEAD^{tree}", cwd=cwd)
        if hdir == "docs":
            write(cwd, "docs/WORKLOG.md", "\n## 2026-10-17 G-001 거래처 검색\n- 검색 함수\n", "a")
        else:
            write(cwd, f"{hdir}/WORKLOG/proto.md",
                  f"\n## 2026-10-17 G-001 거래처 검색 @{user} #proto {{#2026-10-17-search-{user}}}\n- [x] 검색\n", "a")
            write(cwd, f"{hdir}/WORKLOG/INDEX.md",
                  f"- 2026-10-17 [proto] @{user} G-001 거래처 검색 → [proto.md](proto.md#2026-10-17-search-{user})\n", "a")
        p = os.path.join(cwd, hdir, "REMAINING.md")
        t = open(p, encoding="utf-8").read()
        t = re.sub(r"- \[~\] (G-001 [^(]*)\(착수 @\S+ [\d-]+\)[^\n]*", rf"- [x] \1(@{user} 2026-10-17)", t)
        write(cwd, f"{hdir}/REMAINING.md", t)
        if mr is not None:
            write(cwd, f"{hdir}/mr/G-001.md", mr.replace("{tree}", tree))
        sh("git", "add", "-A", cwd=cwd)
        sh("git", "commit", "-q", "--amend", "--no-edit", cwd=cwd)
        return tree


# ---------- 1. 로컬 모드 선점 ----------
class LocalModeClaimTest(PersonalRepo):
    def test_claim_without_remote_commits_locally_and_says_local_mode(self):
        r = self.ho("claim", "G-001", "거래처 검색", "feat/G-001-search")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        sha = self.git("rev-parse", "--short", "HEAD")
        self.assertIn(f"선점(로컬 모드 — 원격 없음): feat/G-001-search@{sha}", r.stdout)
        self.assertIn("[~] G-001", self.git("show", "HEAD:docs/REMAINING.md"))

    def test_config_remote_false_skips_push_even_with_origin(self):
        bare = os.path.join(self.root, "origin.git")
        sh("git", "clone", "-q", "--bare", self.d, bare, cwd=self.root)
        self.git("remote", "add", "origin", bare)
        self.git("fetch", "-q", "origin")
        write(self.d, ".vibe-flow.json", '{"base": "main", "remote": false}')
        self.git("add", ".vibe-flow.json")
        self.git("commit", "-qm", "cfg")
        r = self.ho("claim", "G-001", "거래처 검색", "feat/G-001-search")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("선점(로컬 모드 — 원격 없음): feat/G-001-search@", r.stdout)
        self.assertEqual(sh("git", "branch", "--list", "feat/G-001-search", cwd=bare).stdout.strip(), "")

    def test_claim_with_remote_pushes(self):
        bare = os.path.join(self.root, "origin.git")
        sh("git", "clone", "-q", "--bare", self.d, bare, cwd=self.root)
        clone = os.path.join(self.root, "A")
        sh("git", "clone", "-q", "-c", "core.autocrlf=false", bare, clone, cwd=self.root)
        for k, v in (("user.email", "alice@x"), ("user.name", "alice")):
            sh("git", "config", k, v, cwd=clone)
        r = self.ho("claim", "G-001", "거래처 검색", "feat/G-001-search", cwd=clone)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("push 확인됨", r.stdout)
        self.assertNotIn("로컬 모드", r.stdout)
        self.assertNotEqual(sh("git", "branch", "--list", "feat/G-001-search", cwd=bare).stdout.strip(), "")

    def test_no_push_flag_with_remote_is_not_called_local_mode(self):
        bare = os.path.join(self.root, "origin.git")
        sh("git", "clone", "-q", "--bare", self.d, bare, cwd=self.root)
        self.git("remote", "add", "origin", bare)
        self.git("fetch", "-q", "origin")
        r = self.ho("claim", "G-001", "거래처 검색", "feat/G-001-search", "--no-push")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("로컬 모드", r.stdout)
        self.assertIn("--no-push", r.stdout)
        self.assertEqual(sh("git", "branch", "--list", "feat/G-001-search", cwd=bare).stdout.strip(), "")


# ---------- 2. 기록 커밋의 MR 파일 ----------
class RecordMrFileTest(PersonalRepo):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.ho("claim", "G-001", "거래처 검색", "feat/G-001-search").returncode, 0)

    def test_check_record_requires_mr_file(self):
        self.work_and_record(mr=None)
        r = self.ho("check-record")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("docs/mr/G-001.md", r.stdout)

    def test_check_record_passes_with_mr_file(self):
        self.work_and_record(mr=MR_FILE)
        r = self.ho("check-record")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_check_record_rejects_mr_file_with_empty_qa(self):
        bad = MR_FILE.split("## QA 결과")[0] + "## QA 결과\n(진행 전)\n<!-- - 대상 commit: <sha> -->\n"
        self.work_and_record(mr=bad)
        r = self.ho("check-record")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("QA 결과", r.stdout)

    def test_check_record_rejects_mr_file_without_review_section(self):
        bad = re.sub(r"## 리뷰 기록\n.*?(?=## QA 결과)", "", MR_FILE, flags=re.S)
        self.work_and_record(mr=bad)
        r = self.ho("check-record")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("리뷰 기록", r.stdout)

    def test_check_record_rejects_mr_file_of_other_goal(self):
        self.work_and_record(mr=MR_FILE.replace("G-001", "G-009"))
        r = self.ho("check-record")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("G-001", r.stdout)

    def test_mr_file_does_not_break_qa_snapshot(self):
        """QA 대상(작업 커밋 tree) 뒤 기록 커밋에 MR 파일이 들어가도 merge 검사는 재검증을 요구하지 않는다."""
        tree = self.work_and_record(mr=MR_FILE)
        write(self.d, ".vibe/mr-G-001.md", MR_FILE.replace("{tree}", tree))
        r = subprocess.run([PY, os.path.join(SCRIPTS, "mr_check.py"), ".vibe/mr-G-001.md", "--stage", "merge"],
                           cwd=self.d, capture_output=True, text=True, encoding="utf-8")
        self.assertNotIn("재검증", r.stdout)

    def test_lint_ignores_links_inside_mr_file(self):
        """MR 파일의 캡처 링크는 .vibe/(추적 안 함)를 가리킬 수 있다 — 핸드오프 링크 검사 대상이 아니다."""
        mr = MR_FILE.replace("- 코드: 통과", "- 증거: ![A1](../../.vibe/qa/a1.png)\n- 코드: 통과")
        self.work_and_record(mr=mr)
        r = self.ho("lint")
        self.assertNotIn("끊긴 링크", r.stdout)


class TeamRecordMrFileTest(unittest.TestCase):
    """팀 모드: MR 파일은 docs/handoff/mr/G-###.md."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="vf-c2t-")
        seed = os.path.join(self.root, "seed")
        os.makedirs(seed)
        init_repo(seed, "seed")
        for p, t in {
            ".claude/skills/team-handoff/SKILL.md": "# team-handoff\n",
            "docs/handoff/REMAINING.md": "# 남은 업무\n\n- [ ] G-001 거래처 검색\n",
            "docs/handoff/WORKLOG/INDEX.md": "# INDEX\n",
            "docs/handoff/WORKLOG/proto.md": "# proto\n",
            "docs/handoff/NORTHSTAR.md": "# 노스스타\n<!-- status: confirmed -->\n## 목적\n검색\n",
            "docs/handoff/goals/G-001-search.md": GOAL.format(gid="G-001", st="active"),
            ".vibe-flow.json": '{"base": "main", "branch_prefixes": ["proto"]}',
            "app.py": "# app\n",
        }.items():
            write(seed, p, t)
        sh("git", "add", "-A", cwd=seed)
        sh("git", "commit", "-qm", "seed", cwd=seed)
        bare = os.path.join(self.root, "origin.git")
        sh("git", "clone", "-q", "--bare", seed, bare, cwd=self.root)
        self.a = os.path.join(self.root, "A")
        sh("git", "clone", "-q", "-c", "core.autocrlf=false", bare, self.a, cwd=self.root)
        for k, v in (("user.email", "alice@x"), ("user.name", "alice")):
            sh("git", "config", k, v, cwd=self.a)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_team_mode_mr_file_path(self):
        ho = PersonalRepo.ho
        r = ho(self, "claim", "G-001", "거래처 검색", "proto/G-001-search", cwd=self.a)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.git = lambda *a, cwd=None: sh("git", *a, cwd=cwd or self.a).stdout.strip()
        PersonalRepo.work_and_record(self, mr=None, hdir="docs/handoff", cwd=self.a)
        r = ho(self, "check-record", cwd=self.a)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("docs/handoff/mr/G-001.md", r.stdout)
        tree = self.git("rev-parse", "HEAD^{tree}")
        write(self.a, "docs/handoff/mr/G-001.md", MR_FILE.replace("{tree}", tree))
        sh("git", "add", "-A", cwd=self.a)
        sh("git", "commit", "-q", "--amend", "--no-edit", cwd=self.a)
        r = ho(self, "check-record", cwd=self.a)
        self.assertEqual(r.returncode, 0, r.stdout)


# ---------- 3. 방금 쓴 완료 줄은 lint 경고 아님 ----------
class LintFreshDoneTest(PersonalRepo):
    def lint_warns(self):
        r = self.ho("lint")
        return [l for l in r.stdout.splitlines() if "완료 항목" in l]

    def test_done_line_written_by_record_commit_is_not_warned(self):
        self.assertEqual(self.ho("claim", "G-001", "거래처 검색", "feat/G-001-search").returncode, 0)
        self.work_and_record(mr=MR_FILE)
        self.assertEqual(self.lint_warns(), [])

    def test_done_line_written_before_amend_is_not_warned(self):
        self.assertEqual(self.ho("claim", "G-001", "거래처 검색", "feat/G-001-search").returncode, 0)
        write(self.d, "app.py", "x = 1\n", "a")
        sh("git", "commit", "-qam", "G-001 구현", cwd=self.d)
        p = os.path.join(self.d, "docs/REMAINING.md")
        t = re.sub(r"- \[~\] (G-001 [^(]*)\([^\n]*", r"- [x] \1(@alice 2026-10-17)", open(p, encoding="utf-8").read())
        write(self.d, "docs/REMAINING.md", t)   # 아직 커밋 전(amend 직전)
        self.assertEqual(self.lint_warns(), [])

    def test_older_done_line_still_warned(self):
        self.assertEqual(self.ho("claim", "G-001", "거래처 검색", "feat/G-001-search").returncode, 0)
        self.work_and_record(mr=MR_FILE)
        # 다음 골: 지난 골의 [x]는 archive 대상
        write(self.d, "docs/goals/G-002-next.md", GOAL.format(gid="G-002", st="active"))
        write(self.d, "docs/REMAINING.md", "- [ ] G-002 다음 일\n", "a")
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-qm", "G-002 골", cwd=self.d)
        w = self.lint_warns()
        self.assertEqual(len(w), 1, w)
        self.assertIn("1건", w[0])


# ---------- 재감사 N-04·N-05·N-06·F-11 ----------
class MigrateConflictTest(PersonalRepo):
    """N-04: migrate가 만들 파일이 이미 있으면 덮어쓰지 않고 아무것도 바꾸지 않은 채 멈춘다."""

    def setUp(self):
        super().setUp()
        write(self.d, ".claude/skills/team-handoff/SKILL.md", "# team\n")
        write(self.d, "docs/handoff/REMAINING.md", "# 남은 업무\n")
        write(self.d, "docs/handoff/DECISIONS.md", "# 결정 기록\n\n> 머리말만\n")
        self.mon = datetime.date.today().strftime("%Y-%m")

    def assert_aborts_unchanged(self, existing):
        write(self.d, existing, "기존 내용 — 지우면 안 됨\n")
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-qm", "old", cwd=self.d)
        r = self.ho("migrate")
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(existing, r.stdout + r.stderr)
        self.assertEqual(open(os.path.join(self.d, existing), encoding="utf-8").read(), "기존 내용 — 지우면 안 됨\n")
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertFalse(os.path.exists(os.path.join(self.d, ".vibe", "migrate")))

    def test_existing_decision_body_of_this_month_is_not_overwritten(self):
        self.assert_aborts_unchanged(f"docs/handoff/DECISIONS-{self.mon}.md")

    def test_existing_plan_body_is_not_overwritten(self):
        write(self.d, "docs/handoff/PLAN.md", "# PLAN\n## 범위\nx\n")
        self.assert_aborts_unchanged("docs/handoff/PLAN-body.md")


class LintArchivedTopicTest(unittest.TestCase):
    """N-05: 보관 월 파일의 앵커도 INDEX 대조 대상이다(크기 경고만 뺀다)."""

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="vf-c2l-")
        self.old = os.getcwd()
        os.chdir(self.d)
        init_repo(self.d)
        write(self.d, ".vibe-flow.json", '{"base": "main", "index": {"topic_max_chars": 50}}')
        write(self.d, "docs/handoff/REMAINING.md", "# 남은 업무\n")
        write(self.d, "docs/handoff/WORKLOG/INDEX.md", "# INDEX\n- 2026-10-02 [ui] @alice 둘 → [ui.md](ui.md#u2)\n")
        write(self.d, "docs/handoff/WORKLOG/ui.md", "# ui\n\n## 2026-10-02 둘 {#u2}\n- x\n")
        write(self.d, "docs/handoff/WORKLOG/ui-2026-10.md",
              "# ui\n\n## 2026-10-01 하나 " + "가" * 80 + " {#u1}\n- x\n")

    def tearDown(self):
        os.chdir(self.old)
        shutil.rmtree(self.d, ignore_errors=True)

    def test_unindexed_anchor_in_archived_file_is_error(self):
        import hindex, vf_git
        err, warn = hindex.lint(vf_git.config())
        self.assertTrue(any("ui-2026-10.md#u1" in e for e in err), err)
        self.assertFalse(any("ui-2026-10.md" in w for w in warn), warn)


class GoalStatusAndIdBoundaryTest(PersonalRepo):
    def test_g000_needs_no_mr_file(self):
        """G-000(동작 불변)은 골 MR이 없다 — MR 사본을 요구하지 않는다."""
        write(self.d, "app.py", "# 주석 오타\n", "a")
        write(self.d, "docs/WORKLOG.md", "\n## 2026-10-17 G-000 오타\n", "a")
        write(self.d, "docs/REMAINING.md", "- [x] G-000 오타 (@alice 2026-10-17)\n", "a")
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-qm", "G-000 오타", cwd=self.d)
        r = self.ho("check-record")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_status_in_second_comment_is_read(self):
        """N-06: goal_gate.field()와 같은 규칙 — 파일 어디든 'status:' 줄."""
        write(self.d, "docs/goals/G-001-search.md",
              "# G-001 시험\n<!-- 문서 메모: 이 골은 검색 -->\n<!--\nid: G-001\nstatus: active\n-->\n")
        self.git("commit", "-qam", "goal note")
        r = self.ho("claim", "G-001", "거래처 검색", "feat/G-001-search")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_branch_with_letters_after_id_is_rejected(self):
        """F-11: G-001abc는 G-001이 아니다. feat/G-001-x는 맞다."""
        r = self.ho("claim", "G-001", "거래처 검색", "feat/G-001abc")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("골 ID가 없음", r.stderr)


class CheckRecordCommitIdsTest(unittest.TestCase):
    """M-07: --commit <sha>는 그 커밋 메시지에서만 골 ID를 얻는다 — 지금 체크아웃한 브랜치 이름은 섞지 않는다."""
    setUp = TeamRecordMrFileTest.setUp
    tearDown = TeamRecordMrFileTest.tearDown

    def test_commit_flag_ignores_current_branch_goal_id(self):
        ho = PersonalRepo.ho
        r = ho(self, "claim", "G-001", "거래처 검색", "proto/G-001-search", cwd=self.a)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.git = lambda *a, cwd=None: sh("git", *a, cwd=cwd or self.a).stdout.strip()
        PersonalRepo.work_and_record(self, mr=MR_FILE, hdir="docs/handoff", cwd=self.a)
        sha = self.git("rev-parse", "HEAD")
        self.assertEqual(ho(self, "check-record", cwd=self.a).returncode, 0)
        sh("git", "checkout", "-q", "-b", "proto/G-002-x", cwd=self.a)
        r = ho(self, "check-record", "--commit", sha, cwd=self.a)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("G-002", r.stdout)


if __name__ == "__main__":
    unittest.main()
