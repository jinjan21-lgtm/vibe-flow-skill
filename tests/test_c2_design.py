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
from test_scripts import MR_OK, PY, SCRIPTS, Repo, seed_design, seed_qa_run, seed_review, sh  # noqa: E402

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
        seed_design()   # 「설계 확인」 '판정: 확정'은 d<N> 기록과 대조된다 — 기본은 이 골·브랜치·기준에서 확정된 상태

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
        qa = f"- 대상 tree: {vf_git.snapshot()}\n- 코드: 통과\n- 브라우저: 해당 없음 — 서버 함수만, 화면 없음\n- 미검증·생략 항목과 사유: 없음"
        seed_qa_run(qa)
        self.mr(review="- 라운드 1: x\n- 판정: 확정", qa=qa, conds="- [x] 부분 일치 검색\n- [ ] 0건이면 안내 문구")
        with open("mr.md", encoding="utf-8") as f:
            seed_review(mr=f.read())   # 기록의 conds는 이 MR의 완료 조건(2개) 해시
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
        qa = f"- 대상 tree: {vf_git.snapshot()}\n- 코드: 통과\n- 브라우저: 해당 없음 — 서버 함수만, 화면 없음\n- 미검증·생략 항목과 사유: 없음"
        rv = "- 라운드 1: x\n- 판정: 확정"
        seed_qa_run(qa)
        self.mr(review=rv, qa=qa, conds="- [x] 부분 일치 검색\n- 0건이면 안내 문구")
        with open("mr.md", encoding="utf-8") as f:
            seed_review(mr=f.read())   # 기록의 conds는 이 MR의 완료 조건(2개) 해시
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
        seed_design(goal="G-002", n=2)                                        # G-002 자신의 설계 확인(확정)
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
        qa = f"- 대상 tree: {vf_git.snapshot()}\n- 코드: 통과\n- 브라우저: 해당 없음 — 화면 없음\n- 미검증·생략 항목과 사유: 없음\n"
        self.write("docs/WORKLOG.md", "# 작업 이력\n- 기록\n")
        self.assertFalse([x for x in mr_check.merge_checks(qa, cfg) if "재검증" in x])
        self.write("docs/tool.py", "x = 1\n")
        self.assertTrue([x for x in mr_check.merge_checks(qa, cfg) if "재검증" in x])


IMPL = "def search(q):\n    return [x for x in ['a'] if q in x]\n"
R1_OK = "ROUND: 1\nRESOLVED: 없음\nCHECKED: 1 — app.py:2\nVERDICT: CONFIRM\n"
BLOCKER = "FINDING: F1 | blocker | app.py:2 | 완료 조건 1 위반 | 고친다\n"


class DesignRecordTest(C2):
    """P0-1. 「설계 확인」 '판정: 확정'은 이 골·브랜치·기준의 최근 d<N> 기록이 CONFIRM(blocker 없음)이어야 한다."""

    def setUp(self):
        super().setUp()
        for f in ("d1.txt", "d1.meta"):
            os.remove(os.path.join(".vibe", "review", f))
        self.mr()

    def test_mr_text_alone_is_not_confirmation(self):
        r = self.stage("build")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("설계 확인 기록", r.stdout)
        self.assertIn("review.py --design", r.stdout)

    def test_latest_record_must_confirm_without_blocker(self):
        seed_design(verdict="CHANGES")
        r = self.stage("build")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("CHANGES", r.stdout)
        seed_design(extra=BLOCKER)
        self.assertIn("blocker", self.stage("build").stdout)
        seed_design()
        self.assertEqual(self.stage("build").returncode, 0, self.stage("build").stdout)
        seed_design(n=2, verdict="CHANGES")                          # 최근 회차가 기준
        self.assertEqual(self.stage("build").returncode, 1)

    def test_human_verdict_after_two_checks_and_skip_need_no_confirm(self):
        """사람 판정은 설계 확인 2회(d1·d2 CHANGES) 뒤의 결정 D-nnn으로, 생략은 기록 없이 통과."""
        seed_design(n=1, verdict="CHANGES")
        seed_design(n=2, verdict="CHANGES")
        self.write("docs/DECISIONS.md", "## D-003 캐시 생략\n- 영향: G-001\n")   # 사람 판정은 결정 기록과 대조(J-09)
        self.mr(confirm="- 확인 1: blocker 1\n- 확인 2: blocker 1\n- 사람 결정: D-003 — 캐시 생략\n"
                        "- 판정: 확정 (사람 판정 D-003)")
        self.assertEqual(self.stage("build").returncode, 0, self.stage("build").stdout)
        self.mr(confirm=SKIP)
        self.assertEqual(self.stage("build").returncode, 0, self.stage("build").stdout)

    def test_design_confirm_with_blocker_is_invalid(self):
        self.mr(confirm="(진행 전)")
        r = self.codex("review.py", "--design", "1", "--mr", "mr.md", reply=BLOCKER.replace("F1", "D1") + "VERDICT: CONFIRM\n")
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("blocker", r.stdout + r.stderr)
        self.assertTrue(os.path.exists(".vibe/review/d1.txt.failed"))
        self.assertFalse(os.path.exists(".vibe/review/d1.meta"))


class ReviewRecordTest(C2):
    """P0-1. 「리뷰 기록」 '판정: 확정'은 이 골·브랜치·기준의 최근 r<N> 기록이 CONFIRM(blocker 없음)이어야 한다."""

    def setUp(self):
        super().setUp()
        self.write("app.py", IMPL)
        self.mr(review="- 라운드 1 (전체): blocker 0\n- 판정: 확정")

    def test_mr_text_alone_is_not_confirmation(self):
        r = self.stage("qa")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("리뷰 기록", r.stdout)
        self.assertIn("review.py --round", r.stdout)

    def test_latest_round_must_confirm_without_blocker(self):
        seed_review(verdict="CHANGES")
        r = self.stage("qa")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("CHANGES", r.stdout)
        seed_review(extra=BLOCKER)
        self.assertIn("blocker", self.stage("qa").stdout)
        seed_review()
        self.assertEqual(self.stage("qa").returncode, 0, self.stage("qa").stdout)
        seed_review(n=2, verdict="CHANGES")
        self.assertEqual(self.stage("qa").returncode, 1)

    def test_review_confirm_with_blocker_is_invalid(self):
        r = self.codex("review.py", "--round", "1", "--mr", "mr.md", reply=R1_OK.replace("VERDICT", BLOCKER + "VERDICT"))
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("blocker", r.stdout + r.stderr)
        self.assertTrue(os.path.exists(".vibe/review/r1.txt.failed"))
        self.assertFalse(os.path.exists(".vibe/review/r1.tree"))
        self.assertFalse(os.path.exists(".vibe/review/r1.txt"))


class ChangeAfterReviewTest(C2):
    """P0-2. 리뷰 확정 뒤 코드가 바뀌면 다시 리뷰(N+1 라운드, 3이면 사람). 기록 파일만 바뀐 것은 괜찮다."""

    def test_normal_flow_design_review_qa_record_merge(self):
        import json
        for f in ("d1.txt", "d1.meta"):
            os.remove(os.path.join(".vibe", "review", f))
        sh("git", "checkout", "-q", "main", cwd=self.d)                      # 레포 설정(test_cmd)은 기준에 있다
        self.write(".vibe-flow.json", json.dumps({"base": "main", "test_cmd": f'"{PY}" -c "print(1)"'}))
        sh("git", "commit", "-qam", "G-000 test_cmd", cwd=self.d)
        sh("git", "checkout", "-q", "G-001/test", cwd=self.d)
        sh("git", "merge", "-q", "--ff-only", "main", cwd=self.d)
        self.mr(confirm="(진행 전)")
        r = self.codex("review.py", "--design", "1", "--mr", "mr.md")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        conf = "- 확인 1: blocker 0\n- 판정: 확정"
        self.mr(confirm=conf)
        self.assertEqual(self.stage("build").returncode, 0, self.stage("build").stdout)
        self.write("app.py", IMPL)
        r = self.codex("review.py", "--round", "1", "--mr", "mr.md", reply=R1_OK)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rv = "- 라운드 1 (전체): blocker 0 · 검토 근거 1/1\n- 판정: 확정"
        self.mr(confirm=conf, review=rv)
        self.assertEqual(self.stage("qa").returncode, 0, self.stage("qa").stdout)
        self.mr(confirm=conf, review=rv, qa="- 브라우저: 해당 없음 — 서버 함수만, 화면 없음\n- 미검증·생략 항목과 사유: 없음\n")
        r = self.run_script("qa_run.py", "--mr", "mr.md")                     # QA는 리뷰 뒤, 실제 실행 기록
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.write("docs/WORKLOG.md", "# 작업 이력\n- G-001 검색\n")          # QA 뒤 기록만
        self.write("docs/REMAINING-done-2026-10.md", "# 완료\n- [x] G-001\n")
        r = self.stage("merge")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_code_change_after_confirm_needs_next_round(self):
        self.write("app.py", IMPL)
        seed_review()
        self.mr(review="- 라운드 1: x\n- 판정: 확정")
        self.assertEqual(self.stage("qa").returncode, 0, self.stage("qa").stdout)
        self.write("app.py", IMPL + "# 확정 뒤 수정\n")
        for st in ("qa", "merge"):
            r = self.stage(st)
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn("리뷰 확정 뒤 코드 변경(app.py)", r.stdout)
            self.assertIn("review.py --round 2", r.stdout)
        seed_review(n=3)
        self.write("app.py", IMPL + "# 3라운드 뒤 수정\n")
        r = self.stage("qa")
        self.assertIn("사람 판정 필요", r.stdout)


class CompletionItemsTest(C2):
    """K-01·K-02. 완료 조건 파서는 하나(mr_check.completion_items) — 번호 목록도 같고, 목록 없는 문장은 막는다."""

    def test_numbered_items_are_numbered_in_review_payload(self):
        self.write("app.py", IMPL)
        self.mr(conds="1. [ ] 부분 일치 검색\n2. [x] 0건이면 안내 문구")
        import mr_check
        with open("mr.md", encoding="utf-8") as f:
            items = mr_check.completion_items(f.read())
        self.assertEqual(items, [(False, "부분 일치 검색"), (True, "0건이면 안내 문구")])
        r = self.run_script("review.py", "--round", "1", "--mr", "mr.md", "--dry")
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(r.stdout.strip(), encoding="utf-8") as f:
            payload = f.read()
        self.assertIn("1. 부분 일치 검색", payload)
        self.assertIn("2. 0건이면 안내 문구", payload)

    def test_prose_conditions_are_blocked(self):
        self.mr(conds="검색이 잘 되면 된다")                                    # 목록 항목 0개
        r = self.stage("draft")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("완료 조건은 체크리스트 항목으로", r.stdout)
        self.mr(conds="- [x] 부분 일치 검색\n그리고 빠르면 좋다")
        self.assertIn("완료 조건은 체크리스트 항목으로", self.stage("draft").stdout)
        self.mr(conds="- [x] 부분 일치 검색\n  (대소문자 무시)")                   # 들여쓴 이어지는 줄은 항목의 일부
        self.assertEqual(self.stage("draft").returncode, 0, self.stage("draft").stdout)


class RecordNameTest(C2):
    """K-03. 기록 파일은 정확한 이름·보관 규칙(hindex)만 — PLANET.md·INDEXER.md는 코드 문서다."""

    def test_exact_record_names(self):
        import mr_check
        import vf_git
        cfg = vf_git.config()
        self.write("docs/PLAN.md", "# PLAN INDEX\n- [검색 흐름](PLAN-검색-흐름.md#검색-흐름)\n")   # 분할 파일은 PLAN.md 링크로만(J-02)
        for f in ("PLAN.md", "PLAN-body.md", "PLAN-검색-흐름.md", "WORKLOG.md", "REMAINING.md",
                  "REMAINING-done-2026-10.md", "LESSONS.md", "LESSONS-body.md", "LESSONS-body-2.md", "DECISIONS.md",
                  "DECISIONS-2026-10.md", "DECISIONS-2026-10-2.md", "DECISIONS-INDEX-replaced.md", "NORTHSTAR.md",
                  "NORTHSTAR-body.md", "INDEX.md", "WORKLOG/INDEX-2026-09.md", "goals/INDEX-done.md", "mr/G-001.md"):
            self.assertTrue(mr_check.is_record("docs/" + f, cfg), f)
        for f in ("PLANET.md", "INDEXER.md", "PLANNING.md", "WORKLOGS.md", "REMAINING-x.md", "LESSONSLEARNED.md",
                  "DECISIONS-old.md", "NORTHSTARS.md", "decisions.md", "INDEX-api.md"):
            self.assertFalse(mr_check.is_record("docs/" + f, cfg), f)


class EstimateFormatTest(C2):
    """K-04. 이상한 예상치는 예외가 아니라 빠진 항목이다."""

    def test_malformed_estimate_is_a_miss(self):
        for est in ("예상 ,줄·1파일", "예상 1,2줄·1파일", "예상 5줄·,파일"):
            self.mr(confirm=f"- 생략: 작은 변경 ({est})")
            r = self.stage("build")
            self.assertEqual(r.returncode, 1, est)
            self.assertNotIn("Traceback", r.stderr, est)
            self.assertIn("예상 규모", r.stdout, est)
        self.mr(confirm="- 생략: 작은 변경 (예상 1,200줄·1파일)")
        self.assertIn("예상 규모가 생략 기준을 넘음", self.stage("build").stdout)


class StaleContextTest(C2):
    """K-05. 같은 골이라도 다른 브랜치·다른 기준(리베이스 등)에서 만든 기록은 묵은 것이다."""

    def setUp(self):
        super().setUp()
        self.write("app.py", IMPL)
        seed_review()
        self.mr(review="- 라운드 1: x\n- 판정: 확정")

    def test_other_branch_records_are_stale(self):
        self.assertEqual(self.stage("qa").returncode, 0, self.stage("qa").stdout)
        sh("git", "branch", "-m", "G-001/other", cwd=self.d)
        r = self.stage("qa")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("브랜치", r.stdout)
        self.assertIn("설계 확인 기록", r.stdout)
        r = self.run_script("review.py", "--round", "2", "--mr", "mr.md", "--dry")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("G-001/test", r.stderr)
        r = self.run_script("review.py", "--design", "2", "--mr", "mr.md", "--dry")
        self.assertNotEqual(r.returncode, 0)

    def test_moved_base_makes_records_stale(self):
        sh("git", "checkout", "-q", "main", cwd=self.d)
        self.write("other.py", "y = 1\n")
        sh("git", "add", "other.py", cwd=self.d)
        sh("git", "commit", "-qm", "G-000 main 진행", cwd=self.d)
        sh("git", "checkout", "-q", "G-001/test", cwd=self.d)
        self.assertEqual(self.stage("qa").returncode, 0, self.stage("qa").stdout)   # 갈라진 지점은 그대로
        sh("git", "merge", "-q", "--ff-only", "main", cwd=self.d)                    # 기준 위로 올림
        r = self.stage("qa")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("기준", r.stdout)



class AuditJTest(C2):
    """외부 감사 J-01·02·06·07·08·09 + 평가자(--next DONE, 위험 표식 생략 금지)."""

    def setUp(self):
        super().setUp()
        sys.path.insert(0, SCRIPTS)
        import mr_check
        import vf_git
        self.mc, self.vf = mr_check, vf_git

    def test_j08_missing_qa_run_fails_closed(self):
        saved = sys.modules.get("qa_run")
        sys.modules["qa_run"] = None    # import qa_run → ImportError
        try:
            miss = self.mc.merge_checks("- 코드: 통과\n", self.vf.config())
        finally:
            if saved is None:
                sys.modules.pop("qa_run", None)
            else:
                sys.modules["qa_run"] = saved
        self.assertTrue(any("QA 검증기(qa_run) 없음" in x for x in miss), miss)

    def test_j09_human_verdict_needs_decision_for_goal(self):
        seed_design(n=2, verdict="CHANGES")   # R5: Codex 설계 확인을 돌렸으면 사람 판정은 2회차 뒤에만
        self.mr(confirm="- 확인 2: blocker 1\n- 사람 결정: D-009 — 없음\n- 판정: 확정 (사람 판정 D-009)")
        r = self.stage("build")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("D-009", r.stdout)
        self.write("docs/DECISIONS-2026-10.md", "# 결정\n\n## D-009 캐시 생략\n- 영향: G-002\n\n## D-010 x\n- G-001\n")
        r = self.stage("build")
        self.assertEqual(r.returncode, 1, r.stdout)                 # 다른 골의 결정
        self.write("docs/DECISIONS-2026-10.md", "# 결정\n\n## D-009 캐시 생략\n- 영향: G-001 검색\n")
        self.assertEqual(self.stage("build").returncode, 0, self.stage("build").stdout)

    def test_j07_unreadable_review_tree_is_a_miss(self):
        self.write("app.py", IMPL)
        seed_review()
        self.mr(review="- 라운드 1: x\n- 판정: 확정")
        self.assertEqual(self.stage("qa").returncode, 0, self.stage("qa").stdout)
        p = os.path.join(".vibe", "review", "r1.tree")
        with open(p, encoding="utf-8") as f:
            rest = f.read().split("\n", 1)[1]
        for bad in ("deadbeef" * 5, "not-a-sha"):
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(bad + "\n" + rest)
            r = self.stage("qa")
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn("리뷰 기록 tree를 읽을 수 없음", r.stdout)

    def test_j06_conditions_changed_after_review(self):
        self.write("app.py", IMPL)
        self.mr(conds="- [ ] 부분 일치 검색")
        r = self.codex("review.py", "--round", "1", "--mr", "mr.md", reply=R1_OK)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(".vibe/review/r1.tree", encoding="utf-8") as f:
            self.assertIn("conds:", f.read())
        self.mr(conds="- [x] 부분 일치 검색", review="- 라운드 1: x\n- 판정: 확정")   # 체크만 바뀜 — 같은 조건
        self.assertEqual(self.stage("qa").returncode, 0, self.stage("qa").stdout)
        self.mr(conds="- [x] 아무 결과나 돌려줌", review="- 라운드 1: x\n- 판정: 확정")
        r = self.stage("qa")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("리뷰 뒤 완료 조건이 바뀜", r.stdout)

    def test_j01_empty_checked_item_is_a_miss(self):
        self.mr(conds="- [x] 부분 일치 검색\n- [x]   ")
        r = self.stage("draft")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("빈 항목", r.stdout)

    def test_j02_plan_split_only_if_hindex_name_or_linked(self):
        cfg = self.vf.config()
        self.assertTrue(self.mc.is_record("docs/PLAN.md", cfg))
        self.assertTrue(self.mc.is_record("docs/PLAN-body.md", cfg))
        self.assertFalse(self.mc.is_record("docs/PLAN-evil.md", cfg))
        self.write("docs/PLAN.md", "# PLAN INDEX\n- [범위](PLAN-scope.md#범위)\n")
        self.assertTrue(self.mc.is_record("docs/PLAN-scope.md", cfg))
        self.assertFalse(self.mc.is_record("docs/PLAN-evil.md", cfg))

    def test_next_reports_done_only_when_record_passes(self):
        import contextlib
        import io
        self.mr()
        os.makedirs("docs/mr", exist_ok=True)
        shutil.copy("mr.md", "docs/mr/G-001.md")
        sh("git", "add", "docs/mr/G-001.md", cwd=self.d)   # R5(H-04): DONE은 커밋된 MR 사본과 계약이 같을 때만
        sh("git", "commit", "-qm", "G-001 기록", cwd=self.d)
        old = (self.mc.next_stage, self.mc.record_check, sys.argv)
        self.mc.next_stage = lambda text, cfg: ("record", "vibe-record", [])
        try:
            for ok, want in ((True, "DONE — 머지 준비 완료(머지는 사용자)"), (False, "record → 세부 스킬 vibe-record")):
                self.mc.record_check = lambda ok=ok: (ok, [] if ok else ["WORKLOG 기록 없음"])
                sys.argv = ["mr_check.py", "mr.md", "--next"]
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    self.mc.main()
                self.assertIn(want, buf.getvalue())
                if not ok:
                    self.assertIn("WORKLOG 기록 없음", buf.getvalue())
                    self.assertNotIn("DONE", buf.getvalue())
        finally:
            self.mc.next_stage, self.mc.record_check, sys.argv = old

    def test_risky_change_cannot_skip_design(self):
        self.mr(confirm=SKIP)
        self.assertEqual(self.stage("build").returncode, 0, self.stage("build").stdout)
        with open("mr.md", encoding="utf-8") as f:
            body = f.read()
        self.write("mr.md", body.replace("- 위험: 없음", "- 위험: 권한 검사 변경"))
        r = self.stage("build")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("위험 표식이 있으면 설계 확인 생략 불가", r.stdout)
        self.write("mr.md", body.replace("- 데이터·API 변경: 없음", "- 데이터·API 변경: 응답에 필드 추가"))
        self.assertIn("위험 표식이 있으면 설계 확인 생략 불가", self.stage("build").stdout)


if __name__ == "__main__":
    unittest.main()
