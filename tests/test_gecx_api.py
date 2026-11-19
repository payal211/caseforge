import os
import tempfile

os.environ["LLM_MODE"] = "mock"
os.environ["CASEFORGE_DATA"] = tempfile.mkdtemp(prefix="cf-gecx-api-test-")

from fastapi.testclient import TestClient  # noqa: E402

from caseforge.api.main import app  # noqa: E402

client = TestClient(app)


def test_customer_assistant_session_requires_a_demo_account():
    assert client.post("/cx/assistant/sessions", json={"account_id": "not-an-account"}).status_code == 404


def test_customer_assistant_session_is_created_for_known_demo_account():
    response = client.post("/cx/assistant/sessions", json={"account_id": "ACC-1001"})

    assert response.status_code == 200
    assert response.json()["session_id"]


def test_customer_assistant_rejects_unknown_session_and_oversized_message():
    assert client.post(
        "/cx/assistant/sessions/unknown/messages",
        json={"text": "Hello"},
    ).status_code == 404

    session_id = client.post(
        "/cx/assistant/sessions",
        json={"account_id": "ACC-1001"},
    ).json()["session_id"]
    response = client.post(
        f"/cx/assistant/sessions/{session_id}/messages",
        json={"text": "x" * 2001},
    )
    assert response.status_code == 422
