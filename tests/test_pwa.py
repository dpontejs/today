import pytest
from fastapi.testclient import TestClient

from today.app import create_app
from today.config import Settings

ICONS = ["icon-180.png", "icon-192.png", "icon-512.png", "icon-maskable-512.png"]


@pytest.fixture
def anonymous(settings: Settings) -> TestClient:
    return TestClient(create_app(settings), base_url="https://testserver", follow_redirects=False)


def test_manifest_public_and_valid(anonymous: TestClient):
    response = anonymous.get("/manifest.webmanifest")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/manifest+json")
    manifest = response.json()
    assert manifest["name"] == "today"
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/"
    assert manifest["background_color"] == manifest["theme_color"] == "#0E0F11"
    sources = {icon["src"] for icon in manifest["icons"]}
    assert {
        "/static/icons/icon-192.png",
        "/static/icons/icon-512.png",
        "/static/icons/icon-maskable-512.png",
    } <= sources
    assert any(icon.get("purpose") == "maskable" for icon in manifest["icons"])


def test_sw_served_at_root_scope(anonymous: TestClient):
    response = anonymous.get("/sw.js")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript") or response.headers[
        "content-type"
    ].startswith("application/javascript")
    assert response.headers["service-worker-allowed"] == "/"
    assert response.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("name", ICONS)
def test_icons_exist(anonymous: TestClient, name: str):
    response = anonymous.get(f"/static/icons/{name}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"


def test_pages_link_pwa_metadata(anonymous: TestClient):
    html = anonymous.get("/login").text
    assert '<link rel="manifest" href="/manifest.webmanifest">' in html
    assert '<link rel="apple-touch-icon" href="/static/icons/icon-180.png">' in html
    assert 'name="apple-mobile-web-app-capable" content="yes"' in html
    assert "navigator.serviceWorker.register('/sw.js')" in html


def test_fonts_are_self_hosted(anonymous: TestClient):
    css = anonymous.get("/static/app.css").text
    assert "fonts.googleapis.com" not in css
    for font in ["barlow-condensed-700.woff2", "jetbrains-mono-400.woff2", "jetbrains-mono-700.woff2"]:
        assert f"/static/fonts/{font}" in css
        assert anonymous.get(f"/static/fonts/{font}").status_code == 200
