"""Public surface: pages, the embeddable widget and the chat endpoint's input checks."""
import pytest


@pytest.mark.parametrize("path,needle", [
    ("/", "Hi Bot"),
    ("/dashboard", "Hi Bot"),
    ("/demo", "Hi Bot"),
])
def test_pages_render(client, path, needle):
    r = client.get(path)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert needle in r.text


def test_widget_script_is_served_and_not_stale(client):
    r = client.get("/widget.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert "no-cache" in r.headers.get("cache-control", ""), "site owners must get widget fixes without a hard refresh"
    assert "attachShadow" in r.text, "widget must render in Shadow DOM so host-site CSS can't break it"


def test_chat_requires_assistant_id(client):
    r = client.post("/api/chat", json={"message": "hello"})
    assert r.status_code == 400


def test_chat_unknown_assistant(client):
    r = client.post("/api/chat", json={"assistant_id": "asst_does_not_exist", "message": "hello"})
    assert r.status_code == 404


def test_chat_rejects_oversized_message(client):
    r = client.post("/api/chat", json={"assistant_id": "x", "message": "a" * 20001})
    assert r.status_code == 422


def test_unknown_conversation_transcript_is_not_an_error_leak(client):
    r = client.get("/api/conversations/conv_not_real/transcript")
    assert r.status_code in (200, 404)
    assert "Traceback" not in r.text
