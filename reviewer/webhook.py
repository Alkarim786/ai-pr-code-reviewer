"""FastAPI webhook receiver for `pull_request` events (HMAC-verified)."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections.abc import Awaitable, Callable

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request

HANDLED_ACTIONS = {"opened", "synchronize", "reopened", "ready_for_review"}

ReviewFn = Callable[[str, int], Awaitable[None]]


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


def create_app(review_fn: ReviewFn, secret: str | None = None) -> FastAPI:
    """`review_fn(repo_full_name, pr_number)` is run in the background per event."""
    app = FastAPI(title="ai-pr-code-reviewer")
    secret = secret if secret is not None else os.environ.get("GITHUB_WEBHOOK_SECRET", "")

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    @app.post("/webhook", status_code=202)
    async def webhook(
        request: Request,
        background: BackgroundTasks,
        x_hub_signature_256: str | None = Header(default=None),
        x_github_event: str | None = Header(default=None),
    ) -> dict:
        body = await request.body()
        if not secret or not verify_signature(secret, body, x_hub_signature_256):
            raise HTTPException(status_code=401, detail="invalid signature")
        if x_github_event == "ping":
            return {"status": "pong"}
        if x_github_event != "pull_request":
            return {"status": "ignored", "event": x_github_event}
        payload = json.loads(body)
        pr = payload.get("pull_request", {})
        if payload.get("action") not in HANDLED_ACTIONS or pr.get("draft"):
            return {"status": "ignored", "action": payload.get("action")}
        background.add_task(review_fn, payload["repository"]["full_name"], pr["number"])
        return {"status": "queued"}

    return app


def default_app() -> FastAPI:  # `uvicorn reviewer.webhook:default_app --factory`
    from .github_client import GitHubClient
    from .llm import AnthropicLLM
    from .pr_review import review_github_pr

    gh = GitHubClient()
    llm = AnthropicLLM()

    async def run(repo: str, number: int) -> None:
        await review_github_pr(gh, repo, number, llm, post=True)

    return create_app(run)
