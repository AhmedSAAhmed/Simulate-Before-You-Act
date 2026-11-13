from fastapi.testclient import TestClient

from sba.config import clean_value, normalize_db_url
from sba.main import app
from sba.ui.sections import systems


def test_healthz() -> None:
    resp = TestClient(app).get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_ui_is_mounted_at_root() -> None:
    resp = TestClient(app).get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_clean_value_strips_straight_and_curly_quotes() -> None:
    assert clean_value('  "abc" ') == "abc"
    assert clean_value("“abc”") == "abc"


def test_neon_url_uses_psycopg3_driver() -> None:
    assert normalize_db_url("postgresql://u:p@h/db").startswith("postgresql+psycopg://")
    assert normalize_db_url("sqlite:///x.db") == "sqlite:///x.db"


def test_systems_section_escapes_names() -> None:
    html = systems({"<script>": False})
    assert "<script>" not in html
    assert "not configured" in html
