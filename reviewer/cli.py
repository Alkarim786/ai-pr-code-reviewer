"""CLI.

  python -m reviewer review --diff change.diff --repo . [--static-only] [--json]
  python -m reviewer review-pr --repo-name owner/repo --pr 12 --repo-dir . [--post]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .aggregator import format_comment
from .github_client import GitHubClient
from .orchestrator import review_diff
from .pr_review import review_github_pr, run_sync
from .schemas import ReviewResult
from .sources import LocalSource


def _make_llm(static_only: bool):
    if static_only:
        return None
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set. Set it, or pass --static-only.")
    from .llm import AnthropicLLM

    return AnthropicLLM()


def _print(result: ReviewResult, as_json: bool) -> None:
    if as_json:
        print(result.model_dump_json(indent=2))
        return
    if not result.findings:
        print("No issues found in the changed lines.")
    for f in result.findings:
        print(f"\n{f.file}:{f.line}\n{format_comment(f)}")
    print(
        f"\n-- {len(result.findings)} finding(s); dropped {result.dropped_out_of_diff} "
        f"out-of-diff, merged {result.merged_duplicates} duplicates, "
        f"tokens in/out {result.input_tokens}/{result.output_tokens}"
    )
    for e in result.agent_errors:
        print(f"agent error: {e}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="reviewer")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("review", help="dry-run on a local diff, prints findings")
    r.add_argument("--diff", required=True, help="unified diff file, or - for stdin")
    r.add_argument("--repo", default=".", help="checkout of the PR head")
    r.add_argument("--static-only", action="store_true")
    r.add_argument("--json", action="store_true")
    r.add_argument("--max-comments", type=int, default=int(os.environ.get("MAX_COMMENTS", "20")))

    g = sub.add_parser("review-pr", help="review a GitHub PR (optionally post the review)")
    g.add_argument("--repo-name", required=True, help="owner/repo")
    g.add_argument("--pr", type=int, required=True)
    g.add_argument("--repo-dir", type=Path, help="checkout of the PR head (Action mode)")
    g.add_argument("--post", action="store_true", help="post the review (default: dry run)")
    g.add_argument("--static-only", action="store_true")
    g.add_argument("--json", action="store_true")
    g.add_argument("--max-comments", type=int, default=int(os.environ.get("MAX_COMMENTS", "20")))

    args = p.parse_args(argv)
    llm = _make_llm(args.static_only)

    if args.cmd == "review":
        text = sys.stdin.read() if args.diff == "-" else Path(args.diff).read_text(encoding="utf-8")
        result = run_sync(
            review_diff(text, LocalSource(Path(args.repo)), llm, max_comments=args.max_comments)
        )
    else:
        async def go() -> ReviewResult:
            gh = GitHubClient()
            try:
                return await review_github_pr(
                    gh, args.repo_name, args.pr, llm,
                    repo_dir=args.repo_dir, post=args.post, max_comments=args.max_comments,
                )
            finally:
                await gh.aclose()

        result = run_sync(go())
    _print(result, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
