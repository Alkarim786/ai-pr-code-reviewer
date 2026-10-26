"""Aggregator: validate locations, dedupe across agents/static, rank, cap, format.

Deliberately deterministic (no LLM): the model proposes, plain code disposes. That makes
the grounding guarantees testable - a comment can only ever land on a line GitHub accepts.
"""

from __future__ import annotations

from .diff import FileDiff
from .schemas import SEVERITY_RANK, Finding, ReviewResult

DEDUP_LINE_WINDOW = 2
STATIC_AGREEMENT_BONUS = 1.5


def validate_locations(findings: list[Finding], diffs: list[FileDiff]) -> tuple[list[Finding], int]:
    visible = {d.path: d.visible_lines for d in diffs}
    kept, dropped = [], 0
    for f in findings:
        if f.line in visible.get(f.file, set()):
            kept.append(f)
        else:
            dropped += 1
    return kept, dropped


def dedupe(findings: list[Finding]) -> tuple[list[Finding], int]:
    """Merge findings in the same file+category within a few lines of each other.

    Keeps the most severe, prefers the LLM wording (it carries the explanation and
    suggestion), and records `static+llm` agreement, which boosts the rank.
    """
    merged: list[Finding] = []
    count = 0
    for f in sorted(findings, key=lambda x: (x.file, x.category.value, x.line)):
        target = next(
            (
                m for m in merged
                if m.file == f.file
                and m.category == f.category
                and abs(m.line - f.line) <= DEDUP_LINE_WINDOW
            ),
            None,
        )
        if target is None:
            merged.append(f.model_copy())
            continue
        count += 1
        sources = set(target.source.split("+")) | set(f.source.split("+"))
        best = f if (f.source == "llm" and target.source == "static") else target
        sev = max(target.severity, f.severity, key=lambda s: SEVERITY_RANK[s])
        idx = merged.index(target)
        merged[idx] = best.model_copy(
            update={
                "severity": sev,
                "source": "+".join(sorted(sources, reverse=True)),
                "suggestion": best.suggestion or target.suggestion or f.suggestion,
                "rule": best.rule or target.rule or f.rule,
            }
        )
    return merged, count


def score(f: Finding) -> float:
    base = float(SEVERITY_RANK[f.severity])
    return base * STATIC_AGREEMENT_BONUS if "static" in f.source and "llm" in f.source else base


def aggregate(
    findings: list[Finding], diffs: list[FileDiff], max_comments: int = 20
) -> ReviewResult:
    kept, out_of_diff = validate_locations(findings, diffs)
    merged, dups = dedupe(kept)
    merged.sort(key=lambda f: (-score(f), f.file, f.line))
    capped = merged[:max_comments]
    return ReviewResult(
        findings=capped,
        dropped_out_of_diff=out_of_diff,
        merged_duplicates=dups,
        dropped_over_cap=len(merged) - len(capped),
    )


_ICON = {"critical": "🛑", "high": "🔴", "medium": "🟠", "low": "🟡", "info": "🔵"}


def format_comment(f: Finding) -> str:
    head = f"{_ICON[f.severity.value]} **{f.severity.value.upper()} · {f.category.value}**"
    if f.source != "llm":
        head += f" · _{f.source}_"
    body = f"{head}\n\n{f.message}"
    if f.suggestion:
        body += f"\n\n**Suggestion:** {f.suggestion}"
    return body


def format_summary(result: ReviewResult) -> str:
    if not result.findings:
        return "### AI review\nNo issues found in the changed lines."
    counts: dict[str, int] = {}
    for f in result.findings:
        counts[f.category.value] = counts.get(f.category.value, 0) + 1
    parts = ", ".join(f"{n} {c}" for c, n in sorted(counts.items()))
    return (
        f"### AI review\n{len(result.findings)} finding(s): {parts}.\n\n"
        f"_{result.dropped_out_of_diff} comment(s) dropped for pointing outside the diff, "
        f"{result.merged_duplicates} duplicate(s) merged._"
    )
