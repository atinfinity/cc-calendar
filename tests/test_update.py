import io
import json

import pytest
from fastapi.testclient import TestClient

from cc_calendar import update
from cc_calendar.server import create_app


@pytest.mark.parametrize(
    ("latest", "current", "expected"),
    [
        ("0.7.0", "0.6.1", "0.7.0"),
        ("0.6.10", "0.6.9", "0.6.10"),
        ("1.0", "0.9.9", "1.0"),
        ("0.6.1", "0.6.1", None),
        ("0.6.1.0", "0.6.1", None),
        ("0.6.0", "0.6.1", None),
        ("0.7.0rc1", "0.6.1", None),  # pre-releases are not offered
        ("0.7.0", "0+unknown", None),  # not installed as a package
        ("0.7.0", "0.7.0.dev1", None),
        (None, "0.6.1", None),
    ],
)
def test_newer(latest, current, expected):
    assert update.newer(latest, current) == expected


@pytest.mark.parametrize(
    ("value", "off"), [("", False), ("0", False), ("false", False), ("1", True), ("yes", True)]
)
def test_disabled_by_env(monkeypatch, value, off):
    monkeypatch.setenv(update.ENV_OFF, value)
    assert update.disabled_by_env() is off


def test_fetch_latest(monkeypatch):
    seen = {}

    def urlopen(req, timeout):
        seen["url"], seen["agent"] = req.full_url, req.get_header("User-agent")
        return io.BytesIO(json.dumps({"info": {"version": "9.9.9"}}).encode())

    monkeypatch.setattr(update.urllib.request, "urlopen", urlopen)
    assert update.fetch_latest() == "9.9.9"
    assert seen["url"] == update.PYPI_URL
    assert seen["agent"] == f"cc-calendar/{update.__version__}"


def test_fetch_latest_offline(monkeypatch):
    def urlopen(req, timeout):
        raise OSError("no network")

    monkeypatch.setattr(update.urllib.request, "urlopen", urlopen)
    assert update.fetch_latest() is None


def test_sessions_report_update(claude_dir, monkeypatch):
    monkeypatch.setattr(update, "__version__", "0.6.1")
    monkeypatch.setattr(update, "fetch_latest", lambda: "0.7.0")
    app = create_app(claude_dir, watch=False, update_check=True)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        for _ in range(50):  # the check runs in the background
            if c.get("/api/sessions").json()["update"]:
                break
        assert c.get("/api/sessions").json()["update"] == "0.7.0"


def test_no_check_by_default(claude_dir, monkeypatch):
    def fetch():
        raise AssertionError("must not ask PyPI")

    monkeypatch.setattr(update, "fetch_latest", fetch)
    with TestClient(create_app(claude_dir, watch=False), base_url="http://127.0.0.1") as c:
        assert c.get("/api/sessions").json()["update"] is None
