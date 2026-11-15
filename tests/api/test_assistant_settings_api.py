"""Assistant settings saved from the dashboard must actually persist."""
import pytest

from tests.conftest import auth


@pytest.fixture()
def assistant(client, new_user):
    _, _, token = new_user
    r = client.post("/api/assistants", headers=auth(token), json={"name": "QA Site", "domain": "qa.example.com"})
    assert r.status_code == 200, r.text
    body = r.json()
    asst_id = body.get("assistant_id") or body.get("id") or (body.get("assistant") or {}).get("id")
    assert asst_id, body
    return token, asst_id


@pytest.mark.parametrize("freq", ["weekly", "daily", "off"])
def test_recrawl_schedule_persists(client, assistant, freq):
    token, asst_id = assistant
    r = client.patch(f"/api/assistants/{asst_id}", headers=auth(token),
                     json={"recrawl_frequency": freq, "crawl_max_pages": 100})
    assert r.status_code == 200, r.text
    assert r.json()["assistant"]["recrawl_frequency"] == freq
    fresh = client.get(f"/api/assistants/{asst_id}", headers=auth(token)).json()
    assert fresh["recrawl_frequency"] == freq
    assert fresh["crawl_max_pages"] == 100


def test_invalid_recrawl_schedule_falls_back_to_off(client, assistant):
    token, asst_id = assistant
    r = client.patch(f"/api/assistants/{asst_id}", headers=auth(token), json={"recrawl_frequency": "hourly"})
    assert r.status_code == 200
    assert r.json()["assistant"]["recrawl_frequency"] == "off"
