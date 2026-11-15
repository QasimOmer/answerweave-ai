"""
Shared test setup.

Every test runs against a throwaway SQLite database and a fixed signing secret,
so the suite never touches production data or calls a real LLM.
The environment must be set *before* `app` is imported, which is why this
happens at module level here.
"""
import os
import sys
import tempfile
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_TMP = tempfile.mkdtemp(prefix="hibot-tests-")
os.environ["DB_PATH"] = os.path.join(_TMP, "test.db")
os.environ["AW_AUTH_SECRET"] = "test-secret-not-for-production"
# Blank (not delete) these: app/db.py fills in any variable that is *missing* from
# .env.local, which holds the production DATABASE_URL. An empty value blocks that.
for var in ("DATABASE_URL", "POSTGRES_URL", "VERCEL", "AWS_LAMBDA_FUNCTION_NAME",
            "AW_ALLOW_PRIVATE_URLS", "AW_BLOCK_PRIVATE_URLS", "RESEND_API_KEY", "RESEND_FROM",
            "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "CRON_SECRET",
            "GEMINI_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY",
            "SILICONFLOW_API_KEY", "QWEN_API_KEY", "OPENROUTER_API_KEY"):
    os.environ[var] = ""

import pytest  # noqa: E402

from app import db as _db  # noqa: E402

# Hard stop: never run the suite against anything but the throwaway SQLite file.
if _db.USE_POSTGRES or os.path.abspath(_db.DB_PATH) != os.path.abspath(os.environ["DB_PATH"]):
    raise RuntimeError(f"Refusing to run tests: database is not the temporary test DB ({_db.DB_PATH}).")


@pytest.fixture(scope="session")
def app():
    from app.main import app as fastapi_app
    return fastapi_app


@pytest.fixture()
def client(app):
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def new_user(client):
    """Signs up a brand-new user and returns (email, password, token)."""
    email = f"qa-{uuid.uuid4().hex[:10]}@example.com"
    password = "correct-horse-battery"
    r = client.post("/api/auth/signup", json={"email": email, "password": password, "name": "QA Bot"})
    assert r.status_code == 200, r.text
    return email, password, r.json()["token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
