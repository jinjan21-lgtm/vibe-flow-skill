"""선점 범위 공지 회귀: 선점이 골 ID·제목만 알려 동료가 「무엇을 바꾸는지」 모르고 같은 파일을 고치던 구조.
- handoff.py scope G-### --mr <MR>: 「설계」 '바꿀 모듈·파일'을 내 착수 줄에 '· 범위: …'로 붙여 골 브랜치에 push
- 동료 precheck가 범위를 보여 준다
- 동료의 계획·변경 파일이 남의 공지 범위와 겹치면 draft부터 막고, 「영향·위험」 '- 겹침 확인: G-### — <조율>'로 푼다
- 내 MR은 build부터 설계 파일이, review부터 실제 바꾼 코드 파일이 공지 범위 안이어야 한다(착수 줄이 있을 때)
- test_cmd 'node <파일>.test.js'·'node --test'는 테스트 실행이다(구문 검사만이 아니다)
실행: python -m unittest tests/test_claim_scope.py -v (레포 루트)"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_scripts import GOAL, PY, SCRIPTS, sh  # noqa: E402
from test_c2_record import init_repo, write  # noqa: E402

REM = "docs/handoff/REMAINING.md"


def mr(gid, files, risk="- 위험: 없음"):
    return (f"## 골\n{gid} 시험 골\n## 사용자 가치\n영업팀이 검색한다\n## 완료 조건\n- [ ] 부분 일치 검색\n## 제외 범위\n- 엑셀\n"
            f"## 영향·위험\n{risk}\n## 검증 계획\n- 코드: unittest\n## 설계\n- 접근 방식: 검색 함수 추가\n"
            f"- 바꿀 모듈·파일: {files}\n- 데이터·API 변경: 없음\n- 대안과 선택 이유: 메모리 필터 — 데이터가 작음\n"
            f"- 테스트 계획: 부분 일치 테스트 먼저\n## 설계 확인\n(진행 전)\n## 계획 vs 실제\n(진행 전)\n## 리뷰 기록\n(진행 전)\n## QA 결과\n(진행 전)\n")


class SyntaxNodeRunnerTest(unittest.TestCase):
    def test_node_test_file_is_a_runner(self):
        import mr_check
        self.assertFalse(mr_check.syntax_only_cmd("python s/syntax_check.py docs/prototype && node docs/prototype/tests/calc.test.js"))
        self.assertFalse(mr_check.syntax_only_cmd("python s/syntax_check.py src && node --test"))
        self.assertFalse(mr_check.syntax_only_cmd("python s/syntax_check.py src && node tests/a.spec.mjs"))

    def test_node_non_test_script_is_not_a_runner(self):
        import mr_check
        self.assertTrue(mr_check.syntax_only_cmd("python s/syntax_check.py src && node scripts/build.js"))


class ClaimScopeTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="vf-scope-")
        seed = os.path.join(self.root, "seed")
        os.makedirs(seed)
        init_repo(seed, "seed")
        for p, t in {
            ".claude/skills/team-handoff/SKILL.md": "# team-handoff\n",
            REM: "# 남은 업무\n\n- [ ] G-001 거래처 검색\n- [ ] G-002 화면 정리\n",
            "docs/handoff/WORKLOG/INDEX.md": "# INDEX\n",
            "docs/handoff/WORKLOG/proto.md": "# proto\n",
            "docs/handoff/NORTHSTAR.md": "# 노스스타\n<!-- status: confirmed -->\n## 목적\n검색\n",
            "docs/handoff/goals/G-001-search.md": GOAL.format(gid="G-001", st="active"),
            "docs/handoff/goals/G-002-ui.md": GOAL.format(gid="G-002", st="active"),
            ".vibe-flow.json": '{"base": "main", "branch_prefixes": ["proto"], "test_cmd": "t"}',
            "app/calc.js": "// calc\n", "app/ui.js": "// ui\n", "app/other.js": "// other\n",
        }.items():
            write(seed, p, t)
        sh("git", "add", "-A", cwd=seed)
        sh("git", "commit", "-qm", "seed", cwd=seed)
        bare = os.path.join(self.root, "origin.git")
        sh("git", "clone", "-q", "--bare", seed, bare, cwd=self.root)
        self.a, self.b = os.path.join(self.root, "A"), os.path.join(self.root, "B")
        for d, u in ((self.a, "alice"), (self.b, "bob")):
            sh("git", "clone", "-q", "-c", "core.autocrlf=false", bare, d, cwd=self.root)
            for k, v in (("user.email", f"{u}@x"), ("user.name", u)):
                sh("git", "config", k, v, cwd=d)
            write(d, ".git/info/exclude", "\n.vibe/\n", "a")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run_py(self, script, *args, cwd):
        return subprocess.run([PY, os.path.join(SCRIPTS, script), *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                              env=dict(os.environ, PYTHONIOENCODING="utf-8"))

    def ho(self, *args, cwd):
        return self.run_py("handoff.py", *args, cwd=cwd)

    def mc(self, path, stage, cwd):
        return self.run_py("mr_check.py", path, "--stage", stage, cwd=cwd)

    def write_mr(self, d, gid, files, **kw):
        write(d, f".vibe/mr-{gid}.md", mr(gid, files, **kw))
        return f".vibe/mr-{gid}.md"

    def alice_claims_and_scopes(self, files="`app/calc.js`(계산), `app/ui.js`"):
        r = self.ho("claim", "G-001", "거래처 검색", "proto/G-001-search", cwd=self.a)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        m = self.write_mr(self.a, "G-001", files)
        return self.ho("scope", "G-001", "--mr", m, cwd=self.a)

    def test_scope_publishes_files_on_claim_branch(self):
        r = self.alice_claims_and_scopes()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        sh("git", "fetch", "-q", "origin", cwd=self.b)
        rem = sh("git", "show", f"origin/proto/G-001-search:{REM}", cwd=self.b).stdout
        line = [l for l in rem.splitlines() if l.startswith("- [~] G-001")][0]
        self.assertIn("범위: app/calc.js, app/ui.js", line)

    def test_rescope_replaces_previous_scope(self):
        self.alice_claims_and_scopes()
        m = self.write_mr(self.a, "G-001", "`app/calc.js`, `app/other.js`")
        r = self.ho("scope", "G-001", "--mr", m, cwd=self.a)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        line = [l for l in open(os.path.join(self.a, REM), encoding="utf-8").read().splitlines() if l.startswith("- [~] G-001")][0]
        self.assertEqual(line.count("범위:"), 1, line)
        self.assertIn("범위: app/calc.js, app/other.js", line)

    def test_scope_needs_own_claim(self):
        sh("git", "checkout", "-q", "-b", "proto/G-001-search", cwd=self.a)   # 브랜치는 있지만 착수 줄이 없다
        m = self.write_mr(self.a, "G-001", "`app/calc.js`")
        r = self.ho("scope", "G-001", "--mr", m, cwd=self.a)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("착수", r.stdout + r.stderr)

    def test_peer_precheck_shows_scope(self):
        self.alice_claims_and_scopes()
        sh("git", "pull", "-q", cwd=self.b)
        r = self.ho("precheck", cwd=self.b)
        self.assertIn("범위: app/calc.js, app/ui.js", r.stdout)

    def test_peer_overlap_blocks_until_acknowledged(self):
        self.alice_claims_and_scopes()
        r = self.ho("claim", "G-002", "화면 정리", "proto/G-002-ui", cwd=self.b)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        m = self.write_mr(self.b, "G-002", "`app/calc.js`, `app/other.js`")
        r = self.mc(m, "draft", self.b)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("@alice", r.stdout)
        self.assertIn("app/calc.js", r.stdout)
        self.assertIn("겹침 확인", r.stdout)
        m = self.write_mr(self.b, "G-002", "`app/calc.js`, `app/other.js`",
                          risk="- 위험: 없음\n- 겹침 확인: G-001 — calc는 alice가 머지한 뒤 리베이스하고 함수 추가만")
        r = self.mc(m, "draft", self.b)
        self.assertNotIn("@alice", r.stdout)

    def test_peer_without_overlap_passes(self):
        self.alice_claims_and_scopes()
        self.ho("claim", "G-002", "화면 정리", "proto/G-002-ui", cwd=self.b)
        m = self.write_mr(self.b, "G-002", "`app/other.js`")
        r = self.mc(m, "draft", self.b)
        self.assertNotIn("겹침 확인", r.stdout)

    def test_peer_changed_file_overlap_also_blocks(self):
        # 설계에 없던 파일을 실제로 고쳐도 겹침으로 본다
        self.alice_claims_and_scopes()
        self.ho("claim", "G-002", "화면 정리", "proto/G-002-ui", cwd=self.b)
        write(self.b, "app/ui.js", "// bob\n", "a")
        m = self.write_mr(self.b, "G-002", "`app/other.js`")
        r = self.mc(m, "draft", self.b)
        self.assertIn("app/ui.js", r.stdout)
        self.assertIn("겹침 확인", r.stdout)

    def scope_problems(self, d, m, stage):
        code = ("import sys; sys.path.insert(0, r'%s'); import mr_check, vf_git; "
                "t = open(r'%s', encoding='utf-8').read(); print('\\n'.join(mr_check.scope_problems(t, '%s', vf_git.config())))"
                % (SCRIPTS, m, stage))
        return subprocess.run([PY, "-c", code], cwd=d, capture_output=True, text=True, encoding="utf-8",
                              env=dict(os.environ, PYTHONIOENCODING="utf-8"))

    def test_own_build_needs_published_scope(self):
        r = self.ho("claim", "G-001", "거래처 검색", "proto/G-001-search", cwd=self.a)
        m = self.write_mr(self.a, "G-001", "`app/calc.js`")
        out = self.scope_problems(self.a, m, "build")
        self.assertIn("handoff.py scope", out.stdout + out.stderr)
        self.ho("scope", "G-001", "--mr", m, cwd=self.a)
        out = self.scope_problems(self.a, m, "build")
        self.assertEqual(out.stdout.strip(), "", out.stdout + out.stderr)

    def test_own_design_growth_needs_rescope(self):
        self.alice_claims_and_scopes("`app/calc.js`")
        m = self.write_mr(self.a, "G-001", "`app/calc.js`, `app/ui.js`")
        out = self.scope_problems(self.a, m, "build")
        self.assertIn("app/ui.js", out.stdout)

    def test_own_changed_file_outside_scope_blocks_review(self):
        self.alice_claims_and_scopes("`app/calc.js`")
        write(self.a, "app/other.js", "// alice\n", "a")
        m = f".vibe/mr-G-001.md"
        out = self.scope_problems(self.a, m, "review")
        self.assertIn("app/other.js", out.stdout)
        self.assertEqual(self.scope_problems(self.a, m, "build").stdout.strip(), "")   # build는 설계 파일만

    def test_unpushed_scope_is_not_published(self):
        r = self.ho("claim", "G-001", "거래처 검색", "proto/G-001-search", cwd=self.a)
        m = self.write_mr(self.a, "G-001", "`app/calc.js`")
        self.ho("scope", "G-001", "--mr", m, "--no-push", cwd=self.a)
        out = self.scope_problems(self.a, m, "build")
        self.assertIn("push", out.stdout)


if __name__ == "__main__":
    unittest.main()
