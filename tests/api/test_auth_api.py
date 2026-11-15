"""Sign-up, sign-in, sessions and route protection, through the real HTTP API."""
import base64
import json
import uuid

import pytest

from tests.conftest import auth


def test_signup_returns_working_token(client, new_user):
    email, _, token = new_user
    me = client.get("/api/auth/me", headers=auth(token))
    assert me.status_code == 200
    assert me.json()["email"] == email
    assert "password_hash" not in me.json()


def test_signup_creates_a_workspace(client, new_user):
    _, _, token = new_user
    assert client.get("/api/auth/me", headers=auth(token)).json()["workspaces"], "new users need a workspace"


@pytest.mark.parametrize("payload,message", [
    ({"email": "a@example.com", "password": "short", "name": "x"}, "at least 8"),
    ({"email": "not-an-email", "password": "long-enough-1", "name": "x"}, "valid email"),
])
def test_signup_validation(client, payload, message):
    r = client.post("/api/auth/signup", json=payload)
    assert r.status_code == 400
    assert message in r.json()["detail"]


def test_duplicate_email_rejected(client, new_user):
    email, password, _ = new_user
    r = client.post("/api/auth/signup", json={"email": email, "password": password, "name": "Again"})
    assert r.status_code == 400
    assert "already exists" in r.json()["detail"]


def test_login(client, new_user):
    email, password, _ = new_user
    assert client.post("/api/auth/login", json={"email": email, "password": password}).status_code == 200
    bad = client.post("/api/auth/login", json={"email": email, "password": "wrong-password"})
    assert bad.status_code == 401
    unknown = client.post("/api/auth/login", json={"email": f"nobody-{uuid.uuid4().hex}@example.com", "password": password})
    assert unknown.status_code == 401
    assert bad.json()["detail"] == unknown.json()["detail"], "must not reveal which emails have accounts"


@pytest.mark.parametrize("path", ["/api/auth/me", "/api/assistants", "/api/leads", "/api/settings"])
def test_private_routes_need_a_token(client, path):
    assert client.get(path).status_code == 401


def test_garbage_and_tampered_tokens_rejected(client, new_user):
    _, _, token = new_user
    body, sig = token.split(".", 1)
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    payload["uid"] = "someone-else"
    forged = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode() + "." + sig
    for bad in ("garbage", forged, token[:-2] + "xx"):
        assert client.get("/api/auth/me", headers=auth(bad)).status_code == 401


def test_changing_password_signs_out_old_sessions(client, new_user):
    email, password, old_token = new_user
    r = client.post("/api/auth/change-password", headers=auth(old_token),
                    json={"current_password": password, "new_password": "a-brand-new-password"})
    assert r.status_code == 200
    assert client.get("/api/auth/me", headers=auth(old_token)).status_code == 401
    assert client.get("/api/auth/me", headers=auth(r.json()["token"])).status_code == 200
    assert client.post("/api/auth/login", json={"email": email, "password": password}).status_code == 401


def test_change_password_requires_current_password(client, new_user):
    _, _, token = new_user
    r = client.post("/api/auth/change-password", headers=auth(token),
                    json={"current_password": "not-it", "new_password": "a-brand-new-password"})
    assert r.status_code == 400


def test_forgot_password_does_not_reveal_accounts(client, new_user):
    email, _, _ = new_user
    known = client.post("/api/auth/forgot-password", json={"email": email}).json()
    unknown = client.post("/api/auth/forgot-password", json={"email": "ghost@example.com"}).json()
    assert known == unknown
