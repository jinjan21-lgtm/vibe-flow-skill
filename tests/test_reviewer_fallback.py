"""리뷰어 분기: Codex가 없으면 별도 Claude 프로세스(claude -p, 읽기 전용 도구)가 골 판정·설계 확인·리뷰를 맡는다.
실행: python -m unittest tests/test_reviewer_fallback.py -v"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import vf_git  # noqa: E402


def which_of(*present):
    return lambda name: f"/bin/{name}" if name in present else None


class ReviewerChoiceTest(unittest.TestCase):
    def test_auto_prefers_codex(self):
        with mock.patch.object(vf_git.shutil, "which", which_of("codex", "claude")):
            self.assertEqual(vf_git.reviewer({}), "codex")

    def test_auto_falls_back_to_claude(self):
        with mock.patch.object(vf_git.shutil, "which", which_of("claude")):
            self.assertEqual(vf_git.reviewer({}), "claude")

    def test_none_when_neither(self):
        with mock.patch.object(vf_git.shutil, "which", which_of()):
            self.assertIsNone(vf_git.reviewer({}))

    def test_explicit_choice_is_not_swapped(self):   # 명시한 리뷰어가 없으면 다른 것으로 몰래 바꾸지 않는다
        with mock.patch.object(vf_git.shutil, "which", which_of("claude")):
            self.assertIsNone(vf_git.reviewer({"reviewer": "codex"}))
        with mock.patch.object(vf_git.shutil, "which", which_of("codex", "claude")):
            self.assertEqual(vf_git.reviewer({"reviewer": "claude"}), "claude")


class ClaudeCmdTest(unittest.TestCase):
    def test_read_only_isolated(self):
        cmd = vf_git.claude_cmd({})
        self.assertEqual(cmd[:2], ["claude", "-p"])
        tools = cmd[cmd.index("--tools") + 1]
        self.assertEqual(set(tools.split(",")), {"Read", "Grep", "Glob"})   # 고치거나 실행하는 도구 없음
        self.assertIn("--no-session-persistence", cmd)
        self.assertEqual(cmd[cmd.index("--setting-sources") + 1], "")
        self.assertIn("--append-system-prompt", cmd)

    def test_model_option(self):
        cmd = vf_git.claude_cmd({"claude_model": "opus"})
        self.assertEqual(cmd[cmd.index("--model") + 1], "opus")


class RunReviewerTest(unittest.TestCase):
    def test_claude_stdout_becomes_output_file(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "o.txt")
            fake = mock.Mock(returncode=0, stdout=b"VERDICT: CONFIRM\n", stderr=b"")
            with mock.patch.object(vf_git.shutil, "which", which_of("claude")), \
                 mock.patch.object(vf_git.subprocess, "run", return_value=fake) as run:
                name, rc, body, err = vf_git.run_reviewer("프롬프트", out, 60, {})
            self.assertEqual((name, rc), ("claude", 0))
            self.assertIn("VERDICT: CONFIRM", body)
            self.assertIn("VERDICT: CONFIRM", open(out, encoding="utf-8").read())
            self.assertEqual(run.call_args.kwargs["input"], "프롬프트".encode("utf-8"))

    def test_no_reviewer_is_failure_not_pass(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(vf_git.shutil, "which", which_of()):
                name, rc, body, err = vf_git.run_reviewer("p", os.path.join(d, "o.txt"), 60, {})
        self.assertIsNone(name)
        self.assertNotEqual(rc, 0)
        self.assertEqual(body, "")


if __name__ == "__main__":
    unittest.main()
