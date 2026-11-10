"""Layout rules that only break on real iOS Safari (headless Chromium does not reproduce them)."""

import re
from pathlib import Path

CSS = (Path(__file__).parents[1] / "src/today/static/app.css").read_text()


def rule(selector: str) -> str:
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert match, f"no CSS rule for {selector}"
    return match.group(1)


def test_datetime_input_cannot_overflow_on_ios():
    """iOS gives datetime-local an intrinsic min width ("10 Nov 2026 at 21:00") that ignores width: 100%."""
    body = rule('input[type="datetime-local"]')
    assert "-webkit-appearance: none" in body
    assert "min-width: 0" in body


def test_add_fields_column_can_shrink():
    assert "min-width: 0" in rule(".add-fields")
