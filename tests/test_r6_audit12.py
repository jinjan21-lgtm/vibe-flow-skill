"""12차 감사(A11-01·A11-04 잔여, A12-01) 회귀 시험. 실행: python -m unittest tests/test_r6_audit12.py -v"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_r6_engine import Engine  # noqa: E402
from test_scripts import sh  # noqa: E402

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, SCRIPTS)


class JsIdTest(unittest.TestCase):
    """A11-01 잔여: JS 테스트 식별자(jest '›', vitest '>')를 근거·회귀·실행 대조가 같은 모양으로 다룬다."""

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="vf-js-")
        self.old = os.getcwd()
        os.chdir(self.d)
        os.makedirs("src")
        with open("src/app.test.ts", "w", encoding="utf-8") as f:
            f.write("describe('Account', () => {\n  test('logs in', () => {})\n})\n")

    def tearDown(self):
        os.chdir(self.old)
        shutil.rmtree(self.d, ignore_errors=True)

    def test_ids_exists_and_match(self):
        import mr_check
        self.assertEqual(mr_check.test_ids("src/app.test.ts › Account › logs in (src/app.ts:3)"),
                         ["src/app.test.ts › Account › logs in"])
        self.assertTrue(mr_check.test_exists("src/app.test.ts › Account › logs in"))
        self.assertFalse(mr_check.test_exists("src/app.test.ts › Account › ghost"))
        self.assertEqual(mr_check.checked_ref_problems("src/app.test.ts › Account › logs in", True), [])
        self.assertTrue(mr_check.test_match("src/app.test.ts > Account > logs in", "src/app.test.ts › Account › logs in"))
        self.assertFalse(mr_check.test_match("src/app.test.ts › Account › logs in", "src/b.test.ts › Account › logs in"))
        self.assertIn("./src/app.test.ts", [p.replace("\\", "/") for p in mr_check._test_files()])

    def test_python_ids_unchanged(self):
        import mr_check
        self.assertEqual(mr_check.test_ids("test_app.T.test_partial (app.py:2), tests/x.py::test_y"),
                         ["test_app.T.test_partial", "tests/x.py::test_y"])


R1_UNMET = ("ROUND: 1\nRESOLVED: 없음\nFINDING: F1 | blocker | app.py:2 | 완료 조건 1 | 고친다\n"
            "CHECKED: 1 — 미충족 — F1\nVERDICT: CHANGES\n")
R2_EARLY_EVIDENCE = "ROUND: 2\nRESOLVED: 없음\nFINDING: F1 | blocker | app.py:2 | 아직 | 고친다\nVERDICT: CHANGES\n"


class OrderTest(Engine):
    """A12-01: 지적이 닫히기 전에 단 근거는 확정 근거가 아니다(미충족 → RESOLVED → 새 근거)."""

    def test_evidence_before_resolution_rejected(self):
        # review.py는 r2의 '근거 + 열린 blocker'를 받으므로, 순서 위반은 원문 수정으로 만든다(merge 재검사의 대상)
        self.flow(rounds=(R1_UNMET, R2_EARLY_EVIDENCE, "ROUND: 3\nRESOLVED: F1\nVERDICT: CONFIRM\n"))
        p = ".vibe/review/r2.txt"
        self.write(p, self.read(p).replace("VERDICT: CHANGES", "CHECKED: 1 — test_app.T.test_partial\nVERDICT: CHANGES"))
        r = self.run_py("mr_check.py", ".vibe/mr-G-001.md", "--stage", "merge")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("완료 조건 1번의 확인 근거 없음", r.stdout)

    def test_out_of_range_later_checked_rejected(self):
        self.flow(rounds=(R1_UNMET, "ROUND: 2\nRESOLVED: F1\nCHECKED: 1 — test_app.T.test_partial\nVERDICT: CONFIRM\n"))
        p = ".vibe/review/r2.txt"
        self.write(p, self.read(p).replace("VERDICT: CONFIRM", "CHECKED: 7 — test_app.T.test_partial\nVERDICT: CONFIRM"))
        self.assertIn("CHECKED 번호 7가 완료 조건 1~1 밖", self.run_py("mr_check.py", ".vibe/mr-G-001.md", "--stage", "merge").stdout)


class VibeLinkTest(Engine):
    """A11-04 잔여: 커밋이 .vibe를 담고 있으면(링크 포함) 재연은 쓰기 전에 거부한다."""

    def test_committed_vibe_rejected(self):
        self.template("base", self.flow)
        self.record()
        self.write(".vibe-trap/x.txt", "x")
        sh("git", "add", "-f", ".vibe-trap/x.txt", cwd=self.d)
        # .vibe 자체를 추적 파일로(링크 대신 — 윈도 권한 없이 재현 가능한 같은 경로)
        sh("git", "mv", ".vibe-trap", ".vibe-tracked", cwd=self.d)
        os.makedirs(os.path.join(self.root, "stash"), exist_ok=True)
        shutil.move(os.path.join(self.d, ".vibe"), os.path.join(self.root, "stash", ".vibe"))
        self.write(".vibe", "not a dir\n")
        sh("git", "add", "-f", ".vibe", cwd=self.d)
        sh("git", "commit", "-q", "--amend", "--no-edit", cwd=self.d)
        clone = os.path.join(self.root, "clone")
        sh("git", "clone", "-q", "--no-local", "-b", "feat/G-001-search", self.d, clone, cwd=self.root)
        r = self.run_py("handoff.py", "verify-evidence", "G-001", cwd=clone)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(".vibe가 커밋에 들어 있음", r.stdout)


if __name__ == "__main__":
    unittest.main()
