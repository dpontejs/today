"""Natural-language capture: a sentence or a voice note becomes item drafts the user confirms (ADR 0003).

`extract_items` is the only place that knows about Gemini. Routes call whatever is in `app.state.extractor`
(tests put a fake there), clean the suggested reminders, show a review card, and create items on confirm.
"""

import json
from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, TypeAdapter, ValidationError

from today.auth import require_session
from today.i18n import day_label, request_lang
from today.items.reminders import add_reminders, clean_reminders
from today.items.repo import ItemIn, insert_item

MAX_AUDIO_BYTES = 2 * 1024 * 1024
FORM_FORMAT = "%Y-%m-%dT%H:%M"
SOURCE = "capture"
LANGUAGE_NAMES = {"en": "English", "pt": "Brazilian Portuguese"}


class CaptureError(Exception):
    """The model could not be reached or answered something unusable."""


class CaptureDraft(BaseModel):
    title: str
    due_at: str  # "YYYY-MM-DDTHH:MM" in the user's zone
    notes: str | None
    reminders: list[str]


_DRAFTS = TypeAdapter(list[CaptureDraft])


def build_prompt(now: datetime, tz: ZoneInfo, lang: str) -> str:
    local = now.astimezone(tz)
    return f"""You turn a short note (typed or spoken) into reminders for one person.
Now: {local.strftime("%A %Y-%m-%d %H:%M")} in {tz.key}.

Return a JSON array with one object per thing to remember (usually one; [] if there is nothing to remember).
- title: short, in {LANGUAGE_NAMES[lang]}, without the date or time words.
- due_at: when it happens, local time "YYYY-MM-DDTHH:MM". Resolve relative dates ("amanhã", "sexta",
  "dia 20", "next week") from now. If no time is said, use 09:00.
- notes: other details that were said, or null.
- reminders: local times "YYYY-MM-DDTHH:MM" to notify the person.
  * Events with a fixed date (exam, deadline, appointment, meeting, trip): 7 days before at 09:00 when the
    event is 8 or more days away; the day before at 19:00; and 1 hour before due_at.
  * Plain tasks: one reminder at due_at.
  * Never earlier than now, never later than due_at."""


def parse_drafts(raw: str) -> list[CaptureDraft]:
    try:
        return _DRAFTS.validate_python(json.loads(raw))
    except (ValueError, ValidationError) as exc:
        raise CaptureError(f"unusable model output: {exc}") from exc


# Gemini's documented audio types use `audio/m4a` for the MP4/AAC container that iOS reports as `audio/mp4`.
_GEMINI_MIME = {"audio/mp4": "audio/m4a", "audio/x-m4a": "audio/m4a", "audio/aac": "audio/aac"}


def gemini_mime(mime: str | None) -> str:
    base = (mime or "audio/mp4").split(";")[0].strip().lower()
    return _GEMINI_MIME.get(base, base)


class GeminiExtractor:
    """`extract_items` backed by Gemini: one structured-output call, text or audio in."""

    def __init__(self, api_key: str, model: str) -> None:
        from google import (
            genai,
        )  # imported here so the app starts (and tests run) without the SDK's import cost

        self.client = genai.Client(api_key=api_key)
        self.model = model

    def __call__(
        self, text: str | None, audio: bytes | None, mime: str | None, now: datetime, tz: ZoneInfo, lang: str
    ) -> list[CaptureDraft]:
        from google.genai import types

        contents: list = []
        if audio:
            contents += [
                types.Part.from_bytes(data=audio, mime_type=gemini_mime(mime)),
                "This is a voice note.",
            ]
        if text:
            contents.append(text)
        config = types.GenerateContentConfig(
            system_instruction=build_prompt(now, tz, lang),
            response_mime_type="application/json",
            response_schema=list[CaptureDraft],
            temperature=0,
        )
        try:
            response = self.client.models.generate_content(model=self.model, contents=contents, config=config)
        except Exception as exc:  # network, quota, safety block: all mean "try again" to the user
            raise CaptureError(str(exc)) from exc
        return parse_drafts(response.text or "")


# --- routes ----------------------------------------------------------------------------------------

router = APIRouter(dependencies=[Depends(require_session)])


def _extractor(request: Request):
    extractor = request.app.state.extractor
    if extractor is None:
        raise HTTPException(status_code=404)
    return extractor


def _parse_local(value: str, tz: ZoneInfo) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)


def _review(request: Request, status_code: int = 200, **context) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(
        request, "_capture_review.html", {"drafts": [], "error": None, **context}, status_code=status_code
    )


def _card(draft: CaptureDraft, now: datetime, tz: ZoneInfo, lang: str) -> dict | None:
    due = _parse_local(draft.due_at, tz)
    if due is None or not draft.title.strip():
        return None
    times = [t for t in (_parse_local(r, tz) for r in draft.reminders) if t is not None]
    reminders = clean_reminders(times, due_at=due, now=now)
    return {
        "title": draft.title.strip()[:200],
        "due_at": due.astimezone(tz).strftime(FORM_FORMAT),
        "notes": draft.notes,
        "reminders": [
            {
                "value": r.astimezone(tz).strftime(FORM_FORMAT),
                "label": f"{day_label(r.astimezone(tz), lang)} · {r.astimezone(tz):%H:%M}",
            }
            for r in reminders
        ],
    }


@router.post("/capture", response_class=HTMLResponse)
async def capture(
    request: Request,
    text: Annotated[str, Form()] = "",
    audio: UploadFile | None = None,
) -> HTMLResponse:
    extractor = _extractor(request)
    tz: ZoneInfo = request.app.state.settings.tz
    lang = request_lang(request)
    now = request.app.state.clock()

    data: bytes | None = None
    if audio is not None:
        if not (audio.content_type or "").startswith("audio/"):
            return _review(request, 415, error="capture_not_audio")
        data = await audio.read(MAX_AUDIO_BYTES + 1)
        if len(data) > MAX_AUDIO_BYTES:
            return _review(request, 413, error="capture_audio_too_large")
    text = text.strip()
    if not text and not data:
        return _review(request, 422, error="capture_empty")

    try:
        drafts = await run_in_threadpool(
            extractor, text or None, data, audio.content_type if audio else None, now, tz, lang
        )
    except CaptureError:
        return _review(request, error="capture_failed")
    cards = [c for c in (_card(d, now, tz, lang) for d in drafts) if c is not None]
    if not cards:
        return _review(request, error="capture_nothing")
    return _review(request, drafts=cards)


@router.post("/capture/confirm")
async def confirm(request: Request) -> Response:
    tz: ZoneInfo = request.app.state.settings.tz
    now = request.app.state.clock()
    form = await request.form()
    titles, dues, notes = form.getlist("title"), form.getlist("due_at"), form.getlist("notes")
    if not titles or len(titles) != len(dues):
        raise HTTPException(status_code=422)

    items = []
    for i, (title, due_raw) in enumerate(zip(titles, dues, strict=True)):
        due = _parse_local(str(due_raw), tz)
        if due is None:
            raise HTTPException(status_code=422)
        try:
            note = str(notes[i]).strip() if i < len(notes) else ""
            data = ItemIn(title=str(title).strip(), due_at=due, notes=note or None)
        except ValidationError as exc:
            raise HTTPException(status_code=422) from exc
        times = [
            t for t in (_parse_local(str(r), tz) for r in form.getlist(f"reminders-{i}")) if t is not None
        ]
        items.append((data, clean_reminders(times, due_at=due, now=now)))

    conn = request.app.state.conn
    for data, reminders in items:
        item = insert_item(conn, data, now, source=SOURCE)
        assert item is not None
        add_reminders(conn, item.id, reminders)
    return RedirectResponse("/", status_code=303)
