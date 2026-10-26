"""Minimal async GitHub REST client (httpx). The token comes from the environment only."""

from __future__ import annotations

import os

import httpx

from .aggregator import format_comment, format_summary
from .schemas import ReviewResult
from .sources import SourceError, safe_relpath


class GitHubClient:
    def __init__(
        self,
        token: str | None = None,
        base_url: str = "https://api.github.com",
        client: httpx.AsyncClient | None = None,
    ):
        token = token or os.environ.get("GITHUB_TOKEN")
        if not token:
            raise ValueError("GITHUB_TOKEN is required")
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=30)
        self._headers = {
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def get_pr(self, repo: str, number: int) -> dict:
        r = await self._client.get(
            f"/repos/{repo}/pulls/{number}",
            headers={**self._headers, "Accept": "application/vnd.github+json"},
        )
        r.raise_for_status()
        return r.json()

    async def get_pr_diff(self, repo: str, number: int) -> str:
        r = await self._client.get(
            f"/repos/{repo}/pulls/{number}",
            headers={**self._headers, "Accept": "application/vnd.github.v3.diff"},
        )
        r.raise_for_status()
        return r.text

    async def get_file(self, repo: str, path: str, ref: str) -> str:
        r = await self._client.get(
            f"/repos/{repo}/contents/{safe_relpath(path)}",
            params={"ref": ref},
            headers={**self._headers, "Accept": "application/vnd.github.raw+json"},
        )
        if r.status_code == 404:
            raise SourceError(f"file not found: {path}")
        r.raise_for_status()
        return r.text

    async def post_review(
        self, repo: str, number: int, commit_id: str, result: ReviewResult
    ) -> dict:
        comments = [
            {"path": f.file, "line": f.line, "side": "RIGHT", "body": format_comment(f)}
            for f in result.findings
        ]
        r = await self._client.post(
            f"/repos/{repo}/pulls/{number}/reviews",
            headers={**self._headers, "Accept": "application/vnd.github+json"},
            json={
                "commit_id": commit_id,
                "body": format_summary(result),
                "event": "COMMENT",
                "comments": comments,
            },
        )
        r.raise_for_status()
        return r.json()

    async def aclose(self) -> None:
        await self._client.aclose()
