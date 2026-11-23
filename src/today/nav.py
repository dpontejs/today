"""The app's sections, declared once. Every page gets them through a Jinja context processor.

Routine sections live in the bottom bar (phone) and the top of the sidebar (desktop). Career sections go
under MORE on the phone and in a second group on the sidebar; while there are none, MORE is not rendered.
A new feature adds one `Section(..., group="career")` to `SECTIONS`.
"""

from dataclasses import dataclass
from typing import Literal

from fastapi import Request


@dataclass(frozen=True)
class Section:
    key: str
    path: str
    label_key: str
    group: Literal["routine", "career"]
    # Other paths that render this section's page, e.g. the Today page re-rendered by a failed POST /items.
    also: tuple[str, ...] = ()


SECTIONS: list[Section] = [
    Section(key="today", path="/", label_key="tab_today", group="routine", also=("/items",)),
    Section(key="calendar", path="/calendar", label_key="tab_calendar", group="routine"),
    Section(key="notes", path="/notes", label_key="tab_notes", group="routine"),
]


def _matches(prefix: str, path: str) -> bool:
    if prefix == "/":  # the root is a prefix of everything; only the exact path counts
        return path == "/"
    return path == prefix or path.startswith(prefix + "/")


def is_active(section: Section, path: str) -> bool:
    return any(_matches(p, path) for p in (section.path, *section.also))


def nav_context(request: Request) -> dict:
    """Jinja context processor: sections split by group, each paired with whether it is the current page."""
    path = request.url.path
    entries = [(s, is_active(s, path)) for s in SECTIONS]
    return {
        "nav_routine": [e for e in entries if e[0].group == "routine"],
        "nav_career": [e for e in entries if e[0].group == "career"],
    }
