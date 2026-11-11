"""English and Brazilian Portuguese UI strings, picked per request.

The language comes from the `today_lang` cookie (set by the PT/EN switch) or, failing that, from the browser's
`Accept-Language`. Day and month names live here instead of `strftime("%A")`, which depends on the locales
installed in the container.
"""

from datetime import date, datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

LANGS = ("en", "pt")
DEFAULT_LANG = "en"
HTML_LANG = {"en": "en", "pt": "pt-BR"}
LANG_COOKIE = "today_lang"
LANG_COOKIE_MAX_AGE = 365 * 24 * 3600

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "badge_today": "TODAY",
        "sign_out": "SIGN OUT",
        "section_late": "LATE",
        "section_today": "TODAY",
        "section_next": "NEXT {n} DAYS",
        "pill_late": "LATE",
        "pill_next": "NEXT",
        "status_on_time": "ON TIME",
        "status_done": "DONE",
        "empty_today": "Nothing else today.",
        "empty_week": "Clear week.",
        "label_what": "What",
        "label_when": "When",
        "placeholder_title": "review chapter 3",
        "add": "ADD",
        "mark_done": "Mark {title} as finished",
        "reopen": "Reopen {title}",
        "error_title_required": "Title is required.",
        "error_title_too_long": "Title is too long (200 characters max).",
        "error_pick_date": "Pick a date and time.",
        "sign_in_title": "Sign in",
        "passphrase": "PASSPHRASE",
        "sign_in": "SIGN IN",
        "error_wrong_passphrase": "Wrong passphrase.",
        "error_too_many_attempts": "Too many attempts. Try again in a few minutes.",
        "capture_label": "What should I remind you of?",
        "capture_placeholder": "exam on the 20th, call the bank tomorrow 9am",
        "capture_send": "Send",
        "mic_hold": "Hold to talk",
        "mic_recording": "Recording… release to send.",
        "mic_understanding": "Understanding…",
        "mic_too_short": "Hold the button while you talk.",
        "mic_denied": "Microphone blocked. Allow it in Settings › Safari › Microphone.",
        "review_title": "CHECK AND CREATE",
        "reminders_label": "REMINDERS",
        "no_reminders": "No reminders.",
        "confirm": "CREATE",
        "discard": "DISCARD",
        "manual": "ADD MANUALLY",
        "capture_failed": "Couldn't understand that. Try again or add it manually.",
        "capture_empty": "Type or say something first.",
        "capture_nothing": "Didn't find anything to remind you of.",
        "capture_audio_too_large": "Recording too long. Keep it under a minute.",
        "capture_not_audio": "That file is not audio.",
        "tab_today": "TODAY",
        "tab_calendar": "CALENDAR",
        "tabs_label": "Sections",
        "show_more": "SHOW MORE ({n})",
        "days_choice": "Show the next {n} days",
        "prev_month": "Previous month",
        "next_month": "Next month",
        "month_items": "{n} ITEMS",
        "pick_day": "Tap a day to see its items.",
        "day_empty": "Nothing on this day.",
        "legend_items": "ITEMS",
        "legend_late": "LATE",
        "legend_today": "TODAY",
        "push_devices_one": "Notifications on · 1 device",
        "push_devices_many": "Notifications on · {n} devices",
        "push_last": "last sent {time}",
        "push_off": "No device gets notifications yet.",
        "push_enable": "TURN ON NOTIFICATIONS",
        "push_test": "SEND TEST",
        "push_test_sent": "Sent to {n} device(s).",
        "push_test_none": "No device has notifications on.",
        "push_error": "A delivery failed recently. If nothing arrives, turn notifications on again.",
        "push_install_hint": (
            "On iPhone, add the app to the Home Screen (Share › Add to Home Screen) to get notifications."
        ),
        "push_denied": "Notifications are blocked. Allow them in Settings › Notifications › today.",
        "switch_lang": "PT",
        "switch_lang_label": "Ver em português",
    },
    "pt": {
        "badge_today": "HOJE",
        "sign_out": "SAIR",
        "section_late": "ATRASADOS",
        "section_today": "HOJE",
        "section_next": "PRÓXIMOS {n} DIAS",
        "pill_late": "ATRASADO",
        "pill_next": "PRÓXIMO",
        "status_on_time": "NO HORÁRIO",
        "status_done": "FEITO",
        "empty_today": "Nada mais hoje.",
        "empty_week": "Semana livre.",
        "label_what": "O quê",
        "label_when": "Quando",
        "placeholder_title": "revisar o capítulo 3",
        "add": "CRIAR",
        "mark_done": "Marcar {title} como feito",
        "reopen": "Reabrir {title}",
        "error_title_required": "O título é obrigatório.",
        "error_title_too_long": "O título é longo demais (máximo de 200 caracteres).",
        "error_pick_date": "Escolha data e hora.",
        "sign_in_title": "Entrar",
        "passphrase": "SENHA",
        "sign_in": "ENTRAR",
        "error_wrong_passphrase": "Senha incorreta.",
        "error_too_many_attempts": "Muitas tentativas. Tente de novo em alguns minutos.",
        "capture_label": "Do que devo te lembrar?",
        "capture_placeholder": "prova dia 20, ligar pro banco amanhã às 9",
        "capture_send": "Enviar",
        "mic_hold": "Segure para falar",
        "mic_recording": "Gravando… solte para enviar.",
        "mic_understanding": "Entendendo…",
        "mic_too_short": "Segure o botão enquanto fala.",
        "mic_denied": "Microfone bloqueado. Libere em Ajustes › Safari › Microfone.",
        "review_title": "CONFIRA E CRIE",
        "reminders_label": "LEMBRETES",
        "no_reminders": "Sem lembretes.",
        "confirm": "CRIAR",
        "discard": "DESCARTAR",
        "manual": "ADICIONAR MANUALMENTE",
        "capture_failed": "Não entendi. Tente de novo ou adicione manualmente.",
        "capture_empty": "Digite ou fale algo primeiro.",
        "capture_nothing": "Não encontrei nada para lembrar.",
        "capture_audio_too_large": "Gravação longa demais. Fale em menos de um minuto.",
        "capture_not_audio": "Esse arquivo não é áudio.",
        "tab_today": "HOJE",
        "tab_calendar": "CALENDÁRIO",
        "tabs_label": "Seções",
        "show_more": "VER MAIS ({n})",
        "days_choice": "Mostrar os próximos {n} dias",
        "prev_month": "Mês anterior",
        "next_month": "Próximo mês",
        "month_items": "{n} ITENS",
        "pick_day": "Toque num dia para ver os itens.",
        "day_empty": "Nada neste dia.",
        "legend_items": "ITENS",
        "legend_late": "ATRASADO",
        "legend_today": "HOJE",
        "push_devices_one": "Notificações ativas · 1 aparelho",
        "push_devices_many": "Notificações ativas · {n} aparelhos",
        "push_last": "último envio {time}",
        "push_off": "Nenhum aparelho recebe notificações ainda.",
        "push_enable": "Ativar notificações",
        "push_test": "ENVIAR TESTE",
        "push_test_sent": "Enviado para {n} aparelho(s).",
        "push_test_none": "Nenhum aparelho com notificações ativas.",
        "push_error": "Um envio falhou há pouco. Se nada chegar, ative as notificações de novo.",
        "push_install_hint": (
            "No iPhone, adicione o app à Tela de Início (Compartilhar › Adicionar à Tela de Início) "
            "para receber notificações."
        ),
        "push_denied": "Notificações bloqueadas. Libere em Ajustes › Notificações › today.",
        "switch_lang": "EN",
        "switch_lang_label": "View in English",
    },
}

WEEKDAYS_LONG = {
    "en": ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"],
    "pt": ["SEGUNDA", "TERÇA", "QUARTA", "QUINTA", "SEXTA", "SÁBADO", "DOMINGO"],
}
WEEKDAYS_SHORT = {
    "en": ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"],
    "pt": ["SEG", "TER", "QUA", "QUI", "SEX", "SÁB", "DOM"],
}
MONTHS_LONG = {
    "en": [
        "JANUARY",
        "FEBRUARY",
        "MARCH",
        "APRIL",
        "MAY",
        "JUNE",
        "JULY",
        "AUGUST",
        "SEPTEMBER",
        "OCTOBER",
        "NOVEMBER",
        "DECEMBER",
    ],
    "pt": [
        "JANEIRO",
        "FEVEREIRO",
        "MARÇO",
        "ABRIL",
        "MAIO",
        "JUNHO",
        "JULHO",
        "AGOSTO",
        "SETEMBRO",
        "OUTUBRO",
        "NOVEMBRO",
        "DEZEMBRO",
    ],
}
MONTHS_SHORT = {
    "en": ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"],
    "pt": ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"],
}


def pick_lang(cookie: str | None, accept_language: str | None) -> str:
    """Cookie first; else the supported language with the highest `q` in Accept-Language; else English."""
    if cookie in LANGS:
        return cookie
    best, best_q = DEFAULT_LANG, -1.0
    for part in (accept_language or "").split(","):
        tag, _, params = part.strip().partition(";")
        primary = tag.split("-")[0].strip().lower()
        if primary not in LANGS:
            continue
        q = 1.0
        if params.strip().startswith("q="):
            try:
                q = float(params.strip()[2:])
            except ValueError:
                continue
        if q > best_q:
            best, best_q = primary, q
    return best


def weekday_long(dt: datetime, lang: str) -> str:
    return WEEKDAYS_LONG[lang][dt.weekday()]


def month_short(dt: datetime, lang: str) -> str:
    return MONTHS_SHORT[lang][dt.month - 1]


def month_long(d: date, lang: str) -> str:
    return MONTHS_LONG[lang][d.month - 1]


def weekday_short(d: date, lang: str) -> str:
    return WEEKDAYS_SHORT[lang][d.weekday()]


def day_label(dt: datetime, lang: str) -> str:
    return f"{WEEKDAYS_SHORT[lang][dt.weekday()]} {dt.day:02d}"


def request_lang(request: Request) -> str:
    return pick_lang(request.cookies.get(LANG_COOKIE), request.headers.get("accept-language"))


def i18n_context(request: Request) -> dict:
    """Jinja context processor: `t(key, **fields)`, the language, and date helpers in the user's zone."""
    lang = request_lang(request)
    tz: ZoneInfo = request.app.state.settings.tz
    strings = STRINGS[lang]

    def t(key: str, **fields: str) -> str:
        return strings[key].format(**fields) if fields else strings[key]

    return {
        "t": t,
        "lang": lang,
        "html_lang": HTML_LANG[lang],
        "weekday_long": lambda dt: weekday_long(dt.astimezone(tz), lang),
        "month_short": lambda dt: month_short(dt.astimezone(tz), lang),
        "day_label": lambda dt: day_label(dt.astimezone(tz), lang),
        "month_long": lambda d: month_long(d, lang),
        "weekday_short": lambda d: weekday_short(d, lang),
        "weekday_headers": WEEKDAYS_SHORT[lang],
        "date_heading": lambda d: f"{weekday_short(d, lang)} {d.day:02d} {MONTHS_SHORT[lang][d.month - 1]}",
    }


router = APIRouter()


@router.get("/lang/{code}")
def switch_lang(request: Request, code: str) -> RedirectResponse:
    if code not in LANGS:
        raise HTTPException(status_code=404)
    # Go back to the page the switch was clicked on, but only on this site (no open redirect).
    referer = urlsplit(request.headers.get("referer", ""))
    same_site = referer.netloc == request.url.netloc and referer.path.startswith("/")
    target = referer.path + (f"?{referer.query}" if referer.query else "") if same_site else "/"
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        LANG_COOKIE,
        code,
        max_age=LANG_COOKIE_MAX_AGE,
        httponly=True,
        secure=request.app.state.settings.cookie_secure,
        samesite="lax",
    )
    return response
