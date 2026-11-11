import sqlite3
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from conftest import PASSPHRASE
from fastapi.testclient import TestClient

from today.app import create_app
from today.capture import CaptureDraft, CaptureError, build_prompt, gemini_mime, parse_drafts
from today.config import Settings
from today.items.reminders import list_reminders

TZ = ZoneInfo("America/Fortaleza")
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)  # Tue 10 Nov 2026, 09:00 in Fortaleza
PT = {"Accept-Language": "pt-BR"}

EXAM = CaptureDraft(
    title="Prova de Sistemas Distribuídos",
    due_at="2026-11-20T09:00",
    notes=None,
    reminders=["2026-11-13T09:00", "2026-11-19T19:00", "2026-11-20T08:00", "2026-11-01T09:00"],
)


class FakeExtractor:
    def __init__(self, result: list[CaptureDraft] | Exception) -> None:
        self.result = result
        self.calls: list[dict] = []

    def __call__(self, text, audio, mime, now, tz, lang):
        self.calls.append({"text": text, "audio": audio, "mime": mime, "now": now, "tz": tz, "lang": lang})
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


# --- prompt and parsing ----------------------------------------------------------------------------


def test_build_prompt_states_now_zone_language_and_rules():
    prompt = build_prompt(NOW, TZ, "pt")

    assert "Tuesday 2026-11-10 09:00" in prompt
    assert "America/Fortaleza" in prompt
    assert "Brazilian Portuguese" in prompt
    assert "09:00" in prompt and "19:00" in prompt and "7 days before" in prompt
    assert "Brazilian Portuguese" not in build_prompt(NOW, TZ, "en")


def test_parse_model_json_to_drafts():
    raw = '[{"title": "Ligar pro banco", "due_at": "2026-11-11T09:00", "notes": null, "reminders": []}]'
    assert parse_drafts(raw) == [
        CaptureDraft(title="Ligar pro banco", due_at="2026-11-11T09:00", notes=None, reminders=[])
    ]


@pytest.mark.parametrize("raw", ["not json", '{"title": "x"}', '[{"title": "x"}]'])
def test_parse_bad_model_output_raises(raw):
    with pytest.raises(CaptureError):
        parse_drafts(raw)


# --- routes ----------------------------------------------------------------------------------------


@pytest.fixture
def make_client(settings: Settings):
    def make(extractor) -> TestClient:
        app = create_app(settings)
        app.state.clock = lambda: NOW
        app.state.extractor = extractor
        client = TestClient(app, base_url="https://testserver", follow_redirects=False)
        client.post("/login", data={"passphrase": PASSPHRASE})
        return client

    return make


def test_capture_text_shows_review_card(make_client):
    client = make_client(FakeExtractor([EXAM]))

    html = client.post(
        "/capture", data={"text": "tenho prova dia 20 de Sistemas Distribuídos"}, headers=PT
    ).text

    assert "Prova de Sistemas Distribuídos" in html
    assert 'value="2026-11-20T09:00"' in html
    # past and after-due reminders are dropped; the rest are offered checked, labelled in Portuguese
    assert html.count('type="checkbox"') == 3
    assert "SEX 13 · 09:00" in html and "QUI 19 · 19:00" in html and "SEX 20 · 08:00" in html
    assert "2026-11-01T09:00" not in html


def test_capture_passes_now_tz_and_lang(make_client):
    fake = FakeExtractor([EXAM])
    client = make_client(fake)

    client.post("/capture", data={"text": "prova dia 20"}, headers=PT)

    (call,) = fake.calls
    assert (call["text"], call["audio"], call["now"], call["tz"], call["lang"]) == (
        "prova dia 20",
        None,
        NOW,
        TZ,
        "pt",
    )


def test_capture_audio_passes_bytes_and_mime(make_client):
    fake = FakeExtractor([EXAM])
    client = make_client(fake)

    response = client.post("/capture", files={"audio": ("note.m4a", b"\x00\x01audio", "audio/mp4")})

    assert response.status_code == 200
    assert fake.calls[0]["audio"] == b"\x00\x01audio"
    assert fake.calls[0]["mime"] == "audio/mp4"


def test_capture_rejects_large_audio_413(make_client):
    fake = FakeExtractor([EXAM])
    client = make_client(fake)

    response = client.post("/capture", files={"audio": ("a.m4a", b"0" * (2 * 1024 * 1024 + 1), "audio/mp4")})

    assert response.status_code == 413
    assert fake.calls == []


def test_capture_rejects_non_audio_415(make_client):
    client = make_client(FakeExtractor([EXAM]))
    response = client.post("/capture", files={"audio": ("x.txt", b"hello", "text/plain")})
    assert response.status_code == 415


def test_capture_empty_is_422(make_client):
    fake = FakeExtractor([EXAM])
    client = make_client(fake)

    response = client.post("/capture", data={"text": "   "}, headers=PT)

    assert response.status_code == 422
    assert "Digite ou fale algo primeiro." in response.text
    assert fake.calls == []


def test_capture_model_error_shows_message(make_client):
    client = make_client(FakeExtractor(CaptureError("boom")))

    response = client.post("/capture", data={"text": "x"}, headers=PT)

    assert response.status_code == 200
    assert "Não entendi" in response.text


def test_capture_nothing_found(make_client):
    client = make_client(FakeExtractor([]))
    assert "Não encontrei nada para lembrar." in client.post("/capture", data={"text": "oi"}, headers=PT).text


def test_confirm_creates_item_and_reminders_in_utc(make_client):
    client = make_client(FakeExtractor([]))
    db: sqlite3.Connection = client.app.state.conn

    response = client.post(
        "/capture/confirm",
        data={
            "title": "Prova de Sistemas Distribuídos",
            "due_at": "2026-11-20T09:00",
            "reminders-0": ["2026-11-19T19:00", "2026-11-20T08:00"],
        },
    )

    assert response.status_code == 303
    row = db.execute("SELECT id, title, due_at, source FROM items").fetchone()
    assert (row["title"], row["due_at"], row["source"]) == (
        "Prova de Sistemas Distribuídos",
        "2026-11-20T12:00:00+00:00",
        "capture",
    )
    assert list_reminders(db, row["id"]) == [
        datetime(2026, 11, 19, 22, 0, tzinfo=UTC),
        datetime(2026, 11, 20, 11, 0, tzinfo=UTC),
    ]


def test_confirm_only_checked_reminders(make_client):
    client = make_client(FakeExtractor([]))
    db: sqlite3.Connection = client.app.state.conn

    client.post("/capture/confirm", data={"title": "x", "due_at": "2026-11-20T09:00"})

    assert db.execute("SELECT COUNT(*) FROM reminders").fetchone()[0] == 0


def test_confirm_several_drafts(make_client):
    client = make_client(FakeExtractor([]))
    db: sqlite3.Connection = client.app.state.conn

    client.post(
        "/capture/confirm",
        data={
            "title": ["a", "b"],
            "due_at": ["2026-11-11T09:00", "2026-11-12T09:00"],
            "reminders-1": ["2026-11-11T19:00"],
        },
    )

    rows = db.execute("SELECT id, title FROM items ORDER BY id").fetchall()
    assert [r["title"] for r in rows] == ["a", "b"]
    assert list_reminders(db, rows[0]["id"]) == []
    assert len(list_reminders(db, rows[1]["id"])) == 1


def test_confirm_rejects_bad_input(make_client):
    client = make_client(FakeExtractor([]))
    assert (
        client.post("/capture/confirm", data={"title": "", "due_at": "2026-11-20T09:00"}).status_code == 422
    )
    assert client.post("/capture/confirm", data={"title": "x", "due_at": "nope"}).status_code == 422


def test_capture_requires_session(settings: Settings):
    app = create_app(settings)
    app.state.extractor = FakeExtractor([EXAM])
    anonymous = TestClient(app, base_url="https://testserver", follow_redirects=False)
    assert anonymous.post("/capture", data={"text": "x"}).status_code == 303
    assert anonymous.post("/capture/confirm", data={"title": "x"}).status_code == 303


def test_capture_hidden_without_gemini_key(settings: Settings, make_client):
    client = make_client(None)
    assert client.post("/capture", data={"text": "x"}).status_code == 404
    assert 'action="/capture"' not in client.get("/").text
    assert 'hx-post="/capture"' in make_client(FakeExtractor([])).get("/").text


@pytest.mark.parametrize(
    ("given", "sent"),
    [
        ("audio/mp4", "audio/m4a"),  # iOS Safari's MediaRecorder; Gemini lists the same container as m4a
        ("audio/x-m4a", "audio/m4a"),
        ("audio/webm;codecs=opus", "audio/webm"),
        ("audio/ogg", "audio/ogg"),
        (None, "audio/m4a"),
    ],
)
def test_gemini_mime_maps_ios_recording(given, sent):
    assert gemini_mime(given) == sent
