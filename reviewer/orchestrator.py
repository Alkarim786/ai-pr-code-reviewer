"""Orchestrator: diff -> static analysis -> parallel specialist agents -> aggregate."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from .agents import SPECIALISTS, AgentSpec, run_agent
from .aggregator import aggregate
from .diff import parse_diff
from .llm import LLM
from .schemas import Finding, ReviewResult
from .sources import FileSource, LocalSource
from .static_analysis import run_static
from .tools import ToolBox

DEFAULT_TOKEN_BUDGET = int(os.environ.get("MAX_TOKENS_PER_PR", "400000"))
MAX_FILES = 40  # larger PRs: review the first N files, the rest are listed as skipped


async def review_diff(
    diff_text: str,
    source: FileSource,
    llm: LLM | None,
    *,
    static_root: Path | None = None,
    use_static: bool = True,
    specialists: list[AgentSpec] | None = None,
    max_comments: int = 20,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    search_paths: list[str] | None = None,
) -> ReviewResult:
    """Review a unified diff.

    `llm=None` runs static analysis only. `static_root` is a directory holding the
    PR head's files for the analysers (defaults to the source root when local).
    """
    diffs = parse_diff(diff_text)[:MAX_FILES]
    if not diffs:
        return ReviewResult()
    paths = [d.path for d in diffs]

    static: list[Finding] = []
    if use_static:
        root = static_root or (source.root if isinstance(source, LocalSource) else None)
        if root is not None:
            static = await asyncio.to_thread(run_static, root, paths)

    all_findings = list(static)
    errors: list[str] = []
    invalid = in_tok = out_tok = 0
    if llm is not None:
        toolbox = ToolBox(source, diffs, static, search_paths=search_paths)
        specs = specialists or SPECIALISTS
        outcomes = await asyncio.gather(
            *(run_agent(llm, s, toolbox, diffs, token_budget) for s in specs),
            return_exceptions=True,
        )
        for spec, oc in zip(specs, outcomes, strict=True):
            if isinstance(oc, BaseException):
                errors.append(f"{spec.name}: {type(oc).__name__}: {oc}")
                continue
            all_findings.extend(oc.findings)
            invalid += oc.invalid
            in_tok += oc.input_tokens
            out_tok += oc.output_tokens

    result = aggregate(all_findings, diffs, max_comments=max_comments)
    result.dropped_invalid = invalid
    result.agent_errors = errors
    result.input_tokens, result.output_tokens = in_tok, out_tok
    return result
