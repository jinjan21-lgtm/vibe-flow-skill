"""런 6: 단일 판정 엔진 — 로컬 merge 검사와 새 clone verify-evidence(재연)가 같은 판정을 내는가.
실행: python -m unittest tests/test_r6_engine.py -v (레포 루트)

실제 흐름(가짜 codex → review.py 설계 확인·리뷰, qa_run.py --red·QA, export-evidence, 기록 amend)을 만든 뒤
시나리오마다 같은 변형을 넣고 ① 원래 레포에서 mr_check --stage merge ② --no-local clone에서 verify-evidence를 돌려
통과/실패와 핵심 사유가 같은지 본다. 증거 판(schema)·상태(UNVERIFIED·ACCEPTED-RISK·POLICY-PENDING)도 여기서.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_scripts import DESIGN_OK, GOAL, PY, SCRIPTS, sh  # noqa: E402

FAKE = r'''import os, sys
a = sys.argv
out = a[a.index("-o") + 1]
sys.stdin.read()
with open(os.environ["FAKE_CODEX_REPLY"], encoding="utf-8") as f:
    body = f.read()
with open(out, "w", encoding="utf-8") as f:
    f.write(body)
'''

TEST_FILE = '''import unittest

from app import search


class T(unittest.TestCase):
    def test_partial(self):
        self.assertEqual(search("b"), ["abc"])
'''
IMPL = 'def search(q):\n    return [x for x in ["abc", "xyz"] if q in x]\n'

MR = """## 골
G-001 거래처 부분 검색
## 사용자 가치
영업팀이 이름 일부로 거래처를 찾는다
## 완료 조건
- [ ] 부분 일치 검색
## 제외 범위
- 엑셀
## 영향·위험
- 연관 범위: 검색 함수
- 위험: 검색 결과 순서가 바뀔 수 있음
- 미확인: {unknown}
{risk_extra}## 검증 계획
- 코드: test_app.T.test_partial
- 브라우저: 해당 없음
## 설계
- 접근 방식: 메모리 필터
- 바꿀 모듈·파일: app.py, test_app.py
- 데이터·API 변경: 없음
- 대안과 선택 이유: DB LIKE 대신 메모리 — 데이터가 작음
- 테스트 계획: 부분 일치 테스트 먼저(RED)
## 설계 확인
- 확인 1: blocker 0
- 판정: 확정
## 계획 vs 실제
같음
## 리뷰 기록
- 라운드 1 (전체): blocker 0
- 판정: 확정
## QA 결과
- 브라우저: 해당 없음 — 서버 함수만, 화면 없음
- 미검증·생략 항목과 사유: {unverified}
{qa_extra}"""

R1 = "ROUND: 1\nRESOLVED: 없음\nCHECKED: 1 — test_app.T.test_partial\nVERDICT: CONFIRM\n"

_TEMPLATES = {}   # 흐름 이름 → 그 흐름을 끝낸 레포 사본(.vibe 포함) — 같은 흐름을 테스트마다 다시 돌리지 않는다


def tearDownModule():
    for p in _TEMPLATES.values():
        shutil.rmtree(p, ignore_errors=True)


class Engine(unittest.TestCase):
    clone_args = ("--no-local",)

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="vf-r6-")
        self.d = os.path.join(self.root, "repo")
        os.makedirs(self.d)
        sh("git", "init", "-q", "-b", "main", cwd=self.d)
        for k, v in (("user.email", "t@t"), ("user.name", "t"), ("core.autocrlf", "false")):
            sh("git", "config", k, v, cwd=self.d)
        files = {"docs/goals/G-001-search.md": GOAL.format(gid="G-001", st="active"),
                 "docs/NORTHSTAR.md": "# 노스스타\n## 목적\n검색\n", "docs/WORKLOG.md": "# 작업 기록\n",
                 "docs/REMAINING.md": "# 남은 업무\n\n- [~] G-001 거래처 검색 (착수 @t 2026-10-18)\n",
                 "app.py": "def search(q):\n    return []\n", ".gitignore": ".vibe/\n__pycache__/\n",
                 ".vibe-flow.json": json.dumps({"base": "main", "test_cmd": f'"{PY}" -m unittest -v'})}
        for p, t in files.items():
            self.write(p, t)
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-qm", "G-000 기준", cwd=self.d)
        sh("git", "checkout", "-q", "-b", "feat/G-001-search", cwd=self.d)
        self.bin = os.path.join(self.root, "bin")
        os.makedirs(self.bin)
        fake = os.path.join(self.bin, "fake_codex.py")
        with open(fake, "w", encoding="utf-8") as f:
            f.write(FAKE)
        with open(os.path.join(self.bin, "codex.cmd"), "w") as f:
            f.write(f'@"{PY}" "{fake}" %*\n')
        posix = os.path.join(self.bin, "codex")
        with open(posix, "w", newline="\n") as f:
            f.write(f'#!/bin/sh\nexec "{PY}" "{fake}" "$@"\n')
        os.chmod(posix, 0o755)
        self.reply = os.path.join(self.bin, "reply.txt")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    # ---- 도구 ----
    def write(self, p, text, mode="w"):
        p = os.path.join(self.d, p)
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, mode, encoding="utf-8", newline="\n") as f:
            f.write(text)

    def read(self, p):
        with open(os.path.join(self.d, p), encoding="utf-8") as f:
            return f.read()

    def run_py(self, script, *args, reply=None, cwd=None):
        env = {**os.environ, "PATH": self.bin + os.pathsep + os.environ["PATH"], "FAKE_CODEX_REPLY": self.reply}
        if reply is not None:
            with open(self.reply, "w", encoding="utf-8") as f:
                f.write(reply)
        return subprocess.run([PY, os.path.join(SCRIPTS, script), *args], cwd=cwd or self.d, env=env,
                              capture_output=True, text=True, encoding="utf-8")

    def ok(self, r):
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def mr(self, unknown="없음", risk_extra="", unverified="없음", qa_extra="", checked=False):
        body = MR.format(unknown=unknown, risk_extra=risk_extra, unverified=unverified, qa_extra=qa_extra)
        if checked:
            body = body.replace("- [ ] 부분 일치 검색", "- [x] 부분 일치 검색")
        qa = re.search(r"^## QA 결과\n", body, re.M)
        old = self.read(".vibe/mr-G-001.md") if os.path.exists(os.path.join(self.d, ".vibe/mr-G-001.md")) else ""
        keep = re.findall(r"^- (?:대상 tree|코드|RED):.*$", old, re.M)   # qa_run이 채운 줄은 남긴다
        body = body[:qa.end()] + "".join(k + "\n" for k in keep) + body[qa.end():]
        self.write(".vibe/mr-G-001.md", body)

    def edit(self, p, old, new):
        t = self.read(p)
        self.assertIn(old, t, p)
        self.write(p, t.replace(old, new))

    def edit_json(self, p, **kw):
        rec = json.loads(self.read(p))
        rec.update(kw)
        self.write(p, json.dumps(rec, ensure_ascii=False))

    def qa_rec(self):
        """flow가 남긴 QA 실행 기록(.vibe/qa/<tree>.json — RED 아님) 경로(레포 기준)."""
        hits = [f for f in os.listdir(os.path.join(self.d, ".vibe", "qa")) if re.fullmatch(r"[0-9a-f]{40}\.json", f)]
        self.assertEqual(len(hits), 1, hits)
        return f".vibe/qa/{hits[0]}"

    def template(self, key, build):
        """build(흐름)를 처음 한 번만 돌리고 그 레포를 복사해 둔다. 다음 테스트는 사본에서 시작 — 같은 증거, 빠르게.
        브랜치·기준 tree·작업물 tree가 사본에서도 같으므로 .vibe/ 기록(도장)도 그대로 유효하다."""
        tpl = _TEMPLATES.get(key)
        if tpl is None:
            build()
            tpl = tempfile.mkdtemp(prefix="vf-r6-tpl-")
            shutil.copytree(self.d, os.path.join(tpl, "repo"))
            _TEMPLATES[key] = tpl
            return
        self.d = os.path.join(self.root, "repo-copy")
        shutil.copytree(os.path.join(tpl, "repo"), self.d)

    # ---- 흐름: 설계 확인 → RED → 구현 → 리뷰 → QA → 기록(export·amend) ----
    def flow(self, red=True, rounds=(R1,), after_review=None, before_qa=None, **mr_kw):
        """rounds: 리뷰 라운드마다 가짜 Codex 응답(라운드 3은 --files app.py). after_review: 리뷰 뒤·QA 전 변경,
        before_qa: MR 체크 뒤 QA 직전 변경."""
        self.mr(**{k: v for k, v in mr_kw.items() if k != "checked"})
        self.ok(self.run_py("review.py", "--design", "1", "--mr", ".vibe/mr-G-001.md", reply=DESIGN_OK))
        self.write("test_app.py", TEST_FILE)
        if red:
            self.ok(self.run_py("qa_run.py", "--red", "--mr", ".vibe/mr-G-001.md"))
        self.write("app.py", IMPL)
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-qm", "G-001 거래처 부분 검색", cwd=self.d)
        for n, reply in enumerate(rounds, 1):
            self.ok(self.run_py("review.py", "--round", str(n), "--mr", ".vibe/mr-G-001.md",
                                *(("--files", "app.py") if n == 3 else ()), reply=reply))
        if after_review:
            after_review()
        self.mr(checked=True, **{k: v for k, v in mr_kw.items() if k != "checked"})
        if before_qa:
            before_qa()
        self.ok(self.run_py("qa_run.py", "--mr", ".vibe/mr-G-001.md"))

    def record(self, late_code=False, before_export=None):
        self.write("docs/WORKLOG.md", "\n## 2026-10-18 G-001 거래처 부분 검색\n", "a")
        self.write("docs/REMAINING.md", "# 남은 업무\n\n- [x] G-001 거래처 검색 (@t 2026-10-18)\n")
        if before_export:
            before_export()
        self.ok(self.run_py("handoff.py", "export-evidence", "G-001"))
        if late_code:
            self.write("app.py", "# 몰래 바꿈\n", "a")
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-q", "--amend", "--no-edit", cwd=self.d)

    def judge(self, *verify_args, run_tests=True):
        """(로컬 merge 결과, 새 clone verify-evidence 결과). verify-evidence는 기본으로 --run-tests(재연 merge가 통과하면
        test_cmd를 다시 돌려 기록과 대조) — 없으면 통과 흐름도 UNPROVEN(exit 4)이라 로컬과 같은 판정을 볼 수 없다."""
        verify_args = verify_args + (("--run-tests",) if run_tests else ())
        local = self.run_py("mr_check.py", ".vibe/mr-G-001.md", "--stage", "merge")
        clone = os.path.join(self.root, "clone")
        shutil.rmtree(clone, ignore_errors=True)
        sh("git", "clone", "-q", *self.clone_args, "-b", "feat/G-001-search", self.d, clone, cwd=self.root)
        self.assertFalse(os.path.exists(os.path.join(clone, ".vibe")))
        ver = self.run_py("handoff.py", "verify-evidence", "G-001", *verify_args, cwd=clone)
        return local, ver

    def same(self, local, ver, passed, key=None):
        """두 판정이 같다: 통과 여부 + 핵심 사유(key)가 양쪽 출력에 다 있다."""
        msg = f"\n--- local ---\n{local.stdout}{local.stderr}\n--- verify ---\n{ver.stdout}{ver.stderr}"
        self.assertEqual(local.returncode == 0, passed, msg)
        self.assertEqual(ver.returncode == 0, passed, msg)
        if key:
            self.assertRegex(local.stdout, key, msg)
            self.assertRegex(ver.stdout, key, msg)


class EquivalenceTest(Engine):
    def test_normal_flow_passes_both(self):
        self.flow()
        self.record()
        local, ver = self.judge()
        self.same(local, ver, True)
        self.assertIn("재연 merge 검사", ver.stdout)

    def test_rerun_reexecutes_tests(self):
        self.flow()
        self.record()
        _, ver = self.judge()   # --run-tests
        self.assertEqual(ver.returncode, 0, ver.stdout + ver.stderr)
        self.assertRegex(ver.stdout, r"PASS .*독립 재실행")

    def test_without_run_tests_is_unproven(self):   # 감사 10: 재실행 없이는 통과가 아니라 UNPROVEN(exit 4)
        self.flow()
        self.record()
        local, ver = self.judge(run_tests=False)
        self.assertEqual(local.returncode, 0, local.stdout)
        self.assertEqual(ver.returncode, 4, ver.stdout + ver.stderr)
        self.assertIn("UNPROVEN", ver.stdout)
        self.assertNotRegex(ver.stdout, r"PASS .*독립 재실행")

    def test_missing_red_fails_both(self):   # C5: 새 clone은 RED를 INFO로만 봤다 — 이제 같은 규칙
        self.flow(red=False)
        self.record()
        self.same(*self.judge(), passed=False, key="RED 증거 없음")

    def test_red_of_other_goal_is_not_evidence(self):
        self.flow()
        for f in os.listdir(os.path.join(self.d, ".vibe", "qa")):
            if f.startswith("red-"):
                p = os.path.join(self.d, ".vibe", "qa", f)
                with open(p, encoding="utf-8") as fh:
                    rec = json.load(fh)
                rec["goal"] = "G-099"
                with open(p, "w", encoding="utf-8") as fh:
                    json.dump(rec, fh)
        self.record()
        self.same(*self.judge(), passed=False, key="RED 증거 없음")

    def test_code_changed_after_qa_fails_both(self):
        self.flow()
        self.record(late_code=True)
        self.same(*self.judge(), passed=False, key="QA 대상 .* 이후 바뀐 파일")

    def test_unchecked_condition_fails_both(self):
        self.flow()
        self.record(before_export=lambda: self.write(
            ".vibe/mr-G-001.md", self.read(".vibe/mr-G-001.md").replace("- [x] 부분 일치 검색", "- [ ] 부분 일치 검색")))
        self.same(*self.judge(), passed=False, key="완료 조건 미체크")

    def test_conditions_changed_after_review_fail_both(self):
        self.flow()
        self.record(before_export=lambda: self.write(
            ".vibe/mr-G-001.md", self.read(".vibe/mr-G-001.md").replace("- [x] 부분 일치 검색", "- [x] 부분 일치 검색(대소문자 무시)")))
        self.same(*self.judge(), passed=False, key="리뷰 뒤 완료 조건이 바뀜")


class StateTest(Engine):
    """상태 셋: 기술적 미검증·위험 인수·정책 미결은 다른 상태이고 어느 것도 게이트를 열지 않는다(우회는 사용자 직접)."""
    DEC = "# 결정\n\n## D-001 G-001 위험 인수\n- 결정자 @t · 모바일 화면 확인 미검증 배포 위험 인수\n\n" \
          "## D-002 G-001 ADR 정의\n- 결정자 @t · ADR 법인 할인 포함 여부: 포함한다\n"

    def test_unverified_blocks_both(self):
        self.flow(unverified="모바일 화면 확인")
        self.record()
        self.same(*self.judge(), passed=False, key="UNVERIFIED 모바일 화면 확인")

    def test_risk_acceptance_is_state_not_pass(self):
        self.write("docs/DECISIONS.md", self.DEC)
        self.flow(unverified="모바일 화면 확인", qa_extra="- 위험 인수: D-001 — 모바일 화면 확인\n")
        self.record()
        local, ver = self.judge()
        self.same(local, ver, False, key="ACCEPTED-RISK 모바일 화면 확인")
        self.assertIn("STATE G-001 ACCEPTED-RISK", ver.stdout)
        self.assertNotIn("UNVERIFIED 모바일", local.stdout)

    def test_old_human_approval_no_longer_passes(self):   # C5 충돌 1: 「사람 승인이면 통과」 경로 제거
        self.write("docs/DECISIONS.md", self.DEC)
        self.flow(unverified="모바일 화면 확인", qa_extra="- 사람 승인: D-001 — 모바일 화면 확인\n")
        self.record()
        self.same(*self.judge(), passed=False, key="ACCEPTED-RISK")

    def test_policy_pending_blocks_and_risk_acceptance_does_not_close_it(self):
        self.write("docs/DECISIONS.md", self.DEC)
        self.flow(unknown="ADR 법인 할인 포함 여부", qa_extra="- 위험 인수: D-001 — ADR 법인 할인 포함 여부\n")
        self.record()
        self.same(*self.judge(), passed=False, key="POLICY-PENDING ADR 법인 할인 포함 여부")

    def test_policy_decision_closes_pending(self):
        self.write("docs/DECISIONS.md", self.DEC)
        self.flow(unknown="ADR 법인 할인 포함 여부", risk_extra="- 정책 결정: D-002 — ADR 법인 할인 포함 여부\n")
        self.record()
        self.same(*self.judge(), passed=True)

    def test_resolved_unknown_with_test_evidence(self):
        self.flow(unknown="빈 검색어 동작", risk_extra="- 해소: 빈 검색어 동작 — test_app.T.test_partial\n")
        self.record()
        self.same(*self.judge(), passed=True)

    def test_resolution_without_evidence_stays_pending(self):
        self.flow(unknown="빈 검색어 동작", risk_extra="- 해소: 빈 검색어 동작 — 확인함\n")
        self.record()
        self.same(*self.judge(), passed=False, key="POLICY-PENDING 빈 검색어 동작")

    def test_decision_must_name_goal(self):
        self.write("docs/DECISIONS.md", "# 결정\n\n## D-002 다른 골 정책\n- 결정자 @t\n")
        self.flow(unknown="ADR 법인 할인 포함 여부", risk_extra="- 정책 결정: D-002 — ADR 법인 할인 포함 여부\n")
        self.record()
        self.same(*self.judge(), passed=False, key="POLICY-PENDING")


class SchemaTest(Engine):
    def _strip_schema(self):
        h = os.path.join(self.d, "docs", "mr")
        q = os.path.join(h, "G-001-qa.json")
        with open(q, encoding="utf-8") as fh:
            rec = json.load(fh)
        rec.pop("schema", None)
        with open(q, "w", encoding="utf-8") as f:
            json.dump(rec, f)
        rv = os.path.join(h, "G-001-review.md")
        with open(rv, encoding="utf-8") as fh:
            txt = fh.read()
        with open(rv, "w", encoding="utf-8") as f:
            f.write(re.sub(r"^schema: \d+\n", "", txt, flags=re.M))

    def test_old_evidence_is_legacy_not_pass(self):
        self.flow()
        self.record(before_export=None)
        self._strip_schema()
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-q", "--amend", "--no-edit", cwd=self.d)
        _, ver = self.judge()
        self.assertEqual(ver.returncode, 3, ver.stdout + ver.stderr)
        self.assertIn("LEGACY G-001", ver.stdout)
        self.assertIn("재검증 대상", ver.stdout)
        self.assertNotIn("통과 —", ver.stdout)

    def test_current_records_carry_schema(self):
        import vf_git
        self.flow()
        self.record()
        rec = json.loads(self.read("docs/mr/G-001-qa.json"))
        self.assertEqual(rec["schema"], vf_git.EVIDENCE_SCHEMA)
        self.assertIn(f"schema: {vf_git.EVIDENCE_SCHEMA}", self.read("docs/mr/G-001-review.md"))
        red = json.loads(self.read("docs/mr/G-001-red.json"))
        self.assertEqual((red["goal"], red["schema"]), ("G-001", vf_git.EVIDENCE_SCHEMA))
        self.assertIn("code_tree:", self.read(".vibe/review/r1.tree"))


class TamperTest(Engine):
    """기본 흐름 하나를 만들고 기록(export) 전에 .vibe/를 바꾼다 — 로컬과 clone이 같은 증거를 본다(런 5 손 증거 시험 이식)."""

    def setUp(self):
        super().setUp()
        self.template("base", self.flow)

    def test_qa_tree_object_absent_in_clone(self):   # --no-local clone에는 amend 전 QA tree 객체가 없다 — 그래도 같은 판정
        tree = json.loads(self.read(self.qa_rec()))["tree"]
        self.record()
        local, ver = self.judge()
        self.same(local, ver, True)
        clone = os.path.join(self.root, "clone")
        self.assertNotEqual(sh("git", "cat-file", "-e", tree, cwd=clone, ok=False).returncode, 0)

    def test_qa_exit_1(self):
        self.record(before_export=lambda: self.edit_json(self.qa_rec(), exit=1, ok=False))
        self.same(*self.judge(), passed=False, key="exit 1")

    def test_qa_cmd_differs_from_committed_test_cmd(self):
        self.record(before_export=lambda: self.edit_json(self.qa_rec(), cmd="echo ok"))
        self.same(*self.judge(), passed=False, key="테스트 명령이 바뀜")

    def test_all_skipped_qa(self):
        self.record(before_export=lambda: self.edit_json(self.qa_rec(), passed=0, total=2, skipped=2))
        self.same(*self.judge(), passed=False, key=r"통과가 아님\(전부 건너뜀")

    def test_ok_false_qa(self):
        self.record(before_export=lambda: self.edit_json(self.qa_rec(), ok=False))
        self.same(*self.judge(), passed=False, key=r"통과가 아님")

    def test_last_verdict_changes(self):
        self.record(before_export=lambda: self.edit(".vibe/review/r1.txt", "VERDICT: CONFIRM", "VERDICT: CHANGES"))
        self.same(*self.judge(), passed=False, key="r1.txt는 VERDICT CHANGES")

    def test_blocker_in_last_round(self):
        self.record(before_export=lambda: self.edit(".vibe/review/r1.txt", "VERDICT: CONFIRM",
                                                    "FINDING: F2 | blocker | y\nVERDICT: CONFIRM"))
        self.same(*self.judge(), passed=False, key="blocker FINDING 1개")

    def test_contract_changed_after_review(self):   # 「제외 범위」는 리뷰 계약 — 리뷰 뒤 바꾸면 리뷰 재실행
        self.record(before_export=lambda: self.edit(".vibe/mr-G-001.md", "- 엑셀\n", "- 엑셀\n- PDF 내보내기\n"))
        self.same(*self.judge(), passed=False, key="리뷰 뒤 계약")

    def test_empty_completion_item(self):
        self.record(before_export=lambda: self.edit(".vibe/mr-G-001.md", "- [x] 부분 일치 검색\n",
                                                    "- [x] 부분 일치 검색\n- [x] \n"))
        self.same(*self.judge(), passed=False, key="빈 항목 1개")

    def test_no_code_review_round(self):   # 설계 확인(d1)만 남으면 코드 리뷰가 아니다
        def drop():
            for f in ("r1.txt", "r1.tree"):
                os.remove(os.path.join(self.d, ".vibe", "review", f))
        self.record(before_export=drop)
        local, ver = self.judge()
        self.same(local, ver, False)
        # 로컬은 r1 기록이 없다고, clone은 export 사본에 rN 회차가 없다고 — 같은 사실의 두 표현(사본에 회차가 없으면 재연할 것이 없다)
        self.assertIn("유효한 기록 없음", local.stdout)
        self.assertIn("rN.txt 회차 없음", ver.stdout)

    def test_other_goal_stamp_both_fail(self):   # .vibe 기록 goal이 다른 골 — 로컬은 기록 무효, export는 그 회차를 뺀다
        self.record(before_export=lambda: self.edit(".vibe/review/r1.tree", "goal: G-001", "goal: G-009"))
        local, ver = self.judge()
        self.same(local, ver, False)
        self.assertIn("다른 골(G-009)", local.stdout)
        self.assertIn("rN.txt 회차 없음", ver.stdout)

    # ---- 커밋된 사본만 바꾼 경우: 로컬(.vibe)에는 없는 변조라 clone 판정만 본다 ----
    def amend_copy(self, p, old, new):
        self.edit(p, old, new)
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-q", "--amend", "--no-edit", cwd=self.d)

    def test_committed_stamp_goal_other_goal(self):   # 로컬 불가: 사본 도장만 바꾼 변조
        self.record()
        self.amend_copy("docs/mr/G-001-review.md", "goal: G-001", "goal: G-009")
        _, ver = self.judge()
        self.assertEqual(ver.returncode, 1, ver.stdout + ver.stderr)
        self.assertIn("다른 골(G-009)", ver.stdout)

    def test_committed_goal_not_in_mr_copy(self):   # 로컬 불가: export가 「골」에 그 골이 없는 MR을 거부한다
        self.record()
        self.amend_copy("docs/mr/G-001.md", "## 골\nG-001", "## 골\nG-002")
        _, ver = self.judge()
        self.assertEqual(ver.returncode, 1, ver.stdout + ver.stderr)
        self.assertRegex(ver.stdout, r"FAIL G-001가 MR 사본 「골」에 있음 — 「골」: G-002")

    def test_committed_stamp_removed_is_legacy(self):   # 로컬 불가: 도장 없는 사본은 판 없음 = LEGACY(통과 아님)
        self.record()
        rv = self.read("docs/mr/G-001-review.md")
        self.write("docs/mr/G-001-review.md", re.sub(r"<!-- stamp\n.*?-->\n", "", rv, flags=re.S))
        sh("git", "add", "-A", cwd=self.d)
        sh("git", "commit", "-q", "--amend", "--no-edit", cwd=self.d)
        _, ver = self.judge()
        self.assertEqual(ver.returncode, 3, ver.stdout + ver.stderr)
        self.assertIn("LEGACY G-001", ver.stdout)


class CaptureTest(Engine):
    """브라우저 통과 + 캡처: export가 .vibe/qa/ 캡처를 <핸드오프>/mr/G-001-evidence/로 옮기고 사본 링크를 바꾼다."""
    PASS_LINE = "- 브라우저: 통과 — 검색 화면 확인\n- 증거: {links}\n"

    def setUp(self):
        super().setUp()
        self.template("base", self.flow)

    def browser(self, links, files=("A1.png",)):
        def go():
            self.edit(".vibe/mr-G-001.md", "- 브라우저: 해당 없음 — 서버 함수만, 화면 없음\n",
                      self.PASS_LINE.format(links=links))
            for f in files:
                self.write(f".vibe/qa/G-001/{f}", "PNG")
        return go

    def test_committed_capture_passes(self):
        self.record(before_export=self.browser("![A1](.vibe/qa/G-001/A1.png)"))
        self.assertIn("![A1](G-001-evidence/A1.png)", self.read("docs/mr/G-001.md"))
        self.assertEqual(self.read("docs/mr/G-001-evidence/A1.png"), "PNG")
        self.assertIn("docs/mr/G-001-evidence/A1.png", sh("git", "ls-files", cwd=self.d).stdout)
        self.same(*self.judge(), passed=True)

    def test_missing_capture_fails(self):
        self.record(before_export=self.browser("![A1](.vibe/qa/G-001/A1.png) ![A2](.vibe/qa/G-001/gone.png)"))
        self.same(*self.judge(), passed=False, key=r"브라우저 증거 파일 없음: .*gone\.png")

    def test_no_capture_link_fails(self):
        self.record(before_export=self.browser("화면 봄", files=()))
        self.same(*self.judge(), passed=False, key="증거 캡처 파일 링크 없음")


class FlowVariantTest(Engine):
    """흐름 중간에 바뀌는 경우 — 템플릿 없이 각자 흐름."""

    def test_code_changed_after_review_before_qa(self):   # 리뷰가 본 tree 뒤 코드 변경 — clone은 code_tree로 같은 판정
        self.flow(after_review=lambda: self.write("app.py", "# 리뷰 뒤 바꿈\n", "a"))
        self.record()
        self.same(*self.judge(), passed=False, key="리뷰 확정 뒤 코드 변경")

    def test_records_changed_before_qa_pass(self):   # QA 전에 기록 파일만 바뀌면 코드가 아니다
        self.flow(before_qa=lambda: self.write("docs/WORKLOG.md", "\n- QA 전 메모\n", "a"))
        self.record()
        self.same(*self.judge(), passed=True)


LEDGER_R1 = "FINDING: F1 | blocker | 빈 검색어\nFINDING: M1 | major | 대소문자\nCHECKED: 1 — test_app.T.test_partial\nVERDICT: CHANGES\n"
LEDGER_R2 = "RESOLVED: F1\nCARRY: M1 — 골 후보 대소문자 무시는 다음 골\nVERDICT: CONFIRM\n"


class LedgerTest(Engine):
    """지적 장부: r1 CHANGES(blocker F1·major M1) → r2 CONFIRM(F1 RESOLVED, M1 CARRY). 기록 전에 r2 원문을 바꿔 연다."""

    def setUp(self):
        super().setUp()
        self.template("ledger", lambda: self.flow(rounds=(LEDGER_R1, LEDGER_R2)))

    def test_resolved_and_carried_pass(self):   # major CARRY는 닫힌 것
        self.record()
        self.same(*self.judge(), passed=True)

    def test_blocker_open_from_earlier_round(self):
        self.record(before_export=lambda: self.edit(".vibe/review/r2.txt", "RESOLVED: F1", "RESOLVED: 없음"))
        self.same(*self.judge(), passed=False, key=r"열린 blocker F1\(r1\)")

    def test_major_open_from_earlier_round(self):
        self.record(before_export=lambda: self.edit(".vibe/review/r2.txt", "CARRY: M1 — 골 후보 대소문자 무시는 다음 골\n", ""))
        self.same(*self.judge(), passed=False, key=r"major M1\(r1\)")


HUMAN_R1 = "FINDING: F1 | blocker | 빈 검색어\nCHECKED: 1 — test_app.T.test_partial\nVERDICT: CHANGES\n"
HUMAN_DEC = "# 결정\n\n## D-007 G-001 리뷰 보류 해제\n- 결정자 @t · 사람이 F1 수용(빈 검색어는 다음 골)\n"


class HumanDecisionTest(Engine):
    """3라운드 CHANGES 뒤 사람 판정: '- 사람 결정: D-007 — <IDs> (tree <r3>)' + '- 판정: 확정 (사람 판정 D-007)'
    + 커밋된 DECISIONS 블록(골 ID·남은 ID)."""

    def setUp(self):
        super().setUp()
        self.template("human", lambda: self.flow(rounds=(HUMAN_R1, "VERDICT: CHANGES\n", "VERDICT: CHANGES\n")))

    def human(self, ids="F1", tree=None, line=True, dec=HUMAN_DEC):
        def go():
            p = os.path.join(self.d, ".vibe", "review", "r3.tree")
            r3 = open(p, encoding="utf-8").readline().strip() if os.path.exists(p) else "0" * 40
            rec = (f"- 사람 결정: D-007 — {ids} (tree {tree or r3})\n" if line else "") + "- 판정: 확정 (사람 판정 D-007)\n"
            self.edit(".vibe/mr-G-001.md", "- 판정: 확정\n## QA 결과", rec + "## QA 결과")
            if dec:
                self.write("docs/DECISIONS.md", dec)
        return go

    def test_human_decision_passes(self):
        self.record(before_export=self.human())
        self.same(*self.judge(), passed=True)

    def test_missing_decision_block(self):
        self.record(before_export=self.human(dec=None))
        self.same(*self.judge(), passed=False, key="'## D-007' 결정이 없음")

    def test_decision_block_without_goal(self):
        self.record(before_export=self.human(dec="# 결정\n\n## D-007 다른 골 보류 해제\n- F1 수용\n"))
        self.same(*self.judge(), passed=False, key=r"결정 블록\(DECISIONS.md\)에 이 골 ID")

    def test_decision_tree_mismatch(self):
        self.record(before_export=self.human(tree="abcdef1234567"))
        self.same(*self.judge(), passed=False, key="사람 결정 D-007의 tree abcdef1234")

    def test_missing_decision_line(self):
        self.record(before_export=self.human(line=False))
        self.same(*self.judge(), passed=False, key="'- 사람 결정: D-007 — <지적 ID들>' 줄 없음")

    def test_open_finding_not_covered(self):
        self.record(before_export=self.human(ids="없음", dec="# 결정\n\n## D-007 G-001 리뷰 보류 해제\n- 사람이 확정\n"))
        self.same(*self.judge(), passed=False, key="열린 지적 F1 없음")

    # B-05: 단일 엔진 mr_check.human_review가 유효 회차 [1, 2, 3]을 요구한다(이식 중 드러난 빈틈 — 로컬·clone 모두 통과했었다)
    def test_lone_r3_fails(self):   # r1·r2를 지운 r3 하나는 3라운드를 다 쓴 것이 아니다
        def go():
            for f in ("r1.txt", "r1.tree", "r2.txt", "r2.tree"):
                os.remove(os.path.join(self.d, ".vibe", "review", f))
            self.human(ids="없음")()
        self.record(before_export=go)
        self.same(*self.judge(), passed=False, key="r1·r2·r3")


class HumanNeedsR3Test(Engine):
    def test_human_decision_before_r3(self):   # 1라운드 CONFIRM 흐름에 사람 판정을 적으면 — r3 없음
        self.template("base", self.flow)
        self.record(before_export=HumanDecisionTest.human(self, ids="없음"))
        self.same(*self.judge(), passed=False, key=r"유효 기록 r1·r2·r3가 모두 있어야 함")   # 사람 판정은 r1·r2·r3 모두(감사 9)


class RedNeedsMrTest(Engine):
    def test_red_without_mr_refused(self):
        self.write("test_app.py", TEST_FILE)
        r = self.run_py("qa_run.py", "--red")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("--mr", r.stderr)


if __name__ == "__main__":
    unittest.main()
