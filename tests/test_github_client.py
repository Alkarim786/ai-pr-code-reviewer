import json

import httpx
import pytest
import respx

from reviewer.github_client import GitHubClient
from reviewer.schemas import Finding, ReviewResult
from reviewer.sources import SourceError

BASE = "https://api.github.com"


@pytest.fixture
def gh():
    return GitHubClient(token="t0ken")


@respx.mock
async def test_get_diff_uses_diff_media_type(gh):
    route = respx.get(f"{BASE}/repos/o/r/pulls/7").mock(return_value=httpx.Response(200, text="DIFF"))
    assert await gh.get_pr_diff("o/r", 7) == "DIFF"
    req = route.calls[0].request
    assert req.headers["accept"] == "application/vnd.github.v3.diff"
    assert req.headers["authorization"] == "Bearer t0ken"


@respx.mock
async def test_get_file_404_is_source_error(gh):
    respx.get(f"{BASE}/repos/o/r/contents/a.py").mock(return_value=httpx.Response(404))
    with pytest.raises(SourceError):
        await gh.get_file("o/r", "a.py", "sha")


@respx.mock
async def test_post_review_payload(gh):
    route = respx.post(f"{BASE}/repos/o/r/pulls/7/reviews").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )
    res = ReviewResult(
        findings=[Finding(file="a.py", line=4, severity="high", category="security", message="bad")]
    )
    await gh.post_review("o/r", 7, "abc123", res)
    payload = json.loads(route.calls[0].request.content)
    assert payload["commit_id"] == "abc123" and payload["event"] == "COMMENT"
    c = payload["comments"][0]
    assert c["path"] == "a.py" and c["line"] == 4 and c["side"] == "RIGHT"
    assert "bad" in c["body"]


def test_token_required(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(ValueError):
        GitHubClient()
