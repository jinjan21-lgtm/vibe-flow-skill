"""vibe-flow 스크립트 회귀 테스트. 실행: python -m unittest tests/test_scripts.py -v (레포 루트)

임시 git 레포를 만들어 시험한다. Codex는 부르지 않는다(judge는 가짜 응답으로 대체).
"""
import datetime
import importlib
import re
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
sys.path.insert(0, SCRIPTS)
PY = sys.executable

# review.py --design이 받는 유효한 설계 확인 응답: 설계 다섯 칸마다 CHECKED 한 줄 + POLICY 줄 + VERDICT
DESIGN_CHECKED = ("CHECKED: 접근 방식 — search에 메모리 필터를 넣는 방식, 호출부는 그대로 둔다\n"
                  "CHECKED: 바꿀 모듈·파일 — app.py의 search 함수와 테스트 파일만 바뀐다\n"
                  "CHECKED: 데이터·API 변경 — search(q) 시그니처와 반환 형태가 그대로다\n"
                  "CHECKED: 대안과 선택 이유 — DB LIKE 대안을 봤고 데이터가 작아 메모리 필터가 단순하다\n"
                  "CHECKED: 테스트 계획 — 부분 일치 테스트를 먼저 RED로 확인하는 계획이 있다\n")
DESIGN_OK = "DESIGN: 1\n" + DESIGN_CHECKED + "POLICY: 없음\nVERDICT: CONFIRM\n"

GOAL ="# {gid} 시험\n<!--\nid: {gid}\nstatus: {st}\n-->\n"
MR_OK = """## 골
G-001 시험 골
## 사용자 가치
영업팀이 검색한다
## 완료 조건
- [x] 부분 일치 검색
## 제외 범위
- 엑셀
## 영향·위험
- 위험: 없음
## 검증 계획
- 코드: unittest
## 설계
- 접근 방식: 검색 함수 추가
- 바꿀 모듈·파일: app.py
- 데이터·API 변경: 없음
- 대안과 선택 이유: DB 검색 대신 메모리 필터 — 데이터가 작음
- 테스트 계획: 부분 일치 테스트 먼저
## 설계 확인
- 확인 1: blocker 0
- 사람 결정: D-001 — 없음
- 판정: 확정 (사람 판정 D-001)
## 계획 vs 실제
{plan}
## 리뷰 기록
{review}
## QA 결과
{qa}
"""


def _vibe_record(name, text):
    """.vibe/review 기록을 쓴다. .vibe/는 스냅숏에서 뺀다(.git/info/exclude) — 기록이 작업물 비교에 끼지 않게."""
    with open(os.path.join(".git", "info", "exclude"), "a", encoding="utf-8") as f:
        f.write("\n.vibe/\n")
    os.makedirs(os.path.join(".vibe", "review"), exist_ok=True)
    with open(os.path.join(".vibe", "review", name), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def seed_review(goal="G-001", n=1, verdict="CONFIRM", extra="", mr=None, evidence="docs/NORTHSTAR.md:1"):
    """지금 작업물·브랜치·기준의 리뷰 라운드 기록(r<N>.txt·r<N>.tree). mr_check는 「리뷰 기록」의 '판정: 확정'을
    이 기록과 대조한다 — MR 문구만으로는 확정이 아니다. conds는 mr(기본 MR_OK)의 완료 조건 해시(review.py와 같이)."""
    import mr_check
    import vf_git
    m = MR_OK if mr is None else mr   # 라운드 1은 완료 조건마다 근거 한 줄(qa·merge가 r1 CHECKED를 다시 본다 — A9-03)
    # evidence: 기본 '파일:줄'은 경량 MR만 통과 — 표준·강화(위험 ≠ 없음)는 레포 테스트 파일의 테스트 이름이어야 한다(A10)
    chk = "".join(f"CHECKED: {i} — {evidence}\n" for i in range(1, len(mr_check.completion_items(m)) + 1)) if n == 1 else ""
    _vibe_record(f"r{n}.txt", f"ROUND: {n}\n{chk}{extra}VERDICT: {verdict}\n")
    _vibe_record(f"r{n}.tree", vf_git.snapshot() + "\n" + mr_check.record_stamp(goal, vf_git.config())
                 + f"conds: {mr_check.completion_hash(MR_OK if mr is None else mr)}\n"
                 + f"contract: {mr_check.contract_hash(MR_OK if mr is None else mr)}\n")


def seed_design(goal="G-001", n=1, verdict="CONFIRM", extra="", mr=None):
    """지금 브랜치·기준의 설계 확인 기록(d<N>.txt·d<N>.meta). 「설계 확인」 '판정: 확정'은 이 기록과 대조된다."""
    import mr_check
    import vf_git
    # 설계 확인 원문은 요소별 CHECKED + POLICY 형식이어야 게이트가 받는다(A19-01) — extra에 POLICY가 있으면 그것을 쓴다
    policy = "" if re.search(r"^POLICY:", extra, re.M) else "POLICY: 없음\n"
    _vibe_record(f"d{n}.txt", f"DESIGN: {n}\n{DESIGN_CHECKED}{policy}{extra}VERDICT: {verdict}\n")
    _vibe_record(f"d{n}.meta", mr_check.record_stamp(goal, vf_git.config()) + "diverged: no\n"
                 + f"design: {mr_check.design_hash(MR_OK if mr is None else mr)}\n")


def seed_qa_run(body):
    """「QA 결과」가 주장하는 실행 증거를 만든다 — merge 검사(qa_run.verify)는 손으로 쓴 '통과'를 증거와 대조한다.
    '코드: 통과'면 .vibe/qa/<tree>.json(exit 0), '브라우저'의 캡처 링크면 그 파일. 캡처 파일은 스냅숏에서 뺀다."""
    import json
    import vf_git
    import qa_run
    sha = qa_run.target(body)   # 주석 안 예시 sha는 대상이 아니다(mr_check·qa_run과 같은 파서)
    tree = vf_git.tree_of(sha) if sha else ""
    if tree and re.search(r"^-\s*코드:\s*통과(?=$|[\s(（—–])", body, re.M):
        with open(os.path.join(".git", "info", "exclude"), "a", encoding="utf-8") as f:
            f.write("\n.vibe/\n")
        os.makedirs(os.path.join(".vibe", "qa"), exist_ok=True)
        # 수는 「QA 결과」 코드 줄의 'N/M'과 같게(verify가 대조한다). 줄에 수가 없으면 1/1
        said = re.search(r"^\s*-\s*코드:.*?(\d+)\s*/\s*(\d+)", body, re.M)
        passed, total = (int(said.group(1)), int(said.group(2))) if said else (1, 1)
        with open(os.path.join(".vibe", "qa", tree + ".json"), "w", encoding="utf-8") as f:
            json.dump({"schema": vf_git.EVIDENCE_SCHEMA, "tree": tree, "cmd": (vf_git.config().get("test_cmd") or "").strip(),
                       "exit": 0, "passed": passed, "total": total}, f)
    for p in re.findall(r"!\[[^\]]*\]\(([^)\s]+)\)", body):
        if not re.match(r"(?i)https?://", p) and not os.path.exists(p):
            with open(os.path.join(".git", "info", "exclude"), "a", encoding="utf-8") as f:
                f.write(f"\n/{p}\n")
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            with open(p, "wb") as f:
                f.write(b"\x89PNG")


def sh(*args, cwd, ok=True):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    if ok and r.returncode:
        raise AssertionError(f"{args}: {r.stdout}{r.stderr}")
    return r


class Repo(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="vf-test-")
        self.old = os.getcwd()
        os.chdir(self.d)
        sh("git", "init", "-q", "-b", "main", cwd=self.d)
        sh("git", "config", "user.email", "t@t", cwd=self.d)
        sh("git", "config", "user.name", "t", cwd=self.d)
        sh("git", "config", "core.autocrlf", "false", cwd=self.d)
        os.makedirs("docs/goals")
        self.write("docs/goals/G-000-m.md", GOAL.format(gid="G-000", st="active"))
        self.write("docs/goals/G-001-s.md", GOAL.format(gid="G-001", st="active"))
        self.write("docs/NORTHSTAR.md", "# 노스스타\n## 목적\n검색\n")

    def tearDown(self):
        os.chdir(self.old)
        shutil.rmtree(self.d, ignore_errors=True)

    def write(self, p, text):
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    def run_script(self, name, *args):
        return subprocess.run([PY, os.path.join(SCRIPTS, name), *args], cwd=self.d,
                              capture_output=True, text=True, encoding="utf-8")


class GoalGateTest(Repo):
    def commit_msg(self, msg):
        self.write(".msg", msg)
        return self.run_script("goal_gate.py", "check-commit", ".msg")

    def test_no_id_rejected(self):
        r = self.commit_msg("fix typo")
        self.assertEqual(r.returncode, 1)
        self.assertIn("골 ID", r.stderr)

    def test_unknown_goal_rejected(self):
        self.assertEqual(self.commit_msg("G-999 x").returncode, 1)

    def test_inactive_goal_rejected(self):
        self.write("docs/goals/G-002-r.md", GOAL.format(gid="G-002", st="done"))
        self.assertEqual(self.commit_msg("G-002 x").returncode, 1)

    def test_goal_id_in_unborn_branch_name_counts(self):
        sh("git", "checkout", "-q", "-b", "G-001/search", cwd=self.d)  # 커밋 없는 브랜치
        self.assertEqual(self.commit_msg("검색 추가").returncode, 0)

    def test_goal_status_only_commit_allowed_for_done_goal(self):
        self.write("docs/goals/G-002-r.md", GOAL.format(gid="G-002", st="done"))
        sh("git", "add", "docs/goals/G-002-r.md", cwd=self.d)
        self.assertEqual(self.commit_msg("G-002 완료 처리").returncode, 0)   # 골 파일만 → 허용
        self.write("app.py", "x = 1\n")
        sh("git", "add", "app.py", cwd=self.d)
        self.assertEqual(self.commit_msg("G-002 완료 처리").returncode, 1)   # 코드가 섞이면 → 거부

    def test_active_goal_passes(self):
        self.assertEqual(self.commit_msg("G-000 typo").returncode, 0)

    def test_hook_blocks_real_commit(self):
        self.assertEqual(self.run_script("goal_gate.py", "install-hook").returncode, 0)
        sh("git", "add", "-A", cwd=self.d)
        self.assertNotEqual(sh("git", "commit", "-qm", "no id", cwd=self.d, ok=False).returncode, 0)
        self.assertEqual(sh("git", "commit", "-qm", "G-000 init", cwd=self.d, ok=False).returncode, 0)

    def test_reserve_ids_are_unique_and_skip_existing(self):
        a = self.run_script("goal_gate.py", "reserve-id").stdout.strip()
        b = self.run_script("goal_gate.py", "reserve-id").stdout.strip()
        self.assertEqual((a, b), ("G-002", "G-003"))

    def test_reserve_sees_goals_on_other_branches(self):
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-qm", "base", cwd=self.d)
        sh("git", "checkout", "-qb", "other", cwd=self.d)
        self.write("docs/goals/G-007-x.md", GOAL.format(gid="G-007", st="active"))
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-qm", "g7", cwd=self.d)
        sh("git", "checkout", "-q", "main", cwd=self.d)
        self.assertEqual(self.run_script("goal_gate.py", "reserve-id").stdout.strip(), "G-008")

    def test_concurrent_reservations_do_not_collide(self):
        procs = [subprocess.Popen([PY, os.path.join(SCRIPTS, "goal_gate.py"), "reserve-id"], cwd=self.d,
                                  stdout=subprocess.PIPE, text=True) for _ in range(6)]
        ids = [p.communicate()[0].strip() for p in procs]
        self.assertEqual(len(set(ids)), 6, ids)

    def test_judge_create_with_fake_codex(self):
        import goal_gate
        importlib.reload(goal_gate)
        goal_gate.run_codex = lambda prompt: "VERDICT: CREATE\nREASON: 목적과 연결"
        os.makedirs("docs/goals/candidates")
        self.write("docs/goals/candidates/C-1.md", "# CSV 내보내기\n<!--\nstatus: candidate\n-->\n## 왜\nx\n")
        goal_gate.judge("docs/goals/candidates/C-1.md", apply=True)
        self.assertTrue(any(f.startswith("G-002") for f in os.listdir("docs/goals")))
        self.assertFalse(os.path.exists("docs/goals/candidates/C-1.md"))

    def test_judge_unparseable_keeps_candidate(self):
        import goal_gate
        importlib.reload(goal_gate)
        goal_gate.run_codex = lambda prompt: "error page"
        os.makedirs("docs/goals/candidates")
        self.write("docs/goals/candidates/C-2.md", "# x\n<!--\nstatus: candidate\n-->\n")
        with self.assertRaises(SystemExit) as e:
            goal_gate.judge("docs/goals/candidates/C-2.md", apply=True)
        self.assertEqual(e.exception.code, 2)
        self.assertTrue(os.path.exists("docs/goals/candidates/C-2.md"))


class MrCheckTest(Repo):
    def setUp(self):
        super().setUp()
        sh("git", "checkout", "-q", "-b", "G-001/test", cwd=self.d)  # 골 브랜치에서 작업
        import vf_git
        self.vf = vf_git
        # MR_OK의 「확정 (사람 판정 D-001)」은 실재하는 결정이어야 한다
        self.write("docs/DECISIONS.md", "# 결정\n\n## D-001 설계 판정\n- G-001 설계는 사람이 확정\n")
        self.base = vf_git.snapshot()  # 스냅샷 모드 기준
        self.write(".vibe-flow.json", '{"base": "%s"}' % self.base)

    def check(self, body, stage):
        self.write("mr.md", body)
        seed_review()   # 리뷰 확정은 .vibe/review 기록과 대조된다 — 지금 작업물을 리뷰가 확정한 것으로 둔다
        seed_design(n=1, verdict="CHANGES"); seed_design(n=2, verdict="CHANGES")   # MR_OK의 사람 판정은 설계 확인 2회 뒤에만
        seed_qa_run(body)   # QA 통과 주장은 실행 기록(qa_run)과 대조된다
        return self.run_script("mr_check.py", "mr.md", "--stage", stage)

    def body(self, plan="(진행 전)", review="(진행 전)", qa="(진행 전)"):
        return MR_OK.format(plan=plan, review=review, qa=qa)

    def test_template_placeholders_are_empty(self):
        import mr_check
        with open(os.path.join(SCRIPTS, "..", "templates", "mr-body.md"), encoding="utf-8") as f:
            tpl = f.read()
        miss = mr_check.check(tpl, "draft", self.vf.config())
        for name in ["사용자 가치", "완료 조건", "제외 범위", "영향·위험", "검증 계획"]:
            self.assertIn(f"「{name}」 비어 있음", miss)

    def test_draft_passes_when_filled(self):
        self.assertEqual(self.check(self.body(), "draft").returncode, 0)

    def test_review_needs_plan_vs_actual(self):
        self.assertEqual(self.check(self.body(), "review").returncode, 1)
        self.assertEqual(self.check(self.body(plan="계획과 같음"), "review").returncode, 0)

    def test_qa_needs_confirmed_review_and_max_three_rounds(self):
        self.assertEqual(self.check(self.body(plan="같음", review="- 라운드 1: x"), "qa").returncode, 1)
        ok = "- 라운드 1: x\n- 판정: 확정"
        self.assertEqual(self.check(self.body(plan="같음", review=ok), "qa").returncode, 0)
        four = "\n".join(f"- 라운드 {i}: x" for i in range(1, 5)) + "\n- 판정: 확정"
        self.assertEqual(self.check(self.body(plan="같음", review=four), "qa").returncode, 1)

    def qa_body(self, target, browser="해당 없음(UI 변경 없음)", extra=""):
        qa = f"- 대상 tree: {target}\n- 코드: 통과 — 3/3\n- 브라우저: {browser}\n- 미검증·생략 항목과 사유: 없음\n{extra}"
        return self.body(plan="같음", review="- 라운드 1: x\n- 판정: 확정", qa=qa)

    def test_merge_passes_when_qa_matches_worktree(self):
        self.write("app.py", "x = 1\n")
        self.write("mr.md", self.qa_body("0" * 40))
        target = self.vf.snapshot()  # mr.md까지 포함한 지금 작업물
        r = self.check(self.qa_body(target), "merge")
        # mr.md 내용이 바뀌면 스냅샷도 바뀌므로 mr.md는 .gitignore로 뺀다
        self.write(".gitignore", "mr.md\n")
        target = self.vf.snapshot()
        r = self.check(self.qa_body(target), "merge")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_tracked_but_ignored_artifact_does_not_block_merge(self):
        # .pyc가 실수로 추적되고 있으면 테스트를 돌릴 때마다 바뀐다 — QA 대상 불일치로 막지 않고 경고만
        # 스냅숏(새 인덱스)은 무시 규칙에 걸린 파일을 늘 빼므로, 추적 중인 .pyc가 있으면 커밋 tree와 영원히 안 맞았다
        self.write(".gitignore", "mr.md\n*.pyc\n")
        self.write("cache/app.cpython-312.pyc", "v1")
        self.write("app.py", "x = 1\n")
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "add", "-f", "cache/app.cpython-312.pyc", cwd=self.d)
        sh("git", "commit", "-qm", "G-001 구현", cwd=self.d)
        target = sh("git", "rev-parse", "HEAD", cwd=self.d).stdout.strip()   # QA 대상 = 커밋
        self.write("cache/app.cpython-312.pyc", "v2")                    # 테스트 실행이 다시 만든 캐시
        r = self.check(self.qa_body(target, browser="해당 없음 — 화면 없음").replace("대상 tree", "대상 commit"), "merge")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("무시 대상", r.stdout)
        self.write("app.py", "x = 2\n")                                  # 진짜 코드 변경은 여전히 막는다
        r = self.check(self.qa_body(target, browser="해당 없음 — 화면 없음").replace("대상 tree", "대상 commit"), "merge")
        self.assertIn("재검증", r.stdout)
        self.assertIn("app.py", r.stdout)

    def test_merge_fails_after_uncommitted_change(self):
        self.write(".gitignore", "mr.md\n")
        self.write("app.py", "x = 1\n")
        target = self.vf.snapshot()
        self.write("app.py", "x = 2\n")
        r = self.check(self.qa_body(target), "merge")
        self.assertEqual(r.returncode, 1)
        self.assertIn("재검증", r.stdout)

    def test_merge_requires_browser_for_ui_change(self):
        self.write(".gitignore", "mr.md\n")
        self.write("static/index.html", "<p>x</p>\n")
        target = self.vf.snapshot()
        r = self.check(self.qa_body(target), "merge")
        self.assertEqual(r.returncode, 1)
        self.assertIn("브라우저", r.stdout)
        r = self.check(self.qa_body(target, browser="통과 — 검색 ✅", extra="- 증거: ![A1](A1.png)"), "merge")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_merge_flags_northstar_change_on_base(self):
        self.write(".gitignore", "mr.md\n")
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-qm", "base", cwd=self.d)
        sh("git", "branch", "-m", "main", cwd=self.d)  # setUp의 G-001/test를 main으로
        sh("git", "checkout", "-qb", "G-001/x", cwd=self.d)
        sh("git", "checkout", "-q", "main", cwd=self.d)
        self.write("docs/NORTHSTAR.md", "# 노스스타\n## 목적\n바뀜\n")
        sh("git", "commit", "-qam", "ns", cwd=self.d)
        sh("git", "checkout", "-q", "G-001/x", cwd=self.d)
        self.write(".vibe-flow.json", '{"base": "main"}')
        target = self.vf.snapshot()
        r = self.check(self.qa_body(target), "merge")
        self.assertIn("노스스타", r.stdout)


class ReviewGateTest(Repo):
    def setUp(self):
        super().setUp()
        import vf_git
        self.write(".vibe-flow.json", '{"base": "%s"}' % vf_git.snapshot())
        self.write("mr.md", MR_OK.format(plan="같음", review="", qa=""))

    def review(self, *args):
        return self.run_script("review.py", "--mr", "mr.md", *args)

    def test_round_four_refused(self):
        self.assertNotEqual(self.review("--round", "4").returncode, 0)

    def test_cannot_skip_round(self):
        r = self.review("--round", "2")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("건너뛸 수 없", r.stderr)

    def test_round_three_needs_files(self):
        os.makedirs(".vibe/review")
        self.write(".vibe/review/r2.tree", "x")
        self.assertNotEqual(self.review("--round", "3").returncode, 0)

    def test_round_three_diff_contains_only_given_files(self):
        import vf_git
        self.write("a.py", "a = 1\n")
        self.write("b.py", "b = 1\n")
        os.makedirs(".vibe/review", exist_ok=True)
        self.write(".gitignore", ".vibe/\nmr.md\n")
        import mr_check   # 기록은 골·브랜치·기준까지 맞아야 유효(K-05)
        self.write(".vibe/review/r2.tree", vf_git.snapshot() + "\n" + mr_check.record_stamp("G-001", vf_git.config()))
        self.write(".vibe/review/r2.txt", "VERDICT: CHANGES\n")  # 끝난 라운드 = 판정 출력 + 스냅샷
        self.write("a.py", "a = 2  # 열린 지적 수정\n")
        self.write("b.py", "b = 2  # 다른 변경\n")
        r = self.review("--round", "3", "--files", "a.py", "--dry")
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(r.stdout.strip(), encoding="utf-8") as f:
            payload = f.read()
        self.assertIn("열린 지적 수정", payload)
        self.assertNotIn("다른 변경", payload)
        self.assertIn("라운드 3/3", payload)

    def test_round_two_diff_is_since_round_one(self):
        import vf_git
        self.write(".gitignore", ".vibe/\nmr.md\n")
        self.write("a.py", "a = 1  # 라운드 1 이전\n")
        os.makedirs(".vibe/review", exist_ok=True)
        import mr_check   # 기록은 골·브랜치·기준까지 맞아야 유효(K-05)
        self.write(".vibe/review/r1.tree", vf_git.snapshot() + "\n" + mr_check.record_stamp("G-001", vf_git.config()))
        self.write(".vibe/review/r1.txt", "FINDING: R1 | blocker | a.py:1 | x | y\nVERDICT: CHANGES\n")
        self.write("c.py", "c = 1  # 라운드 1 이후\n")
        r = self.review("--round", "2", "--dry")
        with open(r.stdout.strip(), encoding="utf-8") as f:
            payload = f.read()
        self.assertIn("라운드 1 이후", payload)
        self.assertNotIn("라운드 1 이전", payload)
        self.assertIn("FINDING: R1", payload)  # 직전 지적이 입력에 들어감

    def test_round_one_dry_includes_diff_and_contract(self):
        self.write("app.py", "def search(q):\n    return q\n")
        r = self.review("--round", "1", "--dry")
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(r.stdout.strip(), encoding="utf-8") as f:
            payload = f.read()
        self.assertIn("def search", payload)
        self.assertIn("## 완료 조건", payload)
        self.assertIn("라운드 1/3", payload)


class DupeTest(Repo):
    def setUp(self):
        super().setUp()
        self.write(".gitignore", "mr.md\n")
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-qm", "base", cwd=self.d)
        self.write(".vibe-flow.json", '{"base": "main"}')
        self.body = MR_OK.format(plan="", review="", qa="")

    def test_same_goal_on_other_branch_blocks_draft(self):
        sh("git", "branch", "G-001/someone-else", cwd=self.d)
        sh("git", "checkout", "-qb", "G-001/me", cwd=self.d)
        self.write("mr.md", self.body)
        r = self.run_script("mr_check.py", "mr.md", "--stage", "draft")
        self.assertEqual(r.returncode, 1)
        self.assertIn("같은 골", r.stdout)

    def test_file_overlap_warns_but_passes(self):
        sh("git", "checkout", "-qb", "G-005/other", cwd=self.d)
        self.write("app.py", "a = 1\n")
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-qm", "other", cwd=self.d)
        sh("git", "checkout", "-q", "main", cwd=self.d)
        sh("git", "checkout", "-qb", "G-001/me", cwd=self.d)
        self.write("app.py", "a = 2\n")
        self.write("mr.md", self.body)
        r = self.run_script("mr_check.py", "mr.md", "--stage", "draft")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("겹침", r.stdout)

    def test_remote_same_goal_blocks_and_similar_warns(self):
        import dupe, vf_git
        sh("git", "checkout", "-qb", "G-001/me", cwd=self.d)
        remotes = [{"id": "#7", "title": "G-001 검색 추가", "branch": "x", "body": ""},
                   {"id": "#8", "title": "영업팀이 검색한다 시험 골", "branch": "y", "body": ""}]
        b, w = dupe.find(self.body, vf_git.config(), remotes=remotes)
        self.assertTrue(any("#7" in x for x in b))
        b2, w2 = dupe.find(self.body.replace("G-001", "G-009"), vf_git.config(), remotes=remotes[1:])
        self.assertFalse(b2)
        self.assertTrue(any("#8" in x for x in w2))


class AdoptedChecksTest(Repo):
    """사례 조사에서 채택한 검사: base 최신 여부, MR 크기, 충돌 예측, 디자인시스템 리뷰 입력."""

    def commit_base(self):
        self.write(".gitignore", "mr.md\n.vibe/\n")
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-qm", "base", cwd=self.d)

    def test_merge_blocked_when_base_moved(self):
        self.commit_base()
        sh("git", "checkout", "-qb", "G-001/x", cwd=self.d)
        sh("git", "checkout", "-q", "main", cwd=self.d)
        self.write("other.py", "y = 1\n")
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-qm", "main moved", cwd=self.d)
        sh("git", "checkout", "-q", "G-001/x", cwd=self.d)
        self.write(".vibe-flow.json", '{"base": "main"}')
        import vf_git
        qa = f"- 대상 tree: {vf_git.snapshot()}\n- 코드: 통과\n- 브라우저: 해당 없음"
        self.write("mr.md", MR_OK.format(plan="같음", review="- 판정: 확정", qa=qa))
        r = self.run_script("mr_check.py", "mr.md", "--stage", "merge")
        self.assertIn("리베이스", r.stdout)

    def test_large_diff_warns_at_review(self):
        import vf_git
        self.write(".vibe-flow.json", '{"base": "%s"}' % vf_git.snapshot())
        for i in range(12):
            self.write(f"f{i}.py", "x = 1\n")
        self.write("mr.md", MR_OK.format(plan="같음", review="", qa=""))
        r = self.run_script("mr_check.py", "mr.md", "--stage", "review")
        self.assertIn("[size]", r.stdout)

    def test_conflicting_branch_is_predicted(self):
        self.write("app.py", "a = 0\n")
        self.commit_base()
        sh("git", "checkout", "-qb", "G-005/other", cwd=self.d)
        self.write("app.py", "a = 5\n")
        sh("git", "commit", "-qam", "other", cwd=self.d)
        sh("git", "checkout", "-q", "main", cwd=self.d)
        sh("git", "checkout", "-qb", "G-001/me", cwd=self.d)
        self.write("app.py", "a = 1\n")
        sh("git", "commit", "-qam", "G-001 me", cwd=self.d)
        self.write(".vibe-flow.json", '{"base": "main"}')
        self.write("mr.md", MR_OK.format(plan="", review="", qa=""))
        r = self.run_script("mr_check.py", "mr.md", "--stage", "draft")
        self.assertIn("충돌 예상", r.stdout)

    def test_design_system_goes_into_review_for_ui_change(self):
        import vf_git
        self.write(".vibe-flow.json", '{"base": "%s"}' % vf_git.snapshot())
        self.write("docs/design-system.md", "# 디자인시스템\n- 색은 토큰만: --color-primary\n")
        self.write("static/index.html", "<p style='color:#123456'>x</p>\n")
        self.write("mr.md", MR_OK.format(plan="같음", review="", qa=""))
        r = self.run_script("review.py", "--round", "1", "--mr", "mr.md", "--dry")
        with open(r.stdout.strip(), encoding="utf-8") as f:
            self.assertIn("--color-primary", f.read())


class DesignGateTest(Repo):
    """설계 칸 5요소, 설계 확인(최대 2회), 작은 변경 생략 기준."""

    def setUp(self):
        super().setUp()
        sh("git", "checkout", "-q", "-b", "G-001/test", cwd=self.d)
        import vf_git
        self.write(".gitignore", "mr.md\n.vibe/\n")
        self.write(".vibe-flow.json", '{"base": "%s"}' % vf_git.snapshot())

    def check(self, body, stage):
        self.write("mr.md", body)
        return self.run_script("mr_check.py", "mr.md", "--stage", stage)

    def body(self, design=None, confirm="- 확인 1: blocker 0\n- 판정: 확정", plan="(진행 전)"):
        b = MR_OK.format(plan=plan, review="(진행 전)", qa="(진행 전)")
        if design is not None:
            b = re.sub(r"## 설계\n.*?(?=## 설계 확인)", "## 설계\n" + design + "\n", b, flags=re.S)
        return re.sub(r"## 설계 확인\n.*?(?=## 계획 vs 실제)", "## 설계 확인\n" + confirm + "\n", b, flags=re.S)

    def test_draft_needs_all_five_design_items(self):
        r = self.check(self.body(design="- 접근 방식: x\n- 바꿀 모듈·파일: <경로>"), "draft")
        self.assertEqual(r.returncode, 1)
        for label in ["바꿀 모듈", "데이터·API", "대안", "테스트 계획"]:
            self.assertIn(label, r.stdout)

    def test_build_blocked_until_design_confirmed(self):
        r = self.check(self.body(confirm="(진행 전)"), "build")
        self.assertEqual(r.returncode, 1)
        self.assertIn("설계 확인", r.stdout)
        r = self.check(self.body(), "build")                 # MR 문구만으로는 확정이 아니다 — d<N> 기록과 대조
        self.assertEqual(r.returncode, 1)
        self.assertIn("설계 확인 기록", r.stdout)
        seed_design()
        self.assertEqual(self.check(self.body(), "build").returncode, 0)

    def test_more_than_two_design_checks_blocked(self):
        conf = "- 확인 1: x\n- 확인 2: x\n- 확인 3: x\n- 판정: 확정"
        self.assertIn("2회를 넘음", self.check(self.body(confirm=conf), "build").stdout)

    def test_skip_allowed_for_small_change_only(self):
        skip = "- 생략: 작은 변경 (예상 5줄·1파일)"
        self.assertEqual(self.check(self.body(confirm=skip), "build").returncode, 0)
        self.write("app.py", "x = 1\n")
        self.assertEqual(self.check(self.body(confirm=skip, plan="같음"), "review").returncode, 0)
        for i in range(5):
            self.write(f"m{i}.py", "\n".join(f"v{j} = {j}" for j in range(30)) + "\n")
        r = self.check(self.body(confirm=skip, plan="같음"), "review")
        self.assertEqual(r.returncode, 1)
        self.assertIn("review.py --design", r.stdout)

    def test_design_review_dry_payload_and_limit(self):
        self.write("app.py", "def search(q):\n    return []\n")
        import vf_git
        self.write(".vibe-flow.json", '{"base": "%s"}' % vf_git.snapshot())  # 설계 확인은 기준 커밋 내용을 본다
        self.write("mr.md", self.body(confirm="(진행 전)"))
        r = self.run_script("review.py", "--design", "1", "--mr", "mr.md", "--dry")
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(r.stdout.strip(), encoding="utf-8") as f:
            payload = f.read()
        self.assertIn("설계 확인 1/2", payload)
        self.assertIn("def search", payload)          # 설계가 언급한 파일 내용
        self.assertIn("검색", payload)                 # 노스스타
        self.assertNotEqual(self.run_script("review.py", "--design", "3", "--mr", "mr.md").returncode, 0)
        self.assertIn("건너뛸 수 없", self.run_script("review.py", "--design", "2", "--mr", "mr.md").stderr)


class NorthstarDraftTest(Repo):
    def test_judge_refuses_draft_northstar(self):
        import goal_gate
        importlib.reload(goal_gate)
        self.write("docs/NORTHSTAR.md", "# 노스스타\n<!-- status: draft -->\n## 목적\n검색\n")
        goal_gate.run_codex = lambda p: "VERDICT: CREATE\nREASON: x"
        os.makedirs("docs/goals/candidates")
        self.write("docs/goals/candidates/C-1.md", "# 후보\n<!--\nstatus: candidate\n-->\n")
        with self.assertRaises(SystemExit) as e:
            goal_gate.judge("docs/goals/candidates/C-1.md", apply=True)
        self.assertEqual(e.exception.code, 3)

    def test_confirmed_northstar_with_draft_word_in_history(self):
        import vf_git
        self.write("docs/NORTHSTAR.md", "# 노스스타\n<!-- status: confirmed -->\n## 개정 이력\n| 날짜 | 초안 작성 (status: draft) |\n")
        self.assertEqual(vf_git.northstar_status("docs/NORTHSTAR.md"), "confirmed")
        self.write("docs/NORTHSTAR.md", "# 노스스타\n<!-- status: draft -->\n")
        self.assertEqual(vf_git.northstar_status("docs/NORTHSTAR.md"), "draft")


TEAM_REMAINING = "# 남은 업무\n\n- [ ] G-001 거래처 검색 → 링크\n"


class TeamHandoffTest(unittest.TestCase):
    """team-handoff 모드: 로컬 bare 원격 + 사용자가 다른 복제본 두 개."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="vf-team-")
        self.old = os.getcwd()
        seed = os.path.join(self.root, "seed")
        os.makedirs(seed)
        sh("git", "init", "-q", "-b", "main", cwd=seed)
        for k, v in (("user.email", "s@s"), ("user.name", "seed"), ("core.autocrlf", "false")):
            sh("git", "config", k, v, cwd=seed)
        files = {
            ".claude/skills/team-handoff/SKILL.md": "# team-handoff\n",
            "docs/handoff/REMAINING.md": TEAM_REMAINING,
            "docs/handoff/WORKLOG/INDEX.md": "# INDEX\n",
            "docs/handoff/WORKLOG/proto.md": "# proto\n",
            "docs/handoff/NORTHSTAR.md": "# 노스스타\n<!-- status: confirmed -->\n## 목적\n영업팀이 거래처를 찾는다\n",
            "docs/handoff/goals/G-001-search.md": GOAL.format(gid="G-001", st="active"),
            ".vibe-flow.json": '{"base": "main", "branch_prefixes": ["proto", "chore"], "test_cmd": "t"}',
            ".gitattributes": "docs/handoff/REMAINING.md merge=union\ndocs/handoff/WORKLOG/INDEX.md merge=union\n",
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
        self.a = self.clone("A", "alice")
        self.b = self.clone("B", "bob")

    def tearDown(self):
        os.chdir(self.old)
        shutil.rmtree(self.root, ignore_errors=True)

    def clone(self, name, user):
        d = os.path.join(self.root, name)
        # 줄바꿈 변환은 복제 시점에 꺼야 한다 (나중에 끄면 모든 파일이 변경으로 잡힘)
        sh("git", "clone", "-q", "-c", "core.autocrlf=false", self.bare, d, cwd=self.root)
        for k, v in (("user.email", f"{user}@x"), ("user.name", user), ("core.autocrlf", "false")):
            sh("git", "config", k, v, cwd=d)
        return d

    def ho(self, cwd, *args):
        return subprocess.run([PY, os.path.join(SCRIPTS, "handoff.py"), *args], cwd=cwd,
                              capture_output=True, text=True, encoding="utf-8")

    def test_detect_team_mode(self):
        r = self.ho(self.a, "detect")
        self.assertIn("mode=team", r.stdout)
        self.assertIn("docs/handoff/REMAINING.md", r.stdout)

    def test_claim_pushes_and_blocks_other_user(self):
        r = self.ho(self.a, "claim", "G-001", "거래처 검색", "proto/G-001-search")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("push 확인됨", r.stdout)
        remote_rem = sh("git", "show", "proto/G-001-search:docs/handoff/REMAINING.md", cwd=self.bare).stdout
        self.assertIn("[~] G-001 거래처 검색", remote_rem)
        self.assertIn("착수 @alice", remote_rem)
        r = self.ho(self.b, "claim", "G-001", "거래처 검색 다시", "proto/G-001-search-b")
        self.assertEqual(r.returncode, 1)
        self.assertIn("@alice", r.stderr)
        self.assertEqual(sh("git", "branch", "--list", "proto/G-001-search-b", cwd=self.b).stdout.strip(), "")

    def test_claim_rejects_bad_branch_prefix(self):
        r = self.ho(self.a, "claim", "G-001", "x", "feature/G-001-x")
        self.assertEqual(r.returncode, 1)
        self.assertIn("접두사", r.stderr)

    def test_stale_claim_only_warns(self):
        import dupe, vf_git, datetime
        self.ho(self.a, "claim", "G-001", "거래처 검색", "proto/G-001-search")
        sh("git", "fetch", "-q", cwd=self.b)
        os.chdir(self.b)
        later = datetime.date.today() + datetime.timedelta(days=9)
        b, w = dupe.find("## 골\nG-001\n## 사용자 가치\nx\n", vf_git.config(), remotes=[], today=later)
        self.assertFalse(b)
        self.assertTrue(any("지남" in x for x in w))

    def test_precheck_reports_others_and_claims(self):
        self.ho(self.a, "claim", "G-001", "거래처 검색", "proto/G-001-search")
        r = self.ho(self.b, "precheck")
        self.assertIn("읽을 순서", r.stdout)
        self.assertIn("@alice", r.stdout)
        self.assertIn("[~] G-001", r.stdout)

    def finish(self, cwd, user, record=True, work=True):
        def w(p, t, mode="a"):
            with open(os.path.join(cwd, p), mode, encoding="utf-8", newline="\n") as f:
                f.write(t)
        if work:
            w("app.js", "function search(q) { return q; }\n")
        if record:
            w("docs/handoff/WORKLOG/proto.md", f"\n## 2026-10-17 G-001 거래처 검색 @{user} #proto {{#2026-10-17-search-{user}}}\n- [x] 검색\n")
            w("docs/handoff/WORKLOG/INDEX.md", f"- 2026-10-17 [proto] @{user} G-001 거래처 검색 → [proto.md#2026-10-17-search-{user}](proto.md#2026-10-17-search-{user})\n")
            p = os.path.join(cwd, "docs/handoff/REMAINING.md")
            t = open(p, encoding="utf-8").read()
            t = re.sub(r"- \[~\] (G-001 [^(]*)\(착수 @\S+ [\d-]+\)[^\n]*", rf"- [x] \1(@{user} 2026-10-17)", t)
            open(p, "w", encoding="utf-8", newline="\n").write(t)
            os.makedirs(os.path.join(cwd, "docs/handoff/mr"), exist_ok=True)
            w("docs/handoff/mr/G-001.md", MR_OK.replace("{qa}", "- 대상 tree: " + "a" * 40), "w")   # 기록 커밋에 MR 본문(검증 증거)
            w("docs/handoff/mr/G-001-qa.json",   # QA 실행 기록 사본 — 수(passed·total)가 없으면 통과가 아니다(A9-08)
              '{"schema": 2, "tree": "%s", "cmd": "t", "exit": 0, "passed": 3, "total": 3}\n' % ("a" * 40), "w")
            w("docs/handoff/mr/G-001-review.md", "VERDICT: CONFIRM\n", "w")   # 리뷰 원문 사본
        sh("git", "add", "-A", cwd=cwd)
        sh("git", "commit", "-qm", "G-001 거래처 검색", cwd=cwd)

    def test_check_record_passes_with_work_and_record_in_same_commit(self):
        self.ho(self.a, "claim", "G-001", "거래처 검색", "proto/G-001-search")
        self.finish(self.a, "alice")
        r = self.ho(self.a, "check-record")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_check_record_rejects_record_only_commit(self):
        self.ho(self.a, "claim", "G-001", "거래처 검색", "proto/G-001-search")
        self.finish(self.a, "alice", work=False)
        r = self.ho(self.a, "check-record")
        self.assertEqual(r.returncode, 1)
        self.assertIn("작업 파일", r.stdout)

    def test_check_record_rejects_missing_record(self):
        self.ho(self.a, "claim", "G-001", "거래처 검색", "proto/G-001-search")
        self.finish(self.a, "alice", record=False)
        r = self.ho(self.a, "check-record")
        self.assertEqual(r.returncode, 1)
        self.assertIn("WORKLOG", r.stdout)
        self.assertIn("[~]", r.stdout)

    def test_claim_commits_new_goal_file_and_judge_sees_it(self):
        g2 = os.path.join(self.a, "docs/handoff/goals/G-002-new.md")
        with open(g2, "w", encoding="utf-8", newline="\n") as f:
            f.write(GOAL.format(gid="G-002", st="active").replace("시험", "Squad 이름 검색"))
        r = self.ho(self.a, "claim", "G-002", "Squad 이름 검색", "proto/G-002-squad-search")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        files = sh("git", "show", "--name-only", "--format=", "proto/G-002-squad-search", cwd=self.bare).stdout
        self.assertIn("docs/handoff/goals/G-002-new.md", files)
        sh("git", "fetch", "-q", cwd=self.b)
        os.chdir(self.b)
        import goal_gate
        importlib.reload(goal_gate)
        allg = goal_gate.active_goals_everywhere()
        self.assertIn("G-002", allg)
        self.assertIn("proto/G-002-squad-search", allg["G-002"][1])

    def test_korean_goal_filename_on_other_branch_is_seen(self):
        # git은 한글 파일명을 "\353..."로 감싸 출력한다 — Windows basename이 백슬래시에서 잘라 놓쳤던 버그
        g = os.path.join(self.a, "docs/handoff/goals/G-003-스쿼드-이름-검색.md")
        with open(g, "w", encoding="utf-8", newline="\n") as f:
            f.write(GOAL.format(gid="G-003", st="active").replace("시험", "스쿼드 이름 검색"))
        r = self.ho(self.a, "claim", "G-003", "스쿼드 이름 검색", "proto/G-003-squad")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        sh("git", "fetch", "-q", cwd=self.b)
        os.chdir(self.b)
        import goal_gate
        importlib.reload(goal_gate)
        self.assertIn(3, goal_gate.all_known_ids())
        self.assertIn("G-003", goal_gate.active_goals_everywhere())
        self.assertEqual(goal_gate.reserve_id(), "G-004")

    def test_merge_allows_record_only_change_after_qa(self):
        self.ho(self.a, "claim", "G-001", "거래처 검색", "proto/G-001-search")
        with open(os.path.join(self.a, "app.js"), "a", encoding="utf-8", newline="\n") as f:
            f.write("function search(q) { return q; }\n")
        sh("git", "commit", "-qam", "G-001 구현", cwd=self.a)
        os.chdir(self.a)
        import vf_git
        qa_tree = vf_git.git("rev-parse", "HEAD^{tree}")
        body = MR_OK.replace("G-001 시험 골", "G-001 거래처 검색").format(
            plan="같음", review="- 라운드 1: x\n- 판정: 확정",
            qa=f"- 대상 tree: {qa_tree}\n- 코드: 통과\n- 브라우저: 해당 없음 — 검색 함수만, 화면 없음")
        os.makedirs(".vibe", exist_ok=True)
        with open(".git/info/exclude", "a") as f:
            f.write(".vibe/\n")
        with open(".vibe/mr.md", "w", encoding="utf-8") as f:
            f.write(body)
        self.finish(self.a, "alice", work=False)   # QA 뒤 기록만 추가
        r = subprocess.run([PY, os.path.join(SCRIPTS, "mr_check.py"), ".vibe/mr.md", "--stage", "merge"],
                           cwd=self.a, capture_output=True, text=True, encoding="utf-8")
        self.assertNotIn("재검증", r.stdout)
        with open(os.path.join(self.a, "app.js"), "a", encoding="utf-8", newline="\n") as f:
            f.write("// QA 뒤 코드 변경\n")
        r = subprocess.run([PY, os.path.join(SCRIPTS, "mr_check.py"), ".vibe/mr.md", "--stage", "merge"],
                           cwd=self.a, capture_output=True, text=True, encoding="utf-8")
        self.assertIn("재검증", r.stdout)
        self.assertIn("app.js", r.stdout)

    def test_records_amended_into_last_work_commit_after_qa(self):
        self.ho(self.a, "claim", "G-001", "거래처 검색", "proto/G-001-search")
        with open(os.path.join(self.a, "app.js"), "a", encoding="utf-8", newline="\n") as f:
            f.write("function search(q) { return q; }\n")
        sh("git", "commit", "-qam", "G-001 구현", cwd=self.a)          # 이 커밋이 QA 대상
        self.finish(self.a, "alice", work=False)                        # QA 뒤 기록을 따로 커밋하면
        self.assertEqual(self.ho(self.a, "check-record").returncode, 1)  # 같은 커밋이 아니라 거부
        sh("git", "reset", "-q", "--soft", "HEAD~1", cwd=self.a)        # 기록을 마지막 작업 커밋에 합친다
        sh("git", "commit", "-q", "--amend", "--no-edit", cwd=self.a)
        self.assertEqual(self.ho(self.a, "check-record").returncode, 0)

    def test_union_merge_keeps_both_index_lines(self):
        self.ho(self.a, "claim", "G-001", "거래처 검색", "proto/G-001-search")
        self.finish(self.a, "alice")
        sh("git", "checkout", "-q", "-b", "chore/G-000-x", "origin/main", cwd=self.b)
        with open(os.path.join(self.b, "docs/handoff/WORKLOG/INDEX.md"), "a", encoding="utf-8", newline="\n") as f:
            f.write("- 2026-10-17 [ops] @bob G-000 정리 → [ops.md](ops.md)\n")
        sh("git", "commit", "-qam", "G-000 정리", cwd=self.b)
        sh("git", "fetch", "-q", self.a, "proto/G-001-search:incoming", cwd=self.b)
        r = sh("git", "merge", "-q", "--no-edit", "incoming", cwd=self.b, ok=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        idx = open(os.path.join(self.b, "docs/handoff/WORKLOG/INDEX.md"), encoding="utf-8").read()
        self.assertIn("@bob G-000", idx)
        self.assertIn("@alice G-001", idx)


# ---------- 인덱스 구조 (docs/structure.md 「인덱스 계층」) ----------
LEGACY_DECISIONS = """# 결정 기록 (DECISIONS)

> 머리말 — 이 텍스트도 그대로 옮겨져야 한다.

---

## D-001 검색은 부분 일치
- 날짜 2026-09-30 · 결정자 @seed · 상태 대체됨 → D-003
- 결정: 부분 일치. 영향: SUP-01 화면
- 근거: [안건](../planning/a.md)

## D-002 목록은 20건씩
- 날짜 2026-10-01 · 결정자 @seed · 상태 유효
- 결정: 20건.
- 영향: HOME-01 · 프로토타입 `core.js` `calc.util`

## D-003 검색은 초성까지 (D-001 대체)
- 날짜 2026-10-02 · 결정자 @seed · 상태 유효
- 결정: 초성 검색 포함. 영향: SUP-01
"""
LEGACY_REMAINING = """# 남은 업무

> 형식 안내 — 그대로 남아야 한다.

## 결정
- [x] 결정: 검색 방식 → D-001 (@seed 2026-09-30)
- [ ] 결정: 정렬 기준

## 남은 일
- [ ] G-001 거래처 검색 → 링크
- [x] 초기 화면 (@seed 2026-10-01)
  - 상세: 첫 화면
- [x] 부모 완료지만 하위 미완료
  - [ ] 하위 남은 일
"""
LEGACY_WL_INDEX = "# INDEX\n\n> 진입점.\n\n## 2026-10\n" + "".join(
    f"- 2026-10-{d:02d} [proto] @seed 항목 {d} → [proto.md#e{d}](proto.md#e{d})\n" for d in range(28, 0, -1)) + "\n## 2026-09\n" + "".join(
    f"- 2026-09-{d:02d} [proto] @seed 지난달 {d} → [proto.md#s{d}](proto.md#s{d})\n" for d in range(30, 25, -1))
LEGACY_WL_PROTO = "# WORKLOG — proto\n\n> 프로토타입.\n\n" + "".join(
    f"<!--\ndate: 2026-10-{d:02d}\ntopic: proto\n-->\n\n## 2026-10-{d:02d} 항목 {d} @seed {{#e{d}}}\n- [x] 일\n\n" for d in range(1, 29)) + "".join(
    f"## 2026-09-{d:02d} 지난달 {d} @seed {{#s{d}}}\n- [x] 일\n\n" for d in range(26, 31))
CUR_DEC = f"DECISIONS-{datetime.date.today():%Y-%m}.md"   # 새 결정이 붙는 이번 달 본문 파일
LEGACY = {
    "docs/handoff/DECISIONS.md": LEGACY_DECISIONS,
    "docs/handoff/REMAINING.md": LEGACY_REMAINING,
    "docs/handoff/PLAN.md": "# PLAN\n\n## 개요\n거래처를 찾는다.\n\n## 변경 이력\n| 날짜 | 변경 |\n|---|---|\n| 2026-10-01 | 최초 |\n",
    "docs/handoff/LESSONS.md": "# 교훈\n\n- 한 번 실수 (@seed, 2026-10-01)\n- **두 번 실수 (2회)** — 방지법 (@seed, 2026-10-02)\n",
    "docs/handoff/NORTHSTAR.md": "# 노스스타\n<!-- status: confirmed -->\n## 목적\n영업팀이 거래처를 찾는다\n## 하지 않을 것\n회계\n",
    "docs/handoff/WORKLOG/INDEX.md": LEGACY_WL_INDEX,
    "docs/handoff/WORKLOG/proto.md": LEGACY_WL_PROTO,
    "docs/planning/a.md": "# 안건\n",
}


class IndexStructureTest(unittest.TestCase):
    """예전 구조를 migrate → 새 구조에서 두 사람이 같은 날 기록해도 충돌·번호 중복이 없는지."""
    clone = TeamHandoffTest.clone
    ho = TeamHandoffTest.ho
    finish = TeamHandoffTest.finish

    def setUp(self):
        TeamHandoffTest.setUp(self)
        for p, t in LEGACY.items():
            self.put(self.a, p, t)
        sh("git", "add", "-A", cwd=self.a)
        sh("git", "commit", "-qm", "G-000 예전 구조", cwd=self.a)
        sh("git", "push", "-q", "origin", "main", cwd=self.a)

    def tearDown(self):
        TeamHandoffTest.tearDown(self)

    def put(self, cwd, p, t, mode="w"):
        os.makedirs(os.path.dirname(os.path.join(cwd, p)), exist_ok=True)
        with open(os.path.join(cwd, p), mode, encoding="utf-8", newline="\n") as f:
            f.write(t)

    def get(self, cwd, p):
        with open(os.path.join(cwd, p), encoding="utf-8", newline="") as f:
            return f.read()

    def migrate_and_publish(self):
        r = self.ho(self.a, "migrate")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        snap = re.search(r"스냅숏 (\S+)", r.stdout).group(1)
        sh("git", "add", "-A", cwd=self.a)
        sh("git", "commit", "-qm", "G-000 인덱스 구조로 이전", cwd=self.a)
        sh("git", "push", "-q", "origin", "main", cwd=self.a)
        sh("git", "pull", "-q", "origin", "main", cwd=self.b)
        return snap

    def test_migrate_is_lossless_and_lint_clean(self):
        r = self.ho(self.a, "migrate")
        snap = re.search(r"스냅숏 (\S+)", r.stdout).group(1)
        v = self.ho(self.a, "verify-migration", snap)
        self.assertEqual(v.returncode, 0, v.stdout + v.stderr)
        self.assertIn("결정: 원문 3건 · 본문 파일 합 3건", v.stdout)
        self.assertIn("무손실", v.stdout)
        sep = self.get(self.a, "docs/handoff/DECISIONS-2026-09.md")    # 결정 날짜의 달마다 본문 파일(논의 F15)
        octo = self.get(self.a, "docs/handoff/DECISIONS-2026-10.md")
        self.assertEqual(sep + octo, LEGACY_DECISIONS)                 # 이어 붙이면 머리말까지 바이트 그대로
        self.assertIn("## D-001", sep)
        self.assertNotIn("## D-002", sep)
        idx = self.get(self.a, "docs/handoff/DECISIONS.md")
        self.assertIn("vibe-index: DECISIONS", idx)
        self.assertRegex(idx, r"- D-001 .*대체됨→D-003")
        self.assertRegex(idx, r"- D-003 .*대체 D-001 .*#SUP-01")
        self.assertRegex(idx, r"- D-002 .*#HOME-01 #core.js #calc.util")          # 영향 줄의 코드 이름도 태그
        rem = self.get(self.a, "docs/handoff/REMAINING.md")
        self.assertNotIn("[x] 초기 화면", rem)
        self.assertIn("[x] 부모 완료지만 하위 미완료", rem)            # 하위에 미완료가 있으면 옮기지 않는다
        done = self.get(self.a, "docs/handoff/REMAINING-done-2026-10.md")
        self.assertIn("- [x] 초기 화면 (@seed 2026-10-01)\n  - 상세: 첫 화면\n", done)
        self.assertIn("## 남은 일", done)                              # 원래 소제목을 함께
        wl = self.get(self.a, "docs/handoff/WORKLOG/INDEX.md")
        self.assertEqual(len(re.findall(r"^- 2026", wl, re.M)), 28)    # 지난달 5줄은 보관
        self.assertIn("지난달 30", self.get(self.a, "docs/handoff/WORKLOG/INDEX-2026-09.md"))
        lint = self.ho(self.a, "lint")
        self.assertEqual(lint.returncode, 0, lint.stdout)
        pre = self.ho(self.a, "precheck")
        self.assertIn("시작 읽기량", pre.stdout)
        self.assertIn("DECISIONS.md", pre.stdout)                     # 결정은 grep 안내로만
        self.assertNotIn("docs/handoff/DECISIONS.md →", pre.stdout)    # 읽을 순서에는 없다

    def test_migration_commit_passes_check_record(self):
        # 이전 커밋에서는 옛 교훈·결정이 새 본문 파일에 '추가'된 것처럼 보인다 — 이동이지 새 항목이 아니다
        sh("git", "checkout", "-q", "-b", "chore/G-000-index", cwd=self.a)
        self.ho(self.a, "migrate")
        self.put(self.a, "app.js", "// 규칙 문서 갱신 대신\n", "a")
        self.put(self.a, "docs/handoff/WORKLOG/proto.md", "\n## 2026-10-17 G-000 인덱스 이전 @alice {#2026-10-17-idx-alice}\n- [x] 이전\n", "a")
        idx = self.get(self.a, "docs/handoff/WORKLOG/INDEX.md").replace(
            "## 2026-10\n", "## 2026-10\n- 2026-10-17 [proto] @alice G-000 인덱스 이전 → [proto.md#2026-10-17-idx-alice](proto.md#2026-10-17-idx-alice)\n")
        self.put(self.a, "docs/handoff/WORKLOG/INDEX.md", idx)
        self.put(self.a, "docs/handoff/REMAINING.md", "- [x] G-000 인덱스 이전 (@alice 2026-10-17)\n", "a")
        sh("git", "add", "-A", cwd=self.a)
        sh("git", "commit", "-qm", "G-000 인덱스 이전", cwd=self.a)
        r = self.ho(self.a, "check-record")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_plan_split_file_section_needs_index_line(self):
        # PLAN 본문이 커지면 섹션별 PLAN-<slug>.md로 나뉜다 — 그 파일의 새 섹션도 INDEX 줄이 같은 커밋에
        sh("git", "checkout", "-q", "-b", "chore/G-000-index", cwd=self.a)
        self.ho(self.a, "migrate")
        sh("git", "add", "-A", cwd=self.a)
        sh("git", "commit", "-qm", "G-000 이전", "--no-verify", cwd=self.a)
        self.put(self.a, "docs/handoff/PLAN-scope.md", "# PLAN — 범위\n\n## 범위 밖\n회계는 하지 않는다\n", "w")
        self.put(self.a, "app.js", "// 범위 정리\n", "a")
        self.finish_g000(self.a)
        r = self.ho(self.a, "check-record")
        self.assertEqual(r.returncode, 1)
        self.assertIn("PLAN-scope.md에 새 섹션 「범위 밖」", r.stdout)
        lint = self.ho(self.a, "lint")
        self.assertIn("PLAN-scope.md의 섹션 「범위 밖」", lint.stdout)
        self.put(self.a, "docs/handoff/PLAN.md", "- [범위 밖](PLAN-scope.md#범위-밖) — 회계는 하지 않는다\n", "a")
        sh("git", "add", "-A", cwd=self.a)
        sh("git", "commit", "-q", "--amend", "--no-edit", cwd=self.a)
        self.assertEqual(self.ho(self.a, "check-record").returncode, 0)
        self.assertEqual(self.ho(self.a, "lint").returncode, 0)

    def test_new_section_with_title_used_elsewhere_is_still_new(self):
        # 「하지 않을 것」은 NORTHSTAR 본문에도 있는 제목 — 그래도 PLAN에 새로 쓴 섹션이면 INDEX 줄이 필요하다
        sh("git", "checkout", "-q", "-b", "chore/G-000-index", cwd=self.a)
        self.ho(self.a, "migrate")
        sh("git", "add", "-A", cwd=self.a)
        sh("git", "commit", "-qm", "G-000 이전", "--no-verify", cwd=self.a)
        self.put(self.a, "docs/handoff/PLAN-scope.md", "# PLAN — 범위\n\n## 하지 않을 것\n회계\n", "w")
        self.put(self.a, "app.js", "// 범위\n", "a")
        self.finish_g000(self.a, "dup")
        r = self.ho(self.a, "check-record")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("PLAN-scope.md에 새 섹션 「하지 않을 것」", r.stdout)

    def test_section_moved_between_plan_files_is_a_move(self):
        # 같은 커밋에서 PLAN-body.md에서 지우고 PLAN-scope.md에 그대로 옮긴 섹션은 새 항목이 아니다(INDEX는 링크만 갱신)
        sh("git", "checkout", "-q", "-b", "chore/G-000-index", cwd=self.a)
        self.ho(self.a, "migrate")
        sh("git", "add", "-A", cwd=self.a)
        sh("git", "commit", "-qm", "G-000 이전", "--no-verify", cwd=self.a)
        body = self.get(self.a, "docs/handoff/PLAN-body.md")
        sec = body[body.index("## 개요"):body.index("## 변경 이력")]
        self.put(self.a, "docs/handoff/PLAN-body.md", body.replace(sec, ""), "w")
        self.put(self.a, "docs/handoff/PLAN-scope.md", sec, "w")
        idx = self.get(self.a, "docs/handoff/PLAN.md").replace("(PLAN-body.md#개요)", "(PLAN-scope.md#개요)")
        self.put(self.a, "docs/handoff/PLAN.md", idx, "w")
        self.put(self.a, "app.js", "// 분리\n", "a")
        self.finish_g000(self.a, "move")
        self.assertEqual(self.ho(self.a, "check-record").returncode, 0)
        self.assertEqual(self.ho(self.a, "lint").returncode, 0)

    def finish_g000(self, cwd, slug="scope"):
        self.put(cwd, "docs/handoff/WORKLOG/proto.md", f"\n## 2026-10-17 G-000 {slug} @alice {{#2026-10-17-{slug}-alice}}\n- [x] {slug}\n", "a")
        idx = self.get(cwd, "docs/handoff/WORKLOG/INDEX.md").replace(
            "## 2026-10\n", f"## 2026-10\n- 2026-10-17 [proto] @alice G-000 {slug} → [proto.md#2026-10-17-{slug}-alice](proto.md#2026-10-17-{slug}-alice)\n")
        self.put(cwd, "docs/handoff/WORKLOG/INDEX.md", idx, "w")
        self.put(cwd, "docs/handoff/REMAINING.md", f"- [x] G-000 {slug} (@alice 2026-10-17)\n", "a")
        sh("git", "add", "-A", cwd=cwd)
        sh("git", "commit", "-qm", f"G-000 {slug}", cwd=cwd)

    def test_archive_moves_last_month_index_lines(self):
        # 지난달 INDEX 줄은 개수와 상관없이 그 달 보관 파일로 — 링크(같은 폴더 상대 경로)는 그대로 맞는다
        self.ho(self.a, "migrate")
        last = (datetime.date.today().replace(day=1) - datetime.timedelta(days=1))
        line = f"- {last:%Y-%m}-28 [proto] @alice 늦게 적은 지난달 일 → [proto.md#e1](proto.md#e1)\n"
        idx = self.get(self.a, "docs/handoff/WORKLOG/INDEX.md")
        cur = f"## {datetime.date.today():%Y-%m}\n"
        self.put(self.a, "docs/handoff/WORKLOG/INDEX.md", idx.replace(cur, cur + line), "w")
        self.assertIn("지난달 줄 1개", self.ho(self.a, "lint").stdout)
        r = self.ho(self.a, "archive")
        self.assertIn("WORKLOG INDEX 오래된 줄 1개", r.stdout)
        self.assertNotIn("늦게 적은 지난달 일", self.get(self.a, "docs/handoff/WORKLOG/INDEX.md"))
        arch = self.get(self.a, f"docs/handoff/WORKLOG/INDEX-{last:%Y-%m}.md")
        self.assertIn(line, arch)
        self.assertLess(arch.index(line), arch.index("지난달 30"))         # 옮긴 줄이 기존 보관 줄보다 새것 → 위
        after = self.ho(self.a, "lint")
        self.assertEqual(after.returncode, 0, after.stdout)
        self.assertNotIn("지난달 줄", after.stdout)

    def test_verify_detects_changed_text(self):
        r = self.ho(self.a, "migrate")
        snap = re.search(r"스냅숏 (\S+)", r.stdout).group(1)
        p = "docs/handoff/DECISIONS-2026-09.md"
        before = self.get(self.a, p)
        self.put(self.a, p, before.replace("부분 일치.", "부분일치."), "w")
        v = self.ho(self.a, "verify-migration", snap)
        self.assertEqual(v.returncode, 1)
        self.assertIn("BAD", v.stdout)
        self.put(self.a, p, before, "w")
        self.assertEqual(self.ho(self.a, "verify-migration", snap).returncode, 0)
        rem = "docs/handoff/REMAINING-done-2026-10.md"
        self.put(self.a, rem, self.get(self.a, rem).replace("- 상세: 첫 화면\n", ""))
        self.assertEqual(self.ho(self.a, "verify-migration", snap).returncode, 1)

    def test_northstar_draft_is_read_through_index(self):
        self.put(self.a, "docs/handoff/NORTHSTAR.md", LEGACY["docs/handoff/NORTHSTAR.md"].replace("confirmed", "draft"))
        self.ho(self.a, "migrate")
        os.chdir(self.a)
        import vf_git
        self.assertEqual(vf_git.northstar_status("docs/handoff/NORTHSTAR.md"), "draft")
        self.assertIn("영업팀", vf_git.northstar_text("docs/handoff/NORTHSTAR.md"))

    def test_next_id_reserves_on_remote_so_unpushed_clones_do_not_collide(self):
        self.migrate_and_publish()
        a = self.ho(self.a, "next-id", "D")
        b = self.ho(self.b, "next-id", "D")                          # A는 아무것도 push하지 않았다
        self.assertEqual(a.returncode, 0, a.stderr)
        self.assertEqual((a.stdout.strip(), b.stdout.strip()), ("D-004", "D-005"))
        refs = sh("git", "for-each-ref", "--format=%(refname)", "refs/vibe-ids", cwd=self.bare).stdout
        self.assertIn("refs/vibe-ids/D-004", refs)
        self.assertIn("refs/vibe-ids/D-005", refs)
        self.assertIn(f"{CUR_DEC} 끝에", a.stderr)

    def test_next_id_points_to_decisions_md_before_index_mode(self):
        # 인덱스 모드가 아닌 레포에서는 결정을 DECISIONS.md 끝에 — 달 본문 파일을 새로 만들게 하면 안 된다
        r = self.ho(self.a, "next-id", "D", "--scan-only")
        self.assertEqual(r.stdout.strip(), "D-004")
        self.assertIn("docs/handoff/DECISIONS.md 끝에", r.stderr)
        self.assertNotIn("DECISIONS-20", r.stderr)

    def test_next_id_refuses_when_remote_unreachable(self):
        self.migrate_and_publish()
        sh("git", "remote", "set-url", "origin", os.path.join(self.root, "없는-원격.git"), cwd=self.a)
        r = self.ho(self.a, "next-id", "D")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("원격 예약 실패", r.stderr + r.stdout)
        self.assertIn("--scan-only", r.stderr + r.stdout)
        r = self.ho(self.a, "next-id", "D", "--scan-only")              # 사용자가 직접 하는 우회
        self.assertEqual(r.stdout.strip(), "D-004")

    def record_decision(self, cwd, user, did, branch):
        sh("git", "checkout", "-q", "-b", branch, "origin/main", cwd=cwd)
        self.put(cwd, f"docs/handoff/{CUR_DEC}",
                 f"\n## {did} {user}의 결정\n- 날짜 2026-10-17 · 결정자 @{user} · 상태 유효\n- 결정: 정렬. 영향: SUP-02\n", "a")
        self.put(cwd, "docs/handoff/DECISIONS.md",
                 f"- {did} · {user}의 결정 · 2026-10-17 · @{user} · 유효 · #SUP-02 → [본문]({CUR_DEC}#{did.lower()}-{user}의-결정)\n", "a")

    def test_check_record_requires_index_line_in_same_commit(self):
        self.migrate_and_publish()
        sh("git", "pull", "-q", "origin", "main", cwd=self.a)
        self.ho(self.a, "claim", "G-001", "거래처 검색", "proto/G-001-search")
        did = self.ho(self.a, "next-id", "D").stdout.strip()
        self.put(self.a, f"docs/handoff/{CUR_DEC}", f"\n## {did} 정렬은 이름순\n- 날짜 2026-10-17 · 결정자 @alice · 상태 유효\n", "a")
        self.finish(self.a, "alice")
        r = self.ho(self.a, "check-record")
        self.assertEqual(r.returncode, 1)
        self.assertIn(f"{did} 본문을 썼는데 DECISIONS.md INDEX 줄", r.stdout)
        self.put(self.a, "docs/handoff/DECISIONS.md", f"- {did} · 정렬은 이름순 · 2026-10-17 · @alice · 유효 → [본문]({CUR_DEC}#{did.lower()}-정렬은-이름순)\n", "a")
        sh("git", "add", "-A", cwd=self.a)
        sh("git", "commit", "-q", "--amend", "--no-edit", cwd=self.a)
        r = self.ho(self.a, "check-record")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_two_people_same_day_merge_without_conflict_or_duplicate(self):
        self.migrate_and_publish()
        da = self.ho(self.a, "next-id", "D").stdout.strip()
        db = self.ho(self.b, "next-id", "D").stdout.strip()
        self.record_decision(self.a, "alice", da, "docs/G-000-a")
        self.record_decision(self.b, "bob", db, "docs/G-000-b")
        for cwd, who in ((self.a, "alice"), (self.b, "bob")):
            self.put(cwd, "docs/handoff/REMAINING.md", f"- [ ] {who}가 남긴 일\n", "a")
            self.put(cwd, "docs/handoff/WORKLOG/proto.md", f"\n## 2026-10-17 {who} 기록 @{who} {{#2026-10-17-x-{who}}}\n- [x] 일\n", "a")
            idx = self.get(cwd, "docs/handoff/WORKLOG/INDEX.md").replace(
                "## 2026-10\n", f"## 2026-10\n- 2026-10-17 [proto] @{who} 기록 → [proto.md#2026-10-17-x-{who}](proto.md#2026-10-17-x-{who})\n")
            self.put(cwd, "docs/handoff/WORKLOG/INDEX.md", idx)
            sh("git", "commit", "-qam", f"G-000 {who} 기록", cwd=cwd)
            sh("git", "push", "-q", "origin", "HEAD", cwd=cwd)
        m = self.clone("M", "merger")                                   # 두 PR을 차례로 머지
        for br in ("docs/G-000-a", "docs/G-000-b"):
            r = sh("git", "merge", "-q", "--no-ff", "--no-edit", f"origin/{br}", cwd=m, ok=False)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        idx = self.get(m, "docs/handoff/DECISIONS.md")
        self.assertIn(f"- {da} · alice", idx)
        self.assertIn(f"- {db} · bob", idx)
        self.assertNotEqual(da, db)
        os.chdir(m)
        lint = self.ho(m, "lint")
        self.assertEqual(lint.returncode, 0, lint.stdout)
        self.assertNotIn("<<<<<<<", self.get(m, "docs/handoff/WORKLOG/INDEX.md"))

    def test_lint_finds_missing_index_broken_link_and_union_duplicates(self):
        self.ho(self.a, "migrate")
        self.put(self.a, f"docs/handoff/{CUR_DEC}", "\n## D-004 INDEX 없는 결정\n- 날짜 2026-10-17 · 상태 유효\n", "a")
        self.put(self.a, "docs/handoff/PLAN-body.md", "\n[없는 문서](없음.md)\n", "a")
        dup = re.search(r"^- D-002 .*$", self.get(self.a, "docs/handoff/DECISIONS.md"), re.M).group(0)
        self.put(self.a, "docs/handoff/DECISIONS.md", dup + "\n", "a")
        r = self.ho(self.a, "lint")
        self.assertEqual(r.returncode, 1)
        self.assertIn("D-004", r.stdout)
        self.assertIn("붙일 줄", r.stdout)                              # 준수 경로: 붙여 넣을 INDEX 줄
        self.assertIn("끊긴 링크", r.stdout)
        self.assertIn("D-002 줄이 두 개", r.stdout)

    def test_archive_moves_done_old_lines_and_big_topic_keeping_links(self):
        self.ho(self.a, "migrate")
        self.put(self.a, ".vibe-flow.json", '{"base": "main", "branch_prefixes": ["proto", "chore"], "index": {"topic_max_chars": 2000}}')
        self.put(self.a, "docs/handoff/REMAINING.md", "- [x] 방금 끝난 일 (@alice 2026-10-17)\n", "a")
        for d in range(1, 4):
            idx = self.get(self.a, "docs/handoff/WORKLOG/INDEX.md").replace(
                "## 2026-10\n", f"## 2026-10\n- 2026-10-17 [proto] @alice 새 {d} → [proto.md#e1](proto.md#e1)\n")
            self.put(self.a, "docs/handoff/WORKLOG/INDEX.md", idx)
        before = self.ho(self.a, "lint").stdout
        self.assertIn("완료 항목 1건 잔존", before)
        self.assertIn("WORKLOG INDEX 31줄", before)
        r = self.ho(self.a, "archive")
        self.assertIn("REMAINING 완료 1건", r.stdout)
        self.assertIn("토픽 proto.md", r.stdout)
        self.assertNotIn("[x] 방금 끝난 일", self.get(self.a, "docs/handoff/REMAINING.md"))
        self.assertIn("[x] 방금 끝난 일", self.get(self.a, "docs/handoff/REMAINING-done-2026-10.md"))
        self.assertEqual(self.get(self.a, "docs/handoff/WORKLOG/proto-2026-10.md"), LEGACY_WL_PROTO)  # 옮긴 본문은 그대로
        self.assertIn('<a id="e1"></a>', self.get(self.a, "docs/handoff/WORKLOG/proto.md"))       # 옛 링크용 넘김 앵커
        after = self.ho(self.a, "lint")
        self.assertEqual(after.returncode, 0, after.stdout)              # INDEX의 옛 링크 proto.md#e1이 그대로 맞는다
        self.assertNotIn("잔존", after.stdout)

    def test_judge_adds_goal_index_line(self):
        self.migrate_and_publish()
        os.chdir(self.a)
        import goal_gate
        importlib.reload(goal_gate)
        goal_gate.run_codex = lambda prompt: "VERDICT: CREATE\nREASON: 목적과 연결"
        os.makedirs("docs/handoff/goals/candidates", exist_ok=True)
        with open("docs/handoff/goals/candidates/C-1.md", "w", encoding="utf-8") as f:
            f.write("# 거래처 CSV 내보내기\n<!--\nstatus: candidate\n-->\n## 왜\nx\n")
        goal_gate.judge("docs/handoff/goals/candidates/C-1.md", apply=True)
        self.assertRegex(self.get(self.a, "docs/handoff/goals/INDEX.md"), r"- G-002 거래처 CSV 내보내기 · active")
        self.assertEqual(self.ho(self.a, "lint").returncode, 0)


class FlexibilityTest(Repo):
    """경직성 점검(docs/flexibility.md)으로 바꾼 규칙."""

    def setUp(self):
        super().setUp()
        sh("git", "checkout", "-q", "-b", "G-001/test", cwd=self.d)
        import vf_git
        self.vf = vf_git
        self.write("docs/DECISIONS.md", "# 결정\n\n## D-001 설계 판정\n- G-001 설계는 사람이 확정\n")   # MR_OK의 사람 판정 D-001
        self.write(".vibe-flow.json", '{"base": "%s"}' % vf_git.snapshot())
        self.write(".gitignore", "mr.md\n")

    def check(self, body, stage):
        self.write("mr.md", body)
        seed_review()   # 리뷰 확정은 .vibe/review 기록과 대조된다
        seed_design(n=1, verdict="CHANGES"); seed_design(n=2, verdict="CHANGES")   # MR_OK의 사람 판정은 설계 확인 2회 뒤에만
        seed_qa_run(body)
        return self.run_script("mr_check.py", "mr.md", "--stage", stage)

    def qa(self, browser):
        target = self.vf.snapshot()
        return MR_OK.format(plan="같음", review="- 라운드 1: x\n- 판정: 확정",
                            qa=f"- 대상 tree: {target}\n- 코드: 통과\n- 브라우저: {browser}\n- 미검증·생략 항목과 사유: 없음\n")

    def test_code_outside_ui_globs_needs_a_reason_not_silent_pass(self):
        self.write("lib/format.js", "export const f = 1\n")              # 글롭에 안 걸리는 화면 코드일 수도 있음
        r = self.check(self.qa("해당 없음"), "merge")
        self.assertEqual(r.returncode, 1)
        self.assertIn("UI 판정 불명확", r.stdout)
        self.assertIn("다음 행동", r.stdout)                            # 준수 경로 안내
        r = self.check(self.qa("해당 없음 — 서버 포맷 함수만, 화면 코드에서 안 씀"), "merge")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_english_headings_via_mr_labels(self):
        self.write(".vibe-flow.json", '{"base": "%s", "mr_labels": {"Goal": "골", "User value": "사용자 가치", '
                   '"Done when": "완료 조건", "Out of scope": "제외 범위", "Impact/Risk": "영향·위험", '
                   '"Verification": "검증 계획", "Design": "설계", "Approach": "접근 방식", '
                   '"Modules": "바꿀 모듈", "Data/API": "데이터·API", "Alternatives": "대안", "Test plan": "테스트 계획"}}'
                   % self.vf.snapshot())
        body = ("## Goal\nG-001 search\n## User value\nsales finds vendors\n## Done when\n- partial match\n"
                "## Out of scope\n- excel\n## Impact/Risk\n- none\n## Verification\n- unittest\n## Design\n"
                "- Approach: filter in memory\n- Modules: app.py\n- Data/API: none\n- Alternatives: DB search — data is small\n"
                "- Test plan: partial match test first\n")
        r = self.check(body, "draft")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.write(".vibe-flow.json", '{"base": "%s"}' % self.vf.snapshot())
        self.assertEqual(self.check(body, "draft").returncode, 1)       # 별칭이 없으면 그대로 차단

    def test_next_names_the_stage_and_sub_skill(self):
        self.write("mr.md", MR_OK.format(plan="(진행 전)", review="(진행 전)", qa="(진행 전)"))
        seed_design(n=1, verdict="CHANGES"); seed_design(n=2, verdict="CHANGES")   # MR_OK의 사람 판정은 설계 확인 2회 뒤에만
        r = self.run_script("mr_check.py", "mr.md", "--next")
        self.assertIn("review → 세부 스킬 vibe-dev", r.stdout)            # 설계 확정, 계획 vs 실제 없음 → 구현 중
        no_design = MR_OK.replace("- 확인 1: blocker 0\n- 사람 결정: D-001 — 없음\n- 판정: 확정 (사람 판정 D-001)\n", "")
        self.write("mr.md", no_design.format(plan="같음", review="(진행 전)", qa="(진행 전)"))
        r = self.run_script("mr_check.py", "mr.md", "--next")
        self.assertIn("build → 세부 스킬 vibe-design", r.stdout)         # "리뷰만"이라도 설계 확인부터


if __name__ == "__main__":
    unittest.main()
