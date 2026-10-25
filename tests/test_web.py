"""HTTP behavior for the shared desk; never calls a paid model or market API."""

import json
from datetime import date, timedelta

import pytest

from tradingagents.web.app import create_app
from tradingagents.web.store import connect, provision_admins


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-never-render")
    app = create_app({"TESTING": True, "DATA_DIR": str(tmp_path), "SECRET_KEY": "test-secret"})
    provision_admins(
        app.config["DATABASE"], [("owner", "Owner-password-123"), ("friend", "Friend-password-123")]
    )
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def post(client, path, data=None):
    client.get("/login")
    with client.session_transaction() as session:
        token = session["csrf"]
    return client.post(path, data={**(data or {}), "csrf": token})


def login(client, username="owner", password="Owner-password-123"):
    return post(client, "/login", {"username": username, "password": password})


def new_run(client, **overrides):
    return post(
        client,
        "/runs",
        {
            "ticker": "AAPL",
            "trade_date": date.today().isoformat(),
            "quick_model": "deepseek/test",
            "deep_model": "z-ai/test",
            "rounds": "1",
            **overrides,
        },
    )


def test_protected_routes(client):
    for path in [
        "/",
        "/new",
        "/settings",
        "/runs/missing",
        "/runs/missing/download",
        "/api/runs/missing",
    ]:
        assert client.get(path).status_code == 302


def test_login_and_logout(client):
    assert login(client).status_code == 302
    assert b"owner" in client.get("/").data
    assert post(client, "/logout").status_code == 302
    assert client.get("/").status_code == 302


def test_csrf_and_bad_credentials(client):
    assert (
        client.post(
            "/login", data={"username": "owner", "password": "Owner-password-123"}
        ).status_code
        == 400
    )
    assert login(client, password="wrong").status_code == 401
    assert client.get("/").status_code == 302
    login(client)
    assert client.post("/runs").status_code == 400
    assert client.post("/logout").status_code == 400


def test_login_throttle(client):
    for _ in range(5):
        assert login(client, password="wrong").status_code == 401
    assert login(client).status_code == 429


def test_exactly_two_admins_and_hashed_passwords(app):
    with connect(app.config["DATABASE"]) as db:
        users = db.execute("SELECT * FROM users").fetchall()
    assert len(users) == 2
    assert all("password-123" not in user["password_hash"] for user in users)
    with pytest.raises(ValueError):
        provision_admins(app.config["DATABASE"], [("third", "long-password-123")])
    with pytest.raises(ValueError):
        provision_admins(
            app.config["DATABASE"], [("same", "long-password-123"), ("same", "long-password-456")]
        )


def test_admins_share_runs(client, app):
    login(client)
    response = new_run(client)
    assert response.status_code == 302
    path = response.headers["Location"]
    post(client, "/logout")
    login(client, "friend", "Friend-password-123")
    page = client.get(path)
    assert page.status_code == 200
    assert b"AAPL" in page.data and b"owner" in page.data
    assert client.get(path.replace("/runs/", "/api/runs/")).json["status"] == "queued"


@pytest.mark.parametrize(
    "override",
    [
        {"ticker": "../../etc/passwd"},
        {"ticker": ""},
        {"trade_date": "invalid"},
        {"trade_date": (date.today() + timedelta(days=2)).isoformat()},
        {"quick_model": ""},
        {"deep_model": "invalid model"},
        {"rounds": "20"},
        {"rounds": "abc"},
    ],
)
def test_bad_inputs_do_not_enqueue(client, app, override):
    login(client)
    assert new_run(client, **override).status_code == 400
    with connect(app.config["DATABASE"]) as db:
        assert db.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_missing_key_does_not_enqueue(client, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    login(client)
    assert new_run(client).status_code == 400


def test_queue_limit(client):
    login(client)
    for _ in range(10):
        assert new_run(client).status_code == 302
    assert new_run(client).status_code == 429


def test_reports_escape_html_and_download(client, app):
    login(client)
    path = new_run(client).headers["Location"]
    run_id = path.rsplit("/", 1)[1]
    report = {"market_report": "# Research\n<script>alert(1)</script>\n[bad](javascript:alert(1))"}
    with connect(app.config["DATABASE"]) as db:
        db.execute(
            "UPDATE runs SET status='completed', signal='Hold', reports=? WHERE id=?",
            (json.dumps(report), run_id),
        )
    html = client.get(path).data
    assert b"<script>alert(1)</script>" not in html
    assert b'href="javascript:' not in html
    assert b"&lt;script&gt;" in html
    download = client.get(path + "/download")
    assert download.status_code == 200
    assert "attachment" in download.headers["Content-Disposition"]
    assert b"Research" in download.data


def test_key_never_rendered_and_security_headers(client):
    login(client)
    for path in ["/", "/settings", "/new"]:
        response = client.get(path)
        assert response.status_code == 200
        assert b"test-key-never-render" not in response.data
        assert response.headers["Cache-Control"] == "no-store"
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_unknown_run(client):
    login(client)
    assert client.get("/runs/nope").status_code == 404


def test_reprovision_invalidates_sessions(client, app):
    login(client)
    provision_admins(
        app.config["DATABASE"], [("owner", "New-password-123"), ("friend", "New-password-456")]
    )
    assert client.get("/").status_code == 302


def test_non_ascii_csrf_is_rejected(client):
    client.get("/login")
    assert client.post("/login", data={"csrf": "é"}).status_code == 400


def test_successful_logins_do_not_trigger_throttle(client):
    for _ in range(6):
        assert login(client).status_code == 302
        assert post(client, "/logout").status_code == 302


def test_sqlite_survives_app_restart(client, app):
    login(client)
    path = new_run(client).headers["Location"]
    restarted = create_app(
        {"TESTING": True, "DATA_DIR": app.config["DATA_DIR"], "SECRET_KEY": "test-secret"}
    )
    second = restarted.test_client()
    login(second, "friend", "Friend-password-123")
    assert b"AAPL" in second.get(path).data


def test_first_start_persists_private_session_secret(tmp_path):
    import stat

    app = create_app({"TESTING": True, "DATA_DIR": str(tmp_path)})
    again = create_app({"TESTING": True, "DATA_DIR": str(tmp_path)})
    assert app.secret_key == again.secret_key
    assert len(app.secret_key) >= 32
    assert stat.S_IMODE((tmp_path / "session.key").stat().st_mode) == 0o600
