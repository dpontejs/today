"""HTTP side of web push: the public key, (un)subscribing a device and a test notification."""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from today import notify
from today.auth import require_session
from today.i18n import request_lang


def _enabled(request: Request) -> None:
    if request.app.state.push_sender is None:
        raise HTTPException(status_code=404)


router = APIRouter(dependencies=[Depends(require_session), Depends(_enabled)])


class Keys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=200)
    auth: str = Field(min_length=1, max_length=100)


class SubscriptionIn(BaseModel):
    endpoint: str = Field(pattern=r"^https://", max_length=1000)
    keys: Keys


@router.get("/push/key")
def public_key(request: Request) -> JSONResponse:
    return JSONResponse({"public_key": request.app.state.settings.vapid_public_key})


@router.post("/push/subscribe", status_code=204)
def subscribe(request: Request, sub: SubscriptionIn) -> Response:
    notify.save_subscription(
        request.app.state.conn,
        endpoint=sub.endpoint,
        p256dh=sub.keys.p256dh,
        auth=sub.keys.auth,
        lang=request_lang(request),
        now=request.app.state.clock(),
    )
    return Response(status_code=204)


@router.post("/push/unsubscribe", status_code=204)
def unsubscribe(request: Request, endpoint: Annotated[str, Body(embed=True)]) -> Response:
    notify.delete_subscription(request.app.state.conn, endpoint)
    return Response(status_code=204)


@router.post("/push/test", response_class=HTMLResponse)
def test_push(request: Request) -> HTMLResponse:
    conn, now = request.app.state.conn, request.app.state.clock()
    texts = {
        "en": "It works: reminders will look like this.",
        "pt": "Funcionando: os lembretes vão chegar assim.",
    }
    delivered, _ = notify.send_to_all(
        conn,
        now,
        request.app.state.push_sender,
        lambda lang: {"title": "today", "body": texts[lang], "url": "/", "tag": "test"},
    )
    return request.app.state.templates.TemplateResponse(
        request, "_push_status.html", {"push": notify.status(conn), "test_result": delivered}
    )
