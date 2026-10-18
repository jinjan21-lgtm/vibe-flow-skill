"""런 6 진단 평가 C7 감점 처리. 실행: python -m unittest tests/test_r6_c7.py -v

- 시뮬레이션 결정은 운영 merge를 열지 않는다 — 리허설 레포(.vibe-flow.json "rehearsal": true)에서만 REHEARSAL 상태로 통과
- 설계 확인이 CONFIRM이어도 major 지적은 「설계 확인」에 '- 반영: <id> — <어떻게>'(또는 '- 넘김: <id> — 골 후보 <사유>')로 처리해야 build
"""
import contextlib
import io
import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_scripts import seed_design  # noqa: E402
from test_r5_review import R5  # noqa: E402


class Quiet(R5):
    def miss(self, stage):
        with contextlib.redirect_stdout(io.StringIO()):
            return super().miss(stage)

    def body(self):
        with open("mr.md", encoding="utf-8") as f:
            return f.read()


class SimulatedDecisionGateTest(Quiet):
    def setUp(self):
        super().setUp()
        self.write("docs/DECISIONS.md", "# 결정\n\n## D-002 G-001 정렬\n- 시뮬레이션 사용자 결정(E2E)\n- 정렬 기준: 이름순\n")
        self.mr()
        body = re.sub(r"^- 위험:(.*)$", lambda m: m.group(0) + "\n- 미확인: 정렬 기준\n- 정책 결정: D-002 — 정렬 기준",
                      self.body(), count=1, flags=re.M)
        self.write("mr.md", body)

    def test_simulated_blocks_without_rehearsal(self):
        miss = self.miss("merge")
        self.assertTrue(any(x.startswith("SIMULATED-DECISION D-002") for x in miss), miss)

    def test_rehearsal_repo_allows_with_state(self):
        cfg = json.loads(open(".vibe-flow.json", encoding="utf-8").read())
        cfg["rehearsal"] = True
        self.write(".vibe-flow.json", json.dumps(cfg))
        self.assertFalse(any(x.startswith("SIMULATED-DECISION") for x in self.miss("merge")), self.miss("merge"))


class DesignMajorHandledTest(Quiet):
    def test_major_needs_handling_line(self):
        seed_design(extra="FINDING: D1 | major | 테스트 계획 | ADR 테스트 없음 | 추가\n")
        self.mr()
        self.assertTrue(any("설계 확인 major D1" in x for x in self.miss("build")), self.miss("build"))
        body = self.body().replace("- 판정: 확정", "- 반영: D1 — ADR 테스트를 테스트 계획에 넣음\n- 판정: 확정", 1)
        self.write("mr.md", body)
        self.assertFalse(any("설계 확인 major" in x for x in self.miss("build")), self.miss("build"))


if __name__ == "__main__":
    unittest.main()
