"""P0-3 회귀: QA 코드 통과는 실제 실행 기록(.vibe/qa/<tree>.json)과, 브라우저 증거는 실제 파일과 묶인다.
기록 커밋에는 <핸드오프>/mr/G-###-qa.json이 함께 있어야 한다.
실행: python -m unittest tests/test_c2_qa.py -v (레포 루트)"""
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_scripts import PY, SCRIPTS, sh  # noqa: E402
from test_c2_record import MR_FILE, PersonalRepo, init_repo, write  # noqa: E402

# 통과는 출력에서 읽은 수(passed ≥ 1)가 있어야 한다(A9-08) — 가짜 명령도 unittest 요약을 찍는다
PASS_CMD = f'"{PY}" -c "print(\'Ran 3 tests in 0.0s\'); print(); print(\'OK\')"'
FAIL_CMD = f'"{PY}" -c "import sys; print(\'boom\'); sys.exit(3)"'
LONG_CMD = f'"{PY}" -c "print(\'Ran 1 test in 0.0s\'); print(); print(\'OK\'); [print(i) for i in range(300)]"'
NOCOUNT_CMD = f'"{PY}" -c "print(1)"'


class QaRepo(unittest.TestCase):
    def setUp(self):
        self.old = os.getcwd()
        self.d = tempfile.mkdtemp(prefix="vf-qa-")
        init_repo(self.d)
        write(self.d, "app.py", "# app\n")
        write(self.d, ".gitignore", ".vibe/\n")
        self.cfg(PASS_CMD)
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-qm", "seed", cwd=self.d)

    def tearDown(self):
        os.chdir(self.old)
        shutil.rmtree(self.d, ignore_errors=True)

    def cfg(self, cmd):
        write(self.d, ".vibe-flow.json", json.dumps({"base": "main", **({"test_cmd": cmd} if cmd else {})}))

    def qa(self, *args):
        return subprocess.run([PY, os.path.join(SCRIPTS, "qa_run.py"), *args], cwd=self.d,
                              capture_output=True, text=True, encoding="utf-8")

    def tree(self):
        os.chdir(self.d)
        import vf_git
        return vf_git.snapshot()

    def verify(self, text):
        os.chdir(self.d)
        import qa_run
        import vf_git
        importlib.reload(qa_run)
        return qa_run.verify(text, vf_git.config())


class RunAndRecordTest(QaRepo):
    def test_pass_writes_record_and_prints_line(self):
        r = self.qa()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        tree = self.tree()
        p = os.path.join(self.d, ".vibe", "qa", f"{tree}.json")
        self.assertTrue(os.path.exists(p), r.stdout)
        rec = json.load(open(p, encoding="utf-8"))
        self.assertEqual(rec["tree"], tree)
        self.assertEqual(rec["exit"], 0)
        self.assertEqual(rec["cmd"], PASS_CMD)
        self.assertIn("Ran 3 tests", rec["tail"])
        self.assertEqual((rec["schema"], rec["passed"], rec["total"], rec["ok"]), (2, 3, 3, True))
        for k in ("started", "seconds"):
            self.assertIn(k, rec)
        self.assertIn(f"- 대상 tree: {tree}", r.stdout)
        self.assertRegex(r.stdout, rf"- 코드: 통과 — 3/3 통과, .* exit 0, [\d.]+s \(기록 \.vibe/qa/{tree}\.json\)")

    def test_no_counts_is_not_pass(self):   # A9-08: exit 0이어도 수를 읽을 수 없는 출력은 통과가 아니다
        self.cfg(NOCOUNT_CMD)
        r = self.qa()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        rec = json.load(open(os.path.join(self.d, ".vibe", "qa", f"{self.tree()}.json"), encoding="utf-8"))
        self.assertEqual((rec["exit"], rec["ok"]), (0, False))
        self.assertNotIn("passed", rec)
        self.assertIn("- 코드: 실패(테스트 수를 읽을 수 없음", r.stdout)
        self.assertNotRegex(r.stdout, r"- 코드: 통과")

    def test_fail_records_exit_and_mirrors_it(self):
        self.cfg(FAIL_CMD)
        r = self.qa()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        rec = json.load(open(os.path.join(self.d, ".vibe", "qa", f"{self.tree()}.json"), encoding="utf-8"))
        self.assertEqual(rec["exit"], 3)
        self.assertIn("boom", rec["tail"])
        self.assertRegex(r.stdout, r"- 코드: 실패 — .* exit 3")

    def test_tail_keeps_last_200_lines(self):
        self.cfg(LONG_CMD)
        self.assertEqual(self.qa().returncode, 0)
        rec = json.load(open(os.path.join(self.d, ".vibe", "qa", f"{self.tree()}.json"), encoding="utf-8"))
        lines = rec["tail"].splitlines()
        self.assertLessEqual(len(lines), 200)
        self.assertEqual(lines[-1], "299")
        self.assertEqual(lines[0], "100")

    def test_missing_test_cmd_is_unverified(self):
        self.cfg(None)
        r = self.qa()
        self.assertEqual(r.returncode, 2)
        self.assertIn("test_cmd 없음 — 미검증", r.stdout + r.stderr)
        self.assertFalse(os.path.isdir(os.path.join(self.d, ".vibe", "qa")))

    def test_mr_option_fills_qa_section(self):
        mr = os.path.join(self.d, ".vibe", "mr-G-001.md")
        write(self.d, ".vibe/mr-G-001.md", "## 골\nG-001\n## QA 결과\n- 대상 tree: 0000000\n- 코드: (진행 전)\n- 브라우저: 해당 없음 — 문서만\n")
        r = self.qa("--mr", mr)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        t = open(mr, encoding="utf-8").read()
        self.assertIn(f"- 대상 tree: {self.tree()}", t)
        self.assertNotIn("0000000", t)
        self.assertRegex(t, r"- 코드: 통과 — .* exit 0")
        self.assertIn("- 브라우저: 해당 없음 — 문서만", t)

    def test_mr_option_leaves_template_comment_alone(self):
        # 템플릿 그대로(「(진행 전)」 + 안내 주석 속 예시 줄)면 주석 밖에 줄을 넣고 예시는 그대로 둔다
        mr = os.path.join(self.d, ".vibe", "mr-G-001.md")
        tpl = "## QA 결과\n(진행 전)\n<!-- - 대상 commit: <sha>\n     - 코드: 통과 | 실패 — <명령> -->\n"
        write(self.d, ".vibe/mr-G-001.md", "## 골\nG-001\n" + tpl)
        self.assertEqual(self.qa("--mr", mr).returncode, 0)
        t = open(mr, encoding="utf-8").read()
        before, comment = t.split("<!--", 1)
        self.assertIn(f"- 대상 tree: {self.tree()}", before)
        self.assertRegex(before, r"- 코드: 통과 — .* exit 0")
        self.assertNotIn("(진행 전)", t)
        self.assertIn("- 대상 commit: <sha>", comment)


class VerifyTest(QaRepo):
    def code_qa(self, tree, browser="해당 없음 — 화면 없음", extra=""):
        return f"- 대상 tree: {tree}\n- 코드: 통과 — x\n- 브라우저: {browser}\n{extra}"

    def test_record_present_and_passing_is_ok(self):
        self.assertEqual(self.qa().returncode, 0)
        self.assertEqual(self.verify(self.code_qa(self.tree())), [])

    def test_missing_record_is_problem(self):
        miss = self.verify(self.code_qa(self.tree()))
        self.assertTrue(any("qa_run.py" in x for x in miss), miss)

    def test_failed_record_is_problem(self):
        self.cfg(FAIL_CMD)
        self.qa()
        miss = self.verify(self.code_qa(self.tree()))
        self.assertTrue(any("exit 3" in x for x in miss), miss)

    def test_tree_mismatch_is_problem(self):
        tree = self.tree()
        write(self.d, f".vibe/qa/{tree}.json", json.dumps({"tree": "a" * 40, "cmd": "x", "exit": 0}))
        miss = self.verify(self.code_qa(tree))
        self.assertTrue(any("tree" in x for x in miss), miss)

    def test_commit_target_resolves_to_tree(self):
        self.assertEqual(self.qa().returncode, 0)
        os.chdir(self.d)
        import vf_git
        head = vf_git.git("rev-parse", "HEAD")
        self.assertEqual(self.verify(f"- 대상 commit: {head[:7]}\n- 코드: 통과 — x\n"), [])

    def test_code_pass_without_target_is_problem(self):
        self.assertTrue(self.verify("- 코드: 통과 — x\n"))

    def test_code_fail_claim_needs_no_record(self):
        self.assertEqual(self.verify(f"- 대상 tree: {self.tree()}\n- 코드: 실패 — x\n"), [])

    def test_browser_image_missing_is_problem(self):
        self.qa()
        miss = self.verify(self.code_qa(self.tree(), "통과 — 검색 ✅", "- 증거: ![A1](.vibe/shots/A1.png)\n"))
        self.assertTrue(any(".vibe/shots/A1.png" in x for x in miss), miss)

    def test_browser_image_present_is_ok(self):
        self.qa()
        tree = self.tree()
        write(self.d, ".vibe/shots/A1.png", "png")
        self.assertEqual(self.verify(self.code_qa(tree, "통과 — 검색 ✅", "- 증거: ![A1](.vibe/shots/A1.png) [로그](https://x/y)\n")), [])

    def test_browser_text_only_evidence_is_problem(self):
        self.qa()
        miss = self.verify(self.code_qa(self.tree(), "통과 — 캡처함 A1.png"))
        self.assertTrue(any("증거" in x for x in miss), miss)

    def test_browser_http_only_evidence_is_problem(self):
        self.qa()
        miss = self.verify(self.code_qa(self.tree(), "통과", "- 증거: ![A1](https://x/A1.png)\n"))
        self.assertTrue(any("증거" in x for x in miss), miss)

    def test_never_raises(self):
        self.assertIsInstance(self.verify(None), list)
        write(self.d, f".vibe/qa/{self.tree()}.json", "{깨진 json")
        miss = self.verify(self.code_qa(self.tree()))
        self.assertTrue(miss)


class CheckRecordQaJsonTest(PersonalRepo):
    def setUp(self):
        super().setUp()
        r = self.ho("claim", "G-001", "거래처 검색", "feat/G-001-search")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def add_qa(self, exit_code):
        mr = open(os.path.join(self.d, "docs/mr/G-001.md"), encoding="utf-8").read()
        tree = re.search(r"대상 tree: ([0-9a-f]{40})", mr).group(1)   # work_and_record가 「QA 결과」에 쓴 tree
        write(self.d, "docs/mr/G-001-qa.json", json.dumps({"schema": 2, "tree": tree, "cmd": "t", "exit": exit_code,
                                                           "passed": 3 if exit_code == 0 else 2, "total": 3}))
        write(self.d, "docs/mr/G-001-review.md", "VERDICT: CONFIRM\n")
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-q", "--amend", "--no-edit", cwd=self.d)

    def test_requires_qa_json(self):
        self.work_and_record(mr=MR_FILE, qa=False)
        r = self.ho("check-record")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("docs/mr/G-001-qa.json", r.stdout)

    def test_rejects_failed_qa_json(self):
        self.work_and_record(mr=MR_FILE, qa=False)
        self.add_qa(1)
        r = self.ho("check-record")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("exit 1", r.stdout)

    def test_passes_with_passing_qa_json(self):
        self.work_and_record(mr=MR_FILE, qa=False)
        self.add_qa(0)
        r = self.ho("check-record")
        self.assertEqual(r.returncode, 0, r.stdout)


# ---------- J-03·J-04·J-05·증거 내보내기 ----------
class VerifyStrictTest(QaRepo):
    def test_cmd_changed_is_problem(self):   # J-03
        tree = self.tree()
        write(self.d, f".vibe/qa/{tree}.json", json.dumps({"tree": tree, "cmd": "old cmd", "exit": 0}))
        miss = self.verify(f"- 대상 tree: {tree}\n- 코드: 통과 — x\n")
        self.assertTrue(any("테스트 명령이 바뀜" in x for x in miss), miss)

    def test_browser_non_media_file_is_problem(self):   # J-04
        self.qa()
        write(self.d, ".vibe/shots/A1.txt", "로그")
        miss = self.verify(f"- 대상 tree: {self.tree()}\n- 코드: 통과 — x\n- 브라우저: 통과\n- 증거: [A1](.vibe/shots/A1.txt)\n")
        self.assertTrue(any("A1.txt" in x for x in miss), miss)

    def test_browser_video_is_ok(self):
        self.qa()
        tree = self.tree()
        write(self.d, ".vibe/shots/A1.webm", "v")
        write(self.d, ".vibe/shots/A2.JPEG", "j")
        self.assertEqual(self.verify(f"- 대상 tree: {tree}\n- 코드: 통과 — x\n- 브라우저: 통과\n"
                                     "- 증거: [A1](.vibe/shots/A1.webm) ![A2](.vibe/shots/A2.JPEG)\n"), [])


class CheckRecordStrictTest(PersonalRepo):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.ho("claim", "G-001", "거래처 검색", "feat/G-001-search").returncode, 0)

    def amend(self, path, text):
        if text is None:
            os.remove(os.path.join(self.d, path))
        else:
            write(self.d, path, text)
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-q", "--amend", "--no-edit", cwd=self.d)
        return self.ho("check-record")

    def test_fixture_passes(self):
        self.work_and_record(mr=MR_FILE)
        r = self.ho("check-record")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_qa_json_exit_only_is_problem(self):   # J-05
        self.work_and_record(mr=MR_FILE)
        r = self.amend("docs/mr/G-001-qa.json", '{"exit": 0}')
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("tree", r.stdout)

    def test_qa_json_other_tree_is_problem(self):
        self.work_and_record(mr=MR_FILE)
        r = self.amend("docs/mr/G-001-qa.json", json.dumps({"schema": 2, "tree": "b" * 40, "cmd": "t", "exit": 0,
                                                             "passed": 3, "total": 3}))
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("대상", r.stdout)

    def test_review_md_required(self):   # 리뷰 원문 영속
        self.work_and_record(mr=MR_FILE)
        r = self.amend("docs/mr/G-001-review.md", None)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("docs/mr/G-001-review.md", r.stdout)

    def test_review_md_needs_verdict(self):
        self.work_and_record(mr=MR_FILE)
        r = self.amend("docs/mr/G-001-review.md", "# 리뷰\n판정 없음\n")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("VERDICT", r.stdout)


class ExportEvidenceTest(PersonalRepo):
    def test_export_writes_review_qa_and_mr(self):
        tree = "c" * 40
        write(self.d, ".vibe/mr-G-001.md", MR_FILE.replace("{tree}", tree))
        rec = {"tree": tree, "cmd": "t", "exit": 0}
        write(self.d, f".vibe/qa/{tree}.json", json.dumps(rec))
        write(self.d, ".vibe/review/d1.txt", "설계 원문\nVERDICT: CONFIRM\n")
        br = self.git("symbolic-ref", "--short", "HEAD")   # 지금 브랜치·기준 도장(다른 맥락 원문은 export에서 빠진다)
        st = f"branch: {br}\nbase: {self.git('rev-parse', 'HEAD^{tree}')}\n"
        write(self.d, ".vibe/review/d1.meta", "goal: G-001\n" + st)
        write(self.d, ".vibe/review/r1.txt", "리뷰 원문\nVERDICT: CONFIRM\n")
        write(self.d, ".vibe/review/r1.tree", f"{tree}\ngoal: G-001\n" + st)
        write(self.d, ".vibe/review/r2.txt", "남의 골\nVERDICT: CHANGES\n")
        write(self.d, ".vibe/review/r2.tree", f"{tree}\ngoal: G-002\n" + st)
        r = self.ho("export-evidence", "G-001")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rv = open(os.path.join(self.d, "docs/mr/G-001-review.md"), encoding="utf-8").read()
        self.assertIn("설계 원문", rv)
        self.assertIn("리뷰 원문", rv)
        self.assertIn("d1.txt", rv)
        self.assertNotIn("남의 골", rv)
        self.assertEqual(json.load(open(os.path.join(self.d, "docs/mr/G-001-qa.json"), encoding="utf-8")), rec)
        self.assertTrue(os.path.exists(os.path.join(self.d, "docs/mr/G-001.md")))

    def test_export_without_qa_record_fails(self):
        write(self.d, ".vibe/mr-G-001.md", MR_FILE.replace("{tree}", "d" * 40))
        r = self.ho("export-evidence", "G-001")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("qa_run.py", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
