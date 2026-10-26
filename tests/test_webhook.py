import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from reviewer.webhook import create_app, verify_signature

SECRET = "s3cret"


async def _noop(repo, n):
    return None


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def post(client, payload, event="pull_request", sig=True):
    body = json.dumps(payload).encode()
    headers = {"X-GitHub-Event": event, "Content-Type": "application/json"}
    if sig:
        headers["X-Hub-Signature-256"] = sign(body)
    return client.post("/webhook", content=body, headers=headers)


def test_verify_signature():
    body = b"{}"
    assert verify_signature(SECRET, body, sign(body))
    assert not verify_signature(SECRET, body, "sha256=deadbeef")
    assert not verify_signature(SECRET, body, None)


def test_rejects_unsigned_and_wrong_signature():
    c = TestClient(create_app(_noop, secret=SECRET))
    assert post(c, {}, sig=False).status_code == 401
    bad = c.post("/webhook", content=b"{}", headers={"X-Hub-Signature-256": "sha256=00"})
    assert bad.status_code == 401


def test_refuses_all_requests_when_no_secret_configured():
    c = TestClient(create_app(_noop, secret=""))
    assert post(c, {}).status_code == 401


def test_dispatches_opened_pr():
    calls = []

    async def fn(repo, n):
        calls.append((repo, n))

    c = TestClient(create_app(fn, secret=SECRET))
    r = post(c, {"action": "opened", "pull_request": {"number": 5}, "repository": {"full_name": "o/r"}})
    assert r.status_code == 202 and r.json()["status"] == "queued"
    assert calls == [("o/r", 5)]


def test_ignores_other_actions_drafts_and_events():
    calls = []

    async def fn(repo, n):
        calls.append(1)

    c = TestClient(create_app(fn, secret=SECRET))
    repo = {"full_name": "o/r"}
    post(c, {"action": "closed", "pull_request": {"number": 1}, "repository": repo})
    post(c, {"action": "opened", "pull_request": {"number": 1, "draft": True}, "repository": repo})
    assert post(c, {}, event="push").json()["status"] == "ignored"
    assert post(c, {}, event="ping").json()["status"] == "pong"
    assert not calls
