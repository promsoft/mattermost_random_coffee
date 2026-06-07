from fastapi.testclient import TestClient

from coffeebot.http_app import create_app


class RecordingHandlers:
    def __init__(self):
        self.calls = []

    def on_action(self, user_id, username, action):
        self.calls.append((user_id, username, action))


def make_client():
    handlers = RecordingHandlers()
    app = create_app(handlers, "s3cret")
    return TestClient(app), handlers


def payload(action="register"):
    return {"user_id": "mm1", "user_name": "ivan", "context": {"action": action}}


def test_valid_secret_dispatches_action():
    client, handlers = make_client()
    resp = client.post("/actions/s3cret", json=payload())
    assert resp.status_code == 200
    assert handlers.calls == [("mm1", "ivan", "register")]


def test_wrong_secret_403():
    client, handlers = make_client()
    resp = client.post("/actions/wrong", json=payload())
    assert resp.status_code == 403
    assert handlers.calls == []


def test_missing_action_400():
    client, _ = make_client()
    resp = client.post("/actions/s3cret", json={"user_id": "mm1", "context": {}})
    assert resp.status_code == 400


def test_healthz():
    client, _ = make_client()
    assert client.get("/healthz").json() == {"status": "ok"}
