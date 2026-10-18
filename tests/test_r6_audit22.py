"""22·23차 감사(A22-02·A22-03·A23) 회귀 시험. 실행: python -m unittest tests/test_r6_audit22.py -v"""
import contextlib
import io
import json
import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_r5_review import R5  # noqa: E402


class Quiet(R5):
    def miss(self, stage):
        with contextlib.redirect_stdout(io.StringIO()):
            return super().miss(stage)

    def body(self):
        with open("mr.md", encoding="utf-8") as f:
            return f.read()


class RehearsalTrustTest(Quiet):
    """A22-02: 리허설 여부는 커밋된 설정이 아니라 실행 환경(VF_REHEARSAL=1)에서만 온다."""

    def setUp(self):
        super().setUp()
        self.write("docs/DECISIONS.md", "# 결정\n\n## D-002 G-001 정렬\n- 시뮬레이션 사용자 결정(E2E)\n- 정렬 기준: 이름순\n")
        self.mr()
        body = re.sub(r"^- 위험:(.*)$", lambda m: m.group(0) + "\n- 미확인: 정렬 기준\n- 정책 결정: D-002 — 정렬 기준",
                      self.body(), count=1, flags=re.M)
        self.write("mr.md", body)

    def sim(self):
        return any(x.startswith("SIMULATED-DECISION") for x in self.miss("merge"))

    def test_committed_config_does_not_open(self):
        cfg = json.loads(open(".vibe-flow.json", encoding="utf-8").read())
        cfg["rehearsal"] = True
        self.write(".vibe-flow.json", json.dumps(cfg))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VF_REHEARSAL", None)
            self.assertTrue(self.sim())

    def test_env_opens(self):
        with mock.patch.dict(os.environ, {"VF_REHEARSAL": "1"}):
            self.assertFalse(self.sim())


class DeletedTestFileTest(unittest.TestCase):
    """A22-03: 지운 테스트 파일도 '바뀐 테스트 파일'이다."""

    def test_deleted_counts(self):
        import mr_check
        with mock.patch.object(mr_check.vf_git, "base_tree", return_value="b"), \
             mock.patch.object(mr_check.vf_git, "snapshot", return_value="c"), \
             mock.patch.object(mr_check.vf_git, "git", return_value="M\tsrc/app.py\nD\ttests/test_deleted.py\nD\tlib/foo_test.go\n"), \
             mock.patch.object(mr_check, "_test_files", return_value=[]):
            got = mr_check.changed_test_files({"base": "main"})
        self.assertIn("tests/test_deleted.py", got)
        self.assertIn("lib/foo_test.go", got)
        self.assertNotIn("src/app.py", got)


class ApprovalDecisionSimulatedTest(unittest.TestCase):
    """23차: RED 대체 승인 '(승인 D-nnn)'도 MR이 근거로 쓴 결정 — 시뮬레이션 검사 대상."""

    def test_ids(self):
        import mr_check
        self.assertIn("D-004", mr_check.mr_decision_ids("## QA 결과\n- RED 대체: 동작 불변 — test_x (승인 D-004)\n"))


if __name__ == "__main__":
    unittest.main()
