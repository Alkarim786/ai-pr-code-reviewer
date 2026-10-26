"""End-to-end with the real analysers (ruff/bandit) and a scripted LLM."""

import difflib
from pathlib import Path

from reviewer.llm import FakeLLM, tool_use
from reviewer.orchestrator import review_diff
from reviewer.sources import LocalSource

OLD = 'import sqlite3\n\n\ndef conn():\n    return sqlite3.connect("x")\n'
NEW = OLD + "\n\ndef find(name):\n    return conn().execute(f\"SELECT * FROM t WHERE n = '{name}'\")\n"


def make(tmp_path):
    (tmp_path / "svc.py").write_text(NEW, encoding="utf-8")
    d = "".join(difflib.unified_diff(OLD.splitlines(True), NEW.splitlines(True), "a/svc.py", "b/svc.py"))
    return "diff --git a/svc.py b/svc.py\n" + d


async def test_static_only_finds_sqli(tmp_path):
    res = await review_diff(make(tmp_path), LocalSource(tmp_path), None)
    assert any(f.rule in {"B608", "S608"} and f.line == 9 for f in res.findings)


async def test_static_plus_llm_merge_and_grounding(tmp_path):
    def script(agent, turn, messages):
        if agent != "security":
            return None
        return [
            tool_use(
                "s",
                "submit_findings",
                findings=[
                    {"file": "svc.py", "line": 9, "severity": "critical", "category": "security",
                     "message": "SQL injection", "suggestion": "parameterise"},
                    {"file": "svc.py", "line": 500, "severity": "high", "category": "security",
                     "message": "hallucinated"},
                ],
            )
        ]

    res = await review_diff(make(tmp_path), LocalSource(tmp_path), FakeLLM(script))
    top = res.findings[0]
    assert top.line == 9 and top.source == "static+llm" and top.suggestion == "parameterise"
    assert top.severity.value == "critical"
    assert res.dropped_out_of_diff == 1 and res.merged_duplicates >= 1


async def test_one_failing_agent_does_not_kill_review(tmp_path):
    def script(agent, turn, messages):
        if agent == "bug":
            raise RuntimeError("model exploded")
        return None

    res = await review_diff(make(tmp_path), LocalSource(tmp_path), FakeLLM(script))
    assert len(res.agent_errors) == 1 and "bug" in res.agent_errors[0]
    assert res.findings  # static findings survive


async def test_token_budget_enforced(tmp_path):
    class Greedy(FakeLLM):
        async def complete(self, system, messages, tools):
            r = await super().complete(system, messages, tools)
            r.input_tokens = 1000
            return r

    llm = Greedy(lambda a, t, m: [tool_use(f"x{t}", "search_repo", pattern="a")])
    res = await review_diff(make(tmp_path), LocalSource(tmp_path), llm, token_budget=2500)
    assert len(res.agent_errors) == 4 and "budget" in res.agent_errors[0]


async def test_empty_diff():
    res = await review_diff("", LocalSource(Path(".")), None)
    assert res.findings == []
