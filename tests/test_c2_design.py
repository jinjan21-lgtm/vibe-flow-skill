"""설계 확인을 실제 사전 관문으로, 리뷰 기록에 근거를 (외부 평가 C2). 실행: python -m unittest tests/test_c2_design.py -v

기준은 main 커밋(.vibe-flow.json·.gitignore 포함)이라 설정 파일이 diff에 끼지 않는다.
Codex는 PATH 앞에 둔 가짜 codex가 FAKE_CODEX_REPLY 파일 내용을 -o 파일에 쓴다.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_scripts import MR_OK, PY, SCRIPTS, Repo, sh  # noqa: E402

FAKE = r'''import os, sys
a = sys.argv
out = a[a.index("-o") + 1]
sys.stdin.read()
open(os.environ["FAKE_CODEX_CALLED"], "a").write("x")
with open(os.environ["FAKE_CODEX_REPLY"], encoding="utf-8") as f:
    body = f.read()
with open(out, "w", encoding="utf-8") as f:
    f.write(body)
'''

SKIP = "- 생략: 작은 변경 (예상 5줄·1파일)"
TWO_CONDS = "- [ ] 부분 일치 검색\n- [ ] 0건이면 안내 문구"


def lines(n, tag):
    return "\n".join(f"{tag}{j} = {j}" for j in range(n)) + "\n"


class C2(Repo):
    def setUp(self):
        super().setUp()
        self.write(".gitignore", "mr.md\n.vibe/\n")
        self.write(".vibe-flow.json", '{"base": "main"}')
        self.write("app.py", "def search(q):\n    return []\n")
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-qm", "G-000 기준", cwd=self.d)
        sh("git", "checkout", "-q", "-b", "G-001/test", cwd=self.d)
        self.bin = tempfile.mkdtemp(prefix="vf-bin-")
        with open(os.path.join(self.bin, "fake_codex.py"), "w", encoding="utf-8") as f:
            f.write(FAKE)
        fake = os.path.join(self.bin, "fake_codex.py")
        with open(os.path.join(self.bin, "codex.cmd"), "w") as f:
            f.write(f'@"{PY}" "{fake}" %*\n')
        posix = os.path.join(self.bin, "codex")
        with open(posix, "w", newline="\n") as f:
            f.write(f'#!/bin/sh\nexec "{PY}" "{fake}" "$@"\n')
        os.chmod(posix, 0o755)
        self.called = os.path.join(self.bin, "called")
        self.reply = os.path.join(self.bin, "reply.txt")

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.bin, ignore_errors=True)

    def mr(self, confirm="- 확인 1: blocker 0\n- 판정: 확정", plan="같음", review="(진행 전)", qa="(진행 전)",
           conds=None):
        b = MR_OK.format(plan=plan, review=review, qa=qa)
        b = re.sub(r"## 설계 확인\n.*?(?=## 계획 vs 실제)", lambda m: "## 설계 확인\n" + confirm + "\n", b, flags=re.S)
        if conds is not None:
            b = re.sub(r"- \[[ x]\] 부분 일치 검색", lambda m: conds, b, count=1)
        self.write("mr.md", b)

    def stage(self, st):
        return self.run_script("mr_check.py", "mr.md", "--stage", st)

    def codex(self, script, *args, reply="VERDICT: CONFIRM\n"):
        with open(self.reply, "w", encoding="utf-8") as f:
            f.write(reply)
        env = {**os.environ, "PATH": self.bin + os.pathsep + os.environ["PATH"],
               "FAKE_CODEX_REPLY": self.reply, "FAKE_CODEX_CALLED": self.called}
        return subprocess.run([PY, os.path.join(SCRIPTS, script), *args], cwd=self.d, env=env,
                              capture_output=True, text=True, encoding="utf-8")


class SkipSizeTest(C2):
    """1. 생략 크기는 코드만 센다 — 골 파일·REMAINING·WORKLOG는 코드 위험이 아니다."""

    def test_records_do_not_count_toward_design_skip(self):
        self.write("docs/goals/G-002-next.md", lines(40, "g"))
        self.write("docs/REMAINING.md", lines(15, "r"))
        self.write("docs/WORKLOG.md", lines(15, "w"))
        self.write("app.py", "def search(q):\n    return [x for x in DATA if q in x]\n")
        self.mr(confirm=SKIP)
        r = self.stage("review")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_records_do_not_trigger_size_warning(self):
        for i in range(12):
            self.write(f"docs/goals/G-1{i:02d}-x.md", "x\n")
        self.mr()
        self.assertNotIn("[size]", self.stage("review").stdout)


class SkipPreGateTest(C2):
    """2a·2c. 생략은 구현 전 예상치를 적고, build 단계에서도 지금 크기를 본다."""

    def test_skip_needs_estimate(self):
        self.mr(confirm="- 생략: 작은 변경")
        r = self.stage("build")
        self.assertEqual(r.returncode, 1)
        self.assertIn("예상", r.stdout)
        self.mr(confirm=SKIP)
        self.assertEqual(self.stage("build").returncode, 0)

    def test_build_catches_overrun_while_skipped(self):
        for i in range(5):
            self.write(f"m{i}.py", lines(30, "v"))
        self.mr(confirm=SKIP)
        r = self.stage("build")
        self.assertEqual(r.returncode, 1)
        self.assertIn("review.py --design", r.stdout)


class DesignBaseTreeTest(C2):
    """2b. 설계 확인은 기준 커밋 내용을 본다. 구현이 먼저 시작됐으면 드러낸다."""

    def test_design_payload_uses_base_tree(self):
        self.mr(confirm="(진행 전)")
        r = self.run_script("review.py", "--design", "1", "--mr", "mr.md", "--dry")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("구현 선행", r.stdout + r.stderr)
        self.write("app.py", "def search(q):\n    return q  # 이미 구현\n")
        r = self.run_script("review.py", "--design", "1", "--mr", "mr.md", "--dry")
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(r.stdout.strip(), encoding="utf-8") as f:
            payload = f.read()
        self.assertIn("app.py (기준 커밋)", payload)
        self.assertIn("return []", payload)
        self.assertNotIn("이미 구현", payload)
        self.assertIn("구현이 설계 확인보다 먼저", payload)
        self.assertIn("순서: 구현 선행", r.stderr)

    def test_post_hoc_design_must_be_declared(self):
        self.mr(confirm="(진행 전)")
        r = self.codex("review.py", "--design", "1", "--mr", "mr.md")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(".vibe/review/d1.meta", encoding="utf-8") as f:
            self.assertIn("diverged: no", f.read())
        self.write("app.py", "def search(q):\n    return q\n")
        self.mr()
        self.assertEqual(self.stage("review").returncode, 0)        # 설계 확인 뒤 구현 — 순서 줄 불필요
        os.remove(".vibe/review/d1.txt")
        r = self.codex("review.py", "--design", "1", "--mr", "mr.md")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(".vibe/review/d1.meta", encoding="utf-8") as f:
            self.assertIn("diverged: yes", f.read())
        r = self.stage("review")
        self.assertEqual(r.returncode, 1)
        self.assertIn("구현 선행", r.stdout)
        self.mr(confirm="- 확인 1: blocker 0\n- 판정: 확정\n- 순서: 구현 선행 (장애 대응으로 먼저 고침)")
        self.assertEqual(self.stage("review").returncode, 0, self.stage("review").stdout)


class StageGateInReviewTest(C2):
    """3. review.py는 단계 검사를 직접 돌린다 — 막힌 상태에서 Codex를 부르지 않는다."""

    def test_round_refused_when_review_stage_fails(self):
        self.write("app.py", "def search(q):\n    return q\n")
        self.mr(plan="(진행 전)")
        r = self.codex("review.py", "--round", "1", "--mr", "mr.md")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("계획 vs 실제", r.stdout + r.stderr)
        self.assertFalse(os.path.exists(self.called))
        self.assertFalse(os.path.exists(".vibe/review/r1.tree"))

    def test_design_refused_when_draft_stage_fails(self):
        self.mr(confirm="(진행 전)")
        with open("mr.md", encoding="utf-8") as f:
            body = f.read().replace("- 테스트 계획: 부분 일치 테스트 먼저\n", "")
        self.write("mr.md", body)
        r = self.codex("review.py", "--design", "1", "--mr", "mr.md")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("테스트 계획", r.stdout + r.stderr)
        self.assertFalse(os.path.exists(self.called))


class CheckedEvidenceTest(C2):
    """4. 라운드 1은 완료 조건마다 CHECKED 근거 줄이 있어야 유효하다."""

    def test_prompt_requires_checked_lines(self):
        with open(os.path.join(SCRIPTS, "..", "templates", "review-prompt.md"), encoding="utf-8") as f:
            self.assertIn("CHECKED:", f.read())

    def test_round_one_without_enough_checked_is_invalid(self):
        self.write("app.py", "def search(q):\n    return q\n")
        self.mr(conds=TWO_CONDS)
        thin = "ROUND: 1\nRESOLVED: 없음\nCHECKED: 1 — tests/test_app.py::test_partial\nVERDICT: CONFIRM\n"
        r = self.codex("review.py", "--round", "1", "--mr", "mr.md", reply=thin)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("0건이면 안내 문구", r.stdout + r.stderr)
        self.assertTrue(os.path.exists(".vibe/review/r1.txt.failed"))
        self.assertFalse(os.path.exists(".vibe/review/r1.txt"))
        self.assertFalse(os.path.exists(".vibe/review/r1.tree"))
        full = thin.replace("VERDICT", "CHECKED: 2 — app.py:2\nVERDICT")
        r = self.codex("review.py", "--round", "1", "--mr", "mr.md", reply=full)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.exists(".vibe/review/r1.tree"))
        self.assertIn("근거 2", r.stdout)


class UncheckedConditionMergeTest(C2):
    """5. 완료 조건에 [ ]가 남으면 머지 불가."""

    def test_merge_blocked_by_unchecked_condition(self):
        self.write("app.py", "def search(q):\n    return q\n")
        import vf_git
        qa = f"- 대상 tree: {vf_git.snapshot()}\n- 코드: 통과\n- 브라우저: 해당 없음 — 서버 함수만, 화면 없음"
        self.mr(review="- 라운드 1: x\n- 판정: 확정", qa=qa, conds="- [x] 부분 일치 검색\n- [ ] 0건이면 안내 문구")
        r = self.stage("merge")
        self.assertEqual(r.returncode, 1)
        self.assertIn("완료 조건 미체크 1개", r.stdout)
        self.mr(review="- 라운드 1: x\n- 판정: 확정", qa=qa, conds="- [x] 부분 일치 검색\n- [x] 0건이면 안내 문구")
        r = self.stage("merge")
        self.assertEqual(r.returncode, 0, r.stdout)


class RoundValidityTest(C2):
    """N-03. 라운드는 판정 출력(VERDICT)과 스냅샷이 둘 다 있어야 끝난 것이다."""

    GOOD = "ROUND: 1\nRESOLVED: 없음\nCHECKED: 1 — app.py:2\nVERDICT: CHANGES\n"

    def setUp(self):
        super().setUp()
        self.write("app.py", "def search(q):\n    return q\n")
        self.mr()

    def test_failed_rerun_invalidates_round(self):
        self.assertEqual(self.codex("review.py", "--round", "1", "--mr", "mr.md", reply=self.GOOD).returncode, 0)
        r = self.codex("review.py", "--round", "1", "--mr", "mr.md", reply="")       # Codex 실패
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(".vibe/review/r1.tree"))
        r = self.codex("review.py", "--round", "2", "--mr", "mr.md", reply=self.GOOD.replace("ROUND: 1", "ROUND: 2"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("건너뛸 수 없", r.stderr)

    def test_round_two_needs_valid_previous_output(self):
        import vf_git
        os.makedirs(".vibe/review", exist_ok=True)
        self.write(".vibe/review/r1.tree", vf_git.snapshot())
        r = self.run_script("review.py", "--round", "2", "--mr", "mr.md", "--dry")     # r1.txt 없음
        self.assertNotEqual(r.returncode, 0)
        self.write(".vibe/review/r1.txt", "아무 말\n")                                  # VERDICT 없음
        r = self.run_script("review.py", "--round", "2", "--mr", "mr.md", "--dry")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("건너뛸 수 없", r.stderr)

    def test_missing_verdict_invalidates_round(self):
        r = self.codex("review.py", "--round", "1", "--mr", "mr.md", reply=self.GOOD.replace("VERDICT: CHANGES\n", ""))
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(".vibe/review/r1.tree"))
        self.assertFalse(os.path.exists(".vibe/review/r1.txt"))

    def test_design_two_needs_valid_first_output(self):
        self.mr(confirm="(진행 전)")
        os.makedirs(".vibe/review", exist_ok=True)
        self.write(".vibe/review/d1.txt", "아무 말\n")
        r = self.run_script("review.py", "--design", "2", "--mr", "mr.md", "--dry")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("건너뛸 수 없", r.stderr)


class GoalIdSuffixTest(C2):
    """F-04 잔여. G-001 뒤에 글자·숫자가 붙으면 다른 ID다."""

    def test_branch_with_letter_suffix_is_not_a_match(self):
        sh("git", "branch", "-m", "G-001abc/test", cwd=self.d)
        self.mr()
        r = self.stage("claim")
        self.assertEqual(r.returncode, 1)
        self.assertIn("브랜치", r.stdout)
        sh("git", "branch", "-m", "feat/G-001-x", cwd=self.d)
        self.assertEqual(self.stage("claim").returncode, 0, self.stage("claim").stdout)

    def test_goal_file_with_letter_suffix_is_not_a_match(self):
        self.write("docs/goals/G-007abc.md", "# x\n<!--\nid: G-007abc\nstatus: active\n-->\n")
        sh("git", "branch", "-m", "G-007/test", cwd=self.d)
        with open("mr.md", "w", encoding="utf-8") as f:
            f.write(MR_OK.format(plan="", review="", qa="").replace("G-001 시험 골", "G-007 시험 골"))
        r = self.stage("claim")
        self.assertIn("G-007 골 파일 없음", r.stdout)



class NumberedCheckedTest(C2):
    """M-02. CHECKED는 완료 조건 번호(1..N)마다 정확히 한 줄 — 아무 말 두 줄로 두 조건을 채우지 못한다."""

    def setUp(self):
        super().setUp()
        self.write("app.py", "def search(q):\n    return q\n")
        self.mr(conds=TWO_CONDS)

    def round1(self, checked):
        return self.codex("review.py", "--round", "1", "--mr", "mr.md",
                          reply="ROUND: 1\nRESOLVED: 없음\n" + checked + "VERDICT: CONFIRM\n")

    def test_payload_lists_numbered_conditions(self):
        r = self.run_script("review.py", "--round", "1", "--mr", "mr.md", "--dry")
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(r.stdout.strip(), encoding="utf-8") as f:
            payload = f.read()
        self.assertIn("1. 부분 일치 검색", payload)
        self.assertIn("2. 0건이면 안내 문구", payload)

    def test_arbitrary_checked_lines_are_invalid(self):
        for bad in ("CHECKED: arbitrary — x\nCHECKED: arbitrary — y\n",       # 번호 없음
                    "CHECKED: 1 — app.py:2\nCHECKED: 1 — app.py:3\n",          # 중복
                    "CHECKED: 1 — app.py:2\nCHECKED: 3 — app.py:3\n",          # 범위 밖
                    "CHECKED: 1 — app.py:2\nCHECKED: 2 — app.py:3\nCHECKED: 3 — x\n"):
            r = self.round1(bad)
            self.assertNotEqual(r.returncode, 0, bad)
            self.assertFalse(os.path.exists(".vibe/review/r1.tree"), bad)
        r = self.round1("CHECKED: 2 — app.py:2\nCHECKED: 1 — tests/test_app.py::test_partial\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.exists(".vibe/review/r1.tree"))


class EveryConditionCheckedTest(C2):
    """M-03. 「완료 조건」의 모든 항목은 '- [x]'여야 머지된다 — 체크박스 없는 항목도 미체크다."""

    def test_bullet_without_checkbox_blocks_merge(self):
        self.write("app.py", "def search(q):\n    return q\n")
        import vf_git
        qa = f"- 대상 tree: {vf_git.snapshot()}\n- 코드: 통과\n- 브라우저: 해당 없음 — 서버 함수만, 화면 없음"
        rv = "- 라운드 1: x\n- 판정: 확정"
        self.mr(review=rv, qa=qa, conds="- [x] 부분 일치 검색\n- 0건이면 안내 문구")
        r = self.stage("merge")
        self.assertEqual(r.returncode, 1)
        self.assertIn("완료 조건 미체크 1개", r.stdout)
        self.mr(review=rv, qa=qa, conds="- [x] 부분 일치 검색\n- [X] 0건이면 안내 문구")
        r = self.stage("merge")
        self.assertEqual(r.returncode, 0, r.stdout)


class StaleGoalStateTest(C2):
    """M-04. 이전 골의 .vibe/review 기록(d<N>.meta, r<N>.tree)이 다음 골을 막거나 통과시키지 않는다."""

    def next_goal(self):
        self.write("docs/goals/G-002-n.md", "# G-002\n<!--\nid: G-002\nstatus: active\n-->\n")
        sh("git", "branch", "-m", "G-002/next", cwd=self.d)
        with open("mr.md", encoding="utf-8") as f:
            self.write("mr.md", f.read().replace("G-001 시험 골", "G-002 다음 골"))

    def test_old_goal_design_meta_is_ignored(self):
        self.mr(confirm="(진행 전)")
        self.write("app.py", "def search(q):\n    return q\n")              # 구현 선행
        r = self.codex("review.py", "--design", "1", "--mr", "mr.md")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(".vibe/review/d1.meta", encoding="utf-8") as f:
            meta = f.read()
        self.assertIn("goal: G-001", meta)
        self.assertIn("diverged: yes", meta)
        self.mr()
        self.assertEqual(self.stage("review").returncode, 1)                  # 같은 골 — 순서 줄 필요
        self.next_goal()
        r = self.stage("review")
        self.assertEqual(r.returncode, 0, r.stdout)                           # 다른 골의 meta는 무시

    def test_old_goal_round_does_not_unlock_next_round(self):
        self.write("app.py", "def search(q):\n    return q\n")
        self.mr()
        r = self.codex("review.py", "--round", "1", "--mr", "mr.md",
                       reply="ROUND: 1\nRESOLVED: 없음\nCHECKED: 1 — app.py:2\nVERDICT: CHANGES\n")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.run_script("review.py", "--round", "2", "--mr", "mr.md", "--dry").returncode, 0)
        self.next_goal()
        r = self.run_script("review.py", "--round", "2", "--mr", "mr.md", "--dry")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("G-001", r.stderr)
        self.write(".vibe/review/d1.txt", "VERDICT: CONFIRM\n")                # 이전 골의 설계 1회차도 같다
        self.write(".vibe/review/d1.meta", "goal: G-001\ndiverged: no\n")
        r = self.run_script("review.py", "--design", "2", "--mr", "mr.md", "--dry")
        self.assertNotEqual(r.returncode, 0)


class SkipEstimateLimitTest(C2):
    """M-05. 생략의 예상 규모도 design_skip 기준 안이어야 한다."""

    def test_estimate_over_limit_blocks(self):
        for est in ("예상 100000줄·999파일", "예상 60줄·1파일", "예상 5줄·4파일"):
            self.mr(confirm=f"- 생략: 작은 변경 ({est})")
            r = self.stage("build")
            self.assertEqual(r.returncode, 1, est)
            self.assertIn("예상 규모가 생략 기준을 넘음", r.stdout)
            self.assertIn("review.py --design", r.stdout)
        self.mr(confirm="- 생략: 작은 변경 (예상 5줄)")                      # 파일 수 없음
        r = self.stage("build")
        self.assertEqual(r.returncode, 1)
        self.assertIn("예상 규모 없음", r.stdout)
        self.mr(confirm="- 생략: 작은 변경 (예상 50줄·3파일)")
        self.assertEqual(self.stage("build").returncode, 0, self.stage("build").stdout)


class RecordFileOnlyTest(C2):
    """M-06. 개인 모드(핸드오프=docs/)에서 docs/ 아래 코드는 기록이 아니다 — 핸드오프 기록 파일만 뺀다."""

    def test_code_under_docs_counts(self):
        self.write("docs/tool.py", lines(60, "t"))
        self.mr(confirm=SKIP)
        r = self.stage("build")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("코드 변경이", r.stdout)

    def test_handoff_records_do_not_count(self):
        import mr_check
        import vf_git
        cfg = vf_git.config()
        for f in ("docs/goals/G-002-x.md", "docs/mr/G-001.md", "docs/WORKLOG/search.md", "docs/WORKLOG.md",
                  "docs/PLAN-body.md", "docs/DECISIONS-2026-10.md", "docs/LESSONS.md", "docs/INDEX.md",
                  "docs/NORTHSTAR-body.md", "docs/REMAINING-done-2026-10.md"):
            self.assertTrue(mr_check.is_record(f, cfg), f)
        for f in ("docs/tool.py", "docs/WORKLOG/run.py", "docs/architecture.md", "docs/PLAN.py", "app.py"):
            self.assertFalse(mr_check.is_record(f, cfg), f)

    def test_code_under_docs_changed_after_qa_needs_requa(self):
        # QA 대상 비교도 같은 is_record — docs/ 아래 코드는 QA 뒤에 바뀌면 재검증, 기록만 바뀐 건 허용
        import mr_check
        import vf_git
        cfg = vf_git.config()
        qa = f"- 대상 tree: {vf_git.snapshot()}\n- 코드: 통과\n- 브라우저: 해당 없음 — 화면 없음\n"
        self.write("docs/WORKLOG.md", "# 작업 이력\n- 기록\n")
        self.assertFalse([x for x in mr_check.merge_checks(qa, cfg) if "재검증" in x])
        self.write("docs/tool.py", "x = 1\n")
        self.assertTrue([x for x in mr_check.merge_checks(qa, cfg) if "재검증" in x])


if __name__ == "__main__":
    unittest.main()
