"""End-to-end PR review against GitHub: fetch -> review -> (optionally) post."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from .diff import parse_diff
from .github_client import GitHubClient
from .llm import LLM
from .orchestrator import review_diff
from .schemas import ReviewResult
from .sources import DictSource, LocalSource, SourceError


async def review_github_pr(
    gh: GitHubClient,
    repo: str,
    number: int,
    llm: LLM | None,
    *,
    repo_dir: Path | None = None,
    post: bool = False,
    max_comments: int = 20,
) -> ReviewResult:
    """Review a PR.

    With `repo_dir` (the GitHub Action case: PR head already checked out) the tools see
    the whole repo. Without it (webhook case) only the changed files are fetched via the
    contents API at the head SHA and tools are limited to them.
    """
    pr = await gh.get_pr(repo, number)
    head_sha = pr["head"]["sha"]
    diff_text = await gh.get_pr_diff(repo, number)

    if repo_dir is not None:
        result = await review_diff(
            diff_text, LocalSource(repo_dir), llm, max_comments=max_comments
        )
    else:
        changed = [d.path for d in parse_diff(diff_text)]
        files: dict[str, str] = {}
        for p in changed:
            try:
                files[p] = await gh.get_file(repo, p, head_sha)
            except SourceError:
                continue
        with tempfile.TemporaryDirectory() as tmp:
            for p, text in files.items():
                dest = Path(tmp) / p
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(text, encoding="utf-8")
            result = await review_diff(
                diff_text, DictSource(files), llm,
                static_root=Path(tmp), max_comments=max_comments, search_paths=list(files),
            )
    if post:
        await gh.post_review(repo, number, head_sha, result)
    return result


def run_sync(coro):  # small helper for the CLI
    return asyncio.run(coro)
