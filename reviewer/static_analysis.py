"""Static analysis runner (ruff + bandit). Never imports or executes the reviewed code.

Findings are handed to the LLM agents as *evidence* so they explain and prioritise
instead of guessing, and the aggregator uses agreement between static and LLM
findings as a ranking signal.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from .schemas import Category, Finding, Severity

RUFF_SELECT = "F,B,S,PERF,E7,E9,ASYNC"
RUFF_IGNORE = "S101"

_BANDIT_SEV = {"HIGH": Severity.high, "MEDIUM": Severity.medium, "LOW": Severity.low}


def _ruff_category(code: str) -> Category:
    if code.startswith("S"):
        return Category.security
    if code.startswith(("PERF", "ASYNC")):
        return Category.performance
    return Category.bug


def _ruff_severity(code: str) -> Severity:
    if code in {"F821", "F822", "F823", "E902"} or code.startswith("E9"):
        return Severity.high
    if code.startswith(("F", "B")):
        return Severity.medium
    return Severity.low


def _rel(path: str, root: Path) -> str:
    p = Path(path)
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def _run(cmd: list[str], cwd: Path, timeout: int) -> str:
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell, analysers only parse files
        cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
    )
    return proc.stdout


def run_ruff(root: Path, files: list[str], timeout: int = 60) -> list[Finding]:
    cmd = [
        sys.executable, "-m", "ruff", "check", "--output-format", "json", "--no-cache",
        "--isolated", "--select", RUFF_SELECT, "--ignore", RUFF_IGNORE, *files,
    ]
    out = _run(cmd, root, timeout)
    findings: list[Finding] = []
    for item in json.loads(out or "[]"):
        code = item["code"] or "E999"
        findings.append(
            Finding(
                file=_rel(item["filename"], root),
                line=max(1, item["location"]["row"]),
                severity=_ruff_severity(code),
                category=_ruff_category(code),
                message=f"[ruff {code}] {item['message']}",
                source="static",
                rule=code,
            )
        )
    return findings


def run_bandit(root: Path, files: list[str], timeout: int = 60) -> list[Finding]:
    cmd = [sys.executable, "-m", "bandit", "-f", "json", "-q", *files]
    out = _run(cmd, root, timeout)
    if not out.strip():
        return []
    findings: list[Finding] = []
    for item in json.loads(out).get("results", []):
        findings.append(
            Finding(
                file=_rel(item["filename"], root),
                line=max(1, item["line_number"]),
                severity=_BANDIT_SEV.get(item["issue_severity"], Severity.low),
                category=Category.security,
                message=f"[bandit {item['test_id']}] {item['issue_text']}",
                source="static",
                rule=item["test_id"],
            )
        )
    return findings


def run_static(root: Path, paths: list[str]) -> list[Finding]:
    """Run all analysers on the Python files among `paths` (repo-relative)."""
    py = [p for p in paths if p.endswith(".py") and (root / p).is_file()]
    if not py:
        return []
    return run_ruff(root, py) + run_bandit(root, py)
