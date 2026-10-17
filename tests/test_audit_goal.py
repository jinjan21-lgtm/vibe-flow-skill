"""감사(tests/code-audit.md) F-05·F-06·F-07·F-12·F-14 회귀 테스트. 실행: python -m unittest tests/test_audit_goal.py -v

Codex는 부르지 않는다 — PATH 앞에 가짜 codex 명령을 둔다.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_scripts as ts  # 공용 도우미(sh, Repo, GOAL, MR_OK). 클래스 이름으로 가져오면 테스트가 두 번 돈다

SCRIPTS, PY, sh = ts.SCRIPTS, ts.PY, ts.sh

FAKE_CODEX = r'''import os, sys
a = sys.argv[1:]
out = a[a.index("-o") + 1]
sys.stdin.read()
mode = os.environ.get("FAKE_CODEX", "fail")
if mode == "confirm":
    with open(out, "w", encoding="utf-8") as f:
        f.write("CHECKED: 1 — app.py:1\nVERDICT: CONFIRM\n")   # 라운드 1은 완료 조건별 근거 필요
    sys.exit(0)
if mode == "partial":   # 출력은 남겼지만 실패
    with open(out, "w", encoding="utf-8") as f:
        f.write("VERDICT: CONFIRM\n")
sys.exit(3)
'''


def fake_codex_env(d, mode):
    """PATH 앞에 가짜 codex(Windows .cmd + POSIX sh)를 둔 환경."""
    b = os.path.join(d, "fakebin")
    os.makedirs(b, exist_ok=True)
    py = os.path.join(b, "fake_codex.py")
    with open(py, "w", encoding="utf-8") as f:
        f.write(FAKE_CODEX)
    with open(os.path.join(b, "codex.cmd"), "w", encoding="utf-8") as f:
        f.write(f'@"{PY}" "{py}" %*\r\n')
    sh_path = os.path.join(b, "codex")
    with open(sh_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(f'#!/bin/sh\nexec "{PY}" "{py}" "$@"\n')
    os.chmod(sh_path, 0o755)
    env = dict(os.environ, FAKE_CODEX=mode)
    env["PATH"] = b + os.pathsep + env.get("PATH", "")
    return env


class ReviewCodexFailureTest(ts.Repo):
    """F-05: Codex 실패 시 이전 라운드의 stale VERDICT를 돌려주면 안 된다."""

    def setUp(self):
        super().setUp()
        sh("git", "checkout", "-q", "-b", "G-001/test", cwd=self.d)   # review.py가 --stage review를 직접 검사한다
        import vf_git
        self.write("docs/DECISIONS.md", "# 결정\n\n## D-001 설계 판정\n- G-001 설계는 사람이 확정\n")   # MR_OK의 사람 판정 D-001
        self.write(".vibe-flow.json", '{"base": "%s"}' % vf_git.snapshot())
        self.write("mr.md", ts.MR_OK.format(plan="같음", review="", qa=""))
        self.write(".gitignore", ".vibe/\nmr.md\nfakebin/\n")
        self.write("app.py", "x = 1\n")

    def review(self, mode, *args):
        return subprocess.run([PY, os.path.join(SCRIPTS, "review.py"), "--mr", "mr.md", *args], cwd=self.d,
                              capture_output=True, text=True, encoding="utf-8", env=fake_codex_env(self.d, mode))

    def test_failed_codex_does_not_reuse_stale_round_verdict(self):
        os.makedirs(".vibe/review", exist_ok=True)
        self.write(".vibe/review/r1.txt", "VERDICT: CONFIRM\n")   # 예전 실행의 남은 결과
        r = self.review("fail", "--round", "1")
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("VERDICT CONFIRM", r.stdout)
        self.assertFalse(os.path.exists(".vibe/review/r1.txt"))
        self.assertFalse(os.path.exists(".vibe/review/r1.tree"))   # 실패한 라운드는 다음 라운드의 기준이 되면 안 된다

    def test_nonzero_exit_with_output_still_fails(self):
        r = self.review("partial", "--round", "1")
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("VERDICT CONFIRM", r.stdout)

    def test_failed_codex_does_not_reuse_stale_design_verdict(self):
        os.makedirs(".vibe/review", exist_ok=True)
        self.write(".vibe/review/d1.txt", "VERDICT: CONFIRM\n")
        r = self.review("fail", "--design", "1")
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("VERDICT CONFIRM", r.stdout)

    def test_successful_codex_still_confirms(self):
        r = self.review("confirm", "--round", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("VERDICT CONFIRM", r.stdout)
        self.assertTrue(os.path.exists(".vibe/review/r1.tree"))


class RevertMergeBypassTest(ts.Repo):
    """F-06: "Revert "/"Merge "로 시작하기만 하면 골 검사를 건너뛰던 문제."""

    def commit_msg(self, msg):
        self.write(".msg", msg)
        return self.run_script("goal_gate.py", "check-commit", ".msg")

    def base_commit(self):
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-qm", "base", cwd=self.d)
        return sh("git", "rev-parse", "HEAD", cwd=self.d).stdout.strip()

    def test_fake_revert_rejected(self):
        self.assertEqual(self.commit_msg("Revert any old unrelated work\n").returncode, 1)

    def test_fake_merge_rejected(self):
        self.assertEqual(self.commit_msg("Merge my stuff\n").returncode, 1)
        self.assertEqual(self.commit_msg("Merge branch 'x'\n").returncode, 1)   # 머지 중이 아니면 형식만으로는 안 됨

    def test_real_revert_allowed(self):
        self.base_commit()
        self.write("a.txt", "a\n")
        sha = self.base_commit()
        os.remove("a.txt")                                   # 스테이징이 실제로 그 커밋의 역
        sh("git", "add", "-A", cwd=self.d)
        self.assertEqual(self.commit_msg(f'Revert "base"\n\nThis reverts commit {sha}.\n').returncode, 0)

    def test_revert_of_unknown_commit_rejected(self):
        self.base_commit()
        self.assertEqual(self.commit_msg('Revert "x"\n\nThis reverts commit deadbeefdeadbeef.\n').returncode, 1)

    def test_real_merge_allowed(self):
        self.base_commit()
        sh("git", "checkout", "-qb", "f", cwd=self.d)
        self.write("b.txt", "b\n")
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-qm", "G-000 b", cwd=self.d)
        sh("git", "checkout", "-q", "main", cwd=self.d)
        self.write("c.txt", "c\n")
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-qm", "G-000 c", cwd=self.d)
        self.assertEqual(self.run_script("goal_gate.py", "install-hook").returncode, 0)
        r = sh("git", "merge", "--no-edit", "f", cwd=self.d, ok=False)   # 훅이 MERGE_HEAD 있는 상태로 불린다
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class InstallHookTest(ts.Repo):
    """F-12: 기존 commit-msg 훅을 덮어쓰지 않는다."""

    def hook(self, name="commit-msg"):
        return os.path.join(self.d, ".git", "hooks", name)

    def test_existing_hook_is_kept_and_chained(self):
        with open(self.hook(), "w", encoding="utf-8", newline="\n") as f:
            f.write('#!/bin/sh\necho OTHER-HOOK-RAN >&2\ngrep -q NOPE "$1" && exit 1\nexit 0\n')
        os.chmod(self.hook(), 0o755)
        r = self.run_script("goal_gate.py", "install-hook")
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.hook("commit-msg.local"), encoding="utf-8") as f:
            self.assertIn("OTHER-HOOK-RAN", f.read())
        self.assertEqual(self.run_script("goal_gate.py", "install-hook").returncode, 0)   # 다시 실행해도 같음
        with open(self.hook("commit-msg.local"), encoding="utf-8") as f:
            self.assertIn("OTHER-HOOK-RAN", f.read())
        sh("git", "add", "-A", cwd=self.d)
        r = sh("git", "commit", "-qm", "G-000 NOPE", cwd=self.d, ok=False)
        self.assertNotEqual(r.returncode, 0)                    # 기존 훅의 거부가 살아 있다
        self.assertIn("OTHER-HOOK-RAN", r.stderr)
        self.assertNotEqual(sh("git", "commit", "-qm", "no id", cwd=self.d, ok=False).returncode, 0)   # 골 게이트도
        self.assertEqual(sh("git", "commit", "-qm", "G-000 ok", cwd=self.d, ok=False).returncode, 0)

    def test_refuses_when_local_slot_taken(self):
        for n in ("commit-msg", "commit-msg.local"):
            with open(self.hook(n), "w", encoding="utf-8", newline="\n") as f:
                f.write(f"#!/bin/sh\n# {n}\nexit 0\n")
        r = self.run_script("goal_gate.py", "install-hook")
        self.assertNotEqual(r.returncode, 0)
        with open(self.hook(), encoding="utf-8") as f:
            self.assertIn("# commit-msg", f.read())               # 아무것도 덮어쓰지 않음

    def test_reinstall_is_idempotent(self):
        self.assertEqual(self.run_script("goal_gate.py", "install-hook").returncode, 0)
        self.assertEqual(self.run_script("goal_gate.py", "install-hook").returncode, 0)
        self.assertFalse(os.path.exists(self.hook("commit-msg.local")))


@unittest.skipUnless(shutil.which("node"), "node 없음")
class SyntaxCheckEmptyTest(unittest.TestCase):
    """F-14: 검사할 파일이 0개면 통과가 아니라 미검증(exit 2)."""

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="vf-syn-")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def run_check(self, *targets):
        return subprocess.run([PY, os.path.join(SCRIPTS, "syntax_check.py"), *targets], cwd=self.d,
                              capture_output=True, text=True, encoding="utf-8")

    def test_empty_folder_is_not_pass(self):
        r = self.run_check(self.d)
        self.assertEqual(r.returncode, 2, r.stdout)

    def test_missing_path_is_not_pass(self):
        self.assertEqual(self.run_check(os.path.join(self.d, "nope")).returncode, 2)

    def test_js_file_still_passes(self):
        with open(os.path.join(self.d, "a.js"), "w", encoding="utf-8") as f:
            f.write("const a = 1;\n")
        r = self.run_check(self.d)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("1/1", r.stdout)


class GoalIdRemoteReserveTest(unittest.TestCase):
    """F-07: 서로 push하지 않은 두 복제본이 같은 골 번호를 받지 않는다 (원격 refs/vibe-ids/G-###)."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="vf-gid-")
        seed = os.path.join(self.root, "seed")
        os.makedirs(os.path.join(seed, "docs", "goals"))
        sh("git", "init", "-q", "-b", "main", cwd=seed)
        for k, v in (("user.email", "s@s"), ("user.name", "seed"), ("core.autocrlf", "false")):
            sh("git", "config", k, v, cwd=seed)
        with open(os.path.join(seed, "docs", "goals", "G-001-s.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(ts.GOAL.format(gid="G-001", st="active"))
        sh("git", "add", "-A", cwd=seed)
        sh("git", "commit", "-qm", "seed", cwd=seed)
        self.bare = os.path.join(self.root, "origin.git")
        sh("git", "clone", "-q", "--bare", seed, self.bare, cwd=self.root)
        self.a, self.b = self.clone("A"), self.clone("B")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def clone(self, name):
        d = os.path.join(self.root, name)
        sh("git", "clone", "-q", "-c", "core.autocrlf=false", self.bare, d, cwd=self.root)
        for k, v in (("user.email", f"{name}@x"), ("user.name", name)):
            sh("git", "config", k, v, cwd=d)
        return d

    def reserve(self, cwd):
        return subprocess.run([PY, os.path.join(SCRIPTS, "goal_gate.py"), "reserve-id"], cwd=cwd,
                              capture_output=True, text=True, encoding="utf-8")

    def test_two_clones_get_different_ids(self):
        a, b = self.reserve(self.a), self.reserve(self.b)
        self.assertEqual(a.returncode, 0, a.stderr)
        self.assertEqual((a.stdout.strip(), b.stdout.strip()), ("G-002", "G-003"))
        refs = sh("git", "for-each-ref", "--format=%(refname)", "refs/vibe-ids", cwd=self.bare).stdout
        self.assertIn("refs/vibe-ids/G-002", refs)
        self.assertIn("refs/vibe-ids/G-003", refs)

    def test_scan_mode_skips_remote(self):
        with open(os.path.join(self.a, ".vibe-flow.json"), "w", encoding="utf-8") as f:
            f.write('{"index": {"id_reserve": "scan"}}')
        self.assertEqual(self.reserve(self.a).stdout.strip(), "G-002")
        self.assertEqual(sh("git", "for-each-ref", "refs/vibe-ids", cwd=self.bare).stdout.strip(), "")

    def test_remote_false_skips_remote(self):
        # 로컬 모드 설정이면 원격이 있어도 예약 ref를 올리지 않는다(claim·next_id와 같은 규칙)
        with open(os.path.join(self.a, ".vibe-flow.json"), "w", encoding="utf-8") as f:
            f.write('{"remote": false}')
        self.assertEqual(self.reserve(self.a).stdout.strip(), "G-002")
        self.assertEqual(sh("git", "for-each-ref", "refs/vibe-ids", cwd=self.bare).stdout.strip(), "")

    def test_unreachable_remote_refuses(self):
        sh("git", "remote", "set-url", "origin", os.path.join(self.root, "gone.git"), cwd=self.a)
        r = self.reserve(self.a)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "")


class GoalGateCodexExitTest(unittest.TestCase):
    """감사 범위 밖에서 찾은 같은 종류: 골 판정 Codex가 실패하면 남긴 VERDICT를 쓰지 않는다."""
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def run_with(self, mode):
        import importlib, sys as _s
        _s.path.insert(0, SCRIPTS)
        gg = importlib.import_module("goal_gate")
        old = dict(os.environ)
        os.environ.update(fake_codex_env(self.d, mode))
        try:
            return gg.run_codex("판정해 주세요")
        finally:
            os.environ.clear(); os.environ.update(old)

    def test_failed_run_with_verdict_is_empty(self):
        self.assertEqual(self.run_with("partial"), "")

    def test_successful_run_returns_verdict(self):
        self.assertIn("VERDICT: CONFIRM", self.run_with("confirm"))


class RevertPatchMatchTest(ts.Repo):
    """N-01: 본문에 "This reverts commit <실재 sha>"만 넣은 일반 변경이 골 검사를 건너뛰던 문제."""

    def commit(self, msg):
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-qm", msg, cwd=self.d)
        return sh("git", "rev-parse", "HEAD", cwd=self.d).stdout.strip()

    def check(self, msg):
        with open(os.path.join(self.d, ".git", "MSG"), "w", encoding="utf-8") as f:
            f.write(msg)
        return self.run_script("goal_gate.py", "check-commit", os.path.join(".git", "MSG"))

    def test_fake_footer_with_unrelated_change_rejected(self):
        self.commit("G-000 base")
        self.write("a.txt", "a\n")
        sha = self.commit("G-000 a")
        self.write("other.txt", "unrelated\n")              # 되돌리기가 아닌 변경
        sh("git", "add", "-A", cwd=self.d)
        r = self.check(f'Revert "a"\n\nThis reverts commit {sha}.\n')
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("골 ID", r.stderr)

    def test_revert_footer_with_nothing_staged_rejected(self):
        self.commit("G-000 base")
        self.write("a.txt", "a\n")
        sha = self.commit("G-000 a")
        self.assertEqual(self.check(f"x\n\nThis reverts commit {sha}.\n").returncode, 1)

    def test_root_commit_footer_not_exempt(self):
        sha = self.commit("G-000 base")
        self.write("x.txt", "x\n")
        sh("git", "add", "-A", cwd=self.d)
        self.assertEqual(self.check(f"x\n\nThis reverts commit {sha}.\n").returncode, 1)

    def test_real_git_revert_through_hook_allowed(self):
        self.assertEqual(self.run_script("goal_gate.py", "install-hook").returncode, 0)
        self.commit("G-000 base")
        self.write("a.txt", "a\nb\n")
        self.commit("G-000 a")
        self.write("a.txt", "a\nb\nc\n")
        sha = self.commit("G-000 c")
        sh("git", "checkout", "-q", "-b", "nogoal", cwd=self.d)    # 브랜치에도 골 ID 없음
        r = sh("git", "revert", "--no-edit", sha, cwd=self.d, ok=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("This reverts commit " + sha, sh("git", "log", "-1", "--format=%B", cwd=self.d).stdout)

    def test_revert_no_commit_then_commit_through_hook_allowed(self):
        # git 2.5x의 `git revert`는 commit-msg 훅을 부르지 않는다 — 훅이 실제로 보는 경로는 --no-commit 뒤 git commit
        self.assertEqual(self.run_script("goal_gate.py", "install-hook").returncode, 0)
        self.commit("G-000 base")
        self.write("a.txt", "a\nb\n")
        self.commit("G-000 a")
        self.write("a.txt", "a\nb\nc\n")
        sha = self.commit("G-000 c")
        sh("git", "checkout", "-q", "-b", "nogoal", cwd=self.d)
        sh("git", "revert", "--no-commit", sha, cwd=self.d)
        r = sh("git", "commit", "--no-edit", cwd=self.d, ok=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("This reverts commit " + sha, sh("git", "log", "-1", "--format=%B", cwd=self.d).stdout)

    def test_fake_footer_rejected_through_hook(self):
        self.assertEqual(self.run_script("goal_gate.py", "install-hook").returncode, 0)
        self.commit("G-000 base")
        self.write("a.txt", "a\n")
        sha = self.commit("G-000 a")
        self.write("other.txt", "unrelated\n")
        sh("git", "add", "-A", cwd=self.d)
        r = sh("git", "commit", "-qm", f'Revert "a"\n\nThis reverts commit {sha}.', cwd=self.d, ok=False)
        self.assertNotEqual(r.returncode, 0)


class InstallHookExecBitTest(ts.Repo):
    """N-02: git이 실행하지 않던(실행 권한 없는) 기존 훅을 연결해 모든 커밋이 Permission denied로 막히던 문제."""

    def hook(self, name="commit-msg"):
        return os.path.join(self.d, ".git", "hooks", name)

    def test_generated_hook_guards_exec_bit(self):
        self.assertEqual(self.run_script("goal_gate.py", "install-hook").returncode, 0)
        with open(self.hook(), encoding="utf-8") as f:
            text = f.read()
        self.assertIn('[ -x "$L" ]', text)
        self.assertNotIn('[ -f "$L" ]', text)

    @unittest.skipIf(os.name == "nt", "Windows git은 실행 비트를 보지 않는다")
    def test_non_executable_hook_not_chained(self):
        with open(self.hook(), "w", encoding="utf-8", newline="\n") as f:
            f.write("#!/bin/sh\necho DEAD-HOOK-RAN >&2\nexit 1\n")
        os.chmod(self.hook(), 0o644)
        r = self.run_script("goal_gate.py", "install-hook")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(self.hook("commit-msg.local")))     # 지우지 않고 보존
        sh("git", "add", "-A", cwd=self.d)
        r = sh("git", "commit", "-qm", "G-000 ok", cwd=self.d, ok=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("DEAD-HOOK-RAN", r.stderr)
        self.assertNotIn("Permission denied", r.stderr)



class CodexEffortTest(unittest.TestCase):
    """Codex 호출에 추론 강도를 명시한다 — 사용자 기본값(none 등)으로 리뷰가 얕아지지 않게."""
    def test_default_high_and_override(self):
        import importlib, sys as _s
        _s.path.insert(0, SCRIPTS)
        vg = importlib.import_module("vf_git")
        self.assertIn("model_reasoning_effort=high", vg.codex_cmd("o.txt", {}))
        self.assertIn("model_reasoning_effort=medium", vg.codex_cmd("o.txt", {"codex_effort": "medium"}))
        self.assertNotIn("-c", vg.codex_cmd("o.txt", {"codex_effort": ""}))


class RevertExactTreeTest(ts.Repo):
    """M-01: patch-id는 공백을 무시해 들여쓰기만 다른(파이썬에선 의미가 다른) "되돌리기"가 면제되던 문제."""

    def commit(self, msg):
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-qm", msg, cwd=self.d)
        return sh("git", "rev-parse", "HEAD", cwd=self.d).stdout.strip()

    def setup_c(self):
        self.write("f.py", "def f():\n    if True:\n        return 1\n    return 0\n")
        self.commit("G-000 base")
        self.write("f.py", "def f():\n    if True:\n        return 2\n    return 0\n")
        return self.commit("G-000 c")

    def test_whitespace_only_different_revert_rejected(self):
        sha = self.setup_c()
        self.write("f.py", "def f():\n    if True:\n    return 1\n    return 0\n")   # 들여쓰기가 깨진 "역"
        sh("git", "add", "-A", cwd=self.d)
        with open(os.path.join(self.d, ".git", "MSG"), "w", encoding="utf-8") as f:
            f.write(f'Revert "c"\n\nThis reverts commit {sha}.\n')
        r = self.run_script("goal_gate.py", "check-commit", os.path.join(".git", "MSG"))
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("골 ID", r.stderr)

    def test_whitespace_only_different_revert_rejected_through_hook(self):
        self.assertEqual(self.run_script("goal_gate.py", "install-hook").returncode, 0)
        sha = self.setup_c()
        sh("git", "checkout", "-q", "-b", "nogoal", cwd=self.d)
        self.write("f.py", "def f():\n    if True:\n    return 1\n    return 0\n")
        sh("git", "add", "-A", cwd=self.d)
        r = sh("git", "commit", "-qm", f'Revert "c"\n\nThis reverts commit {sha}.', cwd=self.d, ok=False)
        self.assertNotEqual(r.returncode, 0)

    def test_true_revert_no_commit_through_hook_allowed(self):
        self.assertEqual(self.run_script("goal_gate.py", "install-hook").returncode, 0)
        sha = self.setup_c()
        sh("git", "checkout", "-q", "-b", "nogoal", cwd=self.d)
        sh("git", "revert", "--no-commit", sha, cwd=self.d)
        r = sh("git", "commit", "--no-edit", cwd=self.d, ok=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("This reverts commit " + sha, sh("git", "log", "-1", "--format=%B", cwd=self.d).stdout)

    def test_revert_of_older_commit_with_later_unrelated_change_allowed(self):
        self.write("f.py", "x = 1\n")
        self.write("g.py", "y = 1\n")
        self.commit("G-000 base")
        self.write("f.py", "x = 2\n")
        sha = self.commit("G-000 c")
        self.write("g.py", "y = 2\n")
        self.commit("G-000 later")
        self.write("f.py", "x = 1\n")
        sh("git", "add", "-A", cwd=self.d)
        with open(os.path.join(self.d, ".git", "MSG"), "w", encoding="utf-8") as f:
            f.write(f'Revert "c"\n\nThis reverts commit {sha}.\n')
        r = self.run_script("goal_gate.py", "check-commit", os.path.join(".git", "MSG"))
        self.assertEqual(r.returncode, 0, r.stderr)


class InstallHookMarkerTest(ts.Repo):
    """F-12 잔여: 본문에 goal_gate.py라는 글자만 있어도 우리 훅으로 보고 덮어쓰던 문제."""

    def hook(self, name="commit-msg"):
        return os.path.join(self.d, ".git", "hooks", name)

    def test_foreign_hook_mentioning_goal_gate_preserved_and_chained(self):
        with open(self.hook(), "w", encoding="utf-8", newline="\n") as f:
            f.write('#!/bin/sh\n# runs before goal_gate.py\necho FOREIGN-RAN >&2\n'
                    'grep -q NOPE "$1" && exit 1\nexit 0\n')
        os.chmod(self.hook(), 0o755)
        r = self.run_script("goal_gate.py", "install-hook")
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.hook("commit-msg.local"), encoding="utf-8") as f:
            self.assertIn("FOREIGN-RAN", f.read())
        sh("git", "add", "-A", cwd=self.d)
        r = sh("git", "commit", "-qm", "G-000 NOPE", cwd=self.d, ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("FOREIGN-RAN", r.stderr)
        self.assertEqual(self.run_script("goal_gate.py", "install-hook").returncode, 0)   # 재설치해도 .local 유지
        with open(self.hook("commit-msg.local"), encoding="utf-8") as f:
            self.assertIn("FOREIGN-RAN", f.read())

    def test_previous_generated_hook_upgraded_in_place(self):
        script = os.path.join(SCRIPTS, "goal_gate.py").replace("\\", "/")
        with open(self.hook(), "w", encoding="utf-8", newline="\n") as f:
            f.write('#!/bin/sh\n'
                    'L="$(dirname "$0")/commit-msg.local"\n'
                    'if [ -x "$L" ]; then "$L" "$@" || exit $?; fi\n'
                    f'exec python "{script}" check-commit "$1"\n')
        r = self.run_script("goal_gate.py", "install-hook")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(self.hook("commit-msg.local")))
        with open(self.hook(), encoding="utf-8") as f:
            self.assertIn("# vibe-flow goal_gate hook v1", f.read())


if __name__ == "__main__":
    unittest.main()
