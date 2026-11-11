"""English and Brazilian Portuguese UI strings, picked per request.

The language comes from the `today_lang` cookie (set by the PT/EN switch) or, failing that, from the browser's
`Accept-Language`. Day and month names live here instead of `strftime("%A")`, which depends on the locales
installed in the container.
"""

from datetime import datetime
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
        "section_next": "NEXT 7 DAYS",
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
        "switch_lang": "PT",
        "switch_lang_label": "Ver em português",
    },
    "pt": {
        "badge_today": "HOJE",
        "sign_out": "SAIR",
        "section_late": "ATRASADOS",
        "section_today": "HOJE",
        "section_next": "PRÓXIMOS 7 DIAS",
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
