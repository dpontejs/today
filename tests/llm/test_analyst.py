import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from today.llm.analyst import AnalystError, AnthropicApiAnalyst, ClaudeCliAnalyst, make_analyst

FAKE = Path(__file__).parent / "fake_claude.py"


class Out(BaseModel):
    word: str
    n: int


def cli(tmp_path: Path, mode: str, **kwargs) -> tuple[ClaudeCliAnalyst, Path]:
    dump = tmp_path / "dump.json"
    return ClaudeCliAnalyst(command=(sys.executable, str(FAKE), str(dump), mode), **kwargs), dump


def call(analyst) -> Out:
    return analyst.complete(model="sonnet", system="Você avalia.", prompt="a vaga", schema=Out)


def test_claude_cli_builds_args_and_env_without_app_secrets(tmp_path, monkeypatch):
    for name in ("SESSION_SECRET", "GEMINI_API_KEY", "DB_PATH", "API_TOKEN"):
        monkeypatch.setenv(name, "secret")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth")
    analyst, dump = cli(tmp_path, "ok")

    call(analyst)

    seen = json.loads(dump.read_text())
    args = seen["args"]
    assert args[:5] == ["-p", "--output-format", "json", "--model", "sonnet"]
    assert json.loads(args[args.index("--json-schema") + 1]) == Out.model_json_schema()
    assert args[args.index("--system-prompt") + 1] == "Você avalia."
    assert args[args.index("--tools") + 1] == ""
    assert "--no-session-persistence" in args and "--bare" not in args
    assert seen["stdin"] == "a vaga"
    assert Path(seen["cwd"]).name.startswith("today-claude-")
    env = seen["env"]
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "oauth"
    for name in ("SESSION_SECRET", "GEMINI_API_KEY", "DB_PATH", "API_TOKEN"):
        assert name not in env
    assert set(env) <= {"HOME", "PATH", "LANG", "CLAUDE_CODE_OAUTH_TOKEN", "LC_CTYPE", "PWD"}


def test_claude_cli_returns_validated_model(tmp_path):
    analyst, _ = cli(tmp_path, "ok")
    assert call(analyst) == Out(word="olá", n=3)


def test_claude_cli_missing_structured_output_is_error(tmp_path):
    analyst, _ = cli(tmp_path, "no_structured")
    with pytest.raises(AnalystError, match="structured_output"):
        call(analyst)


def test_claude_cli_is_error_result_is_error(tmp_path):
    analyst, _ = cli(tmp_path, "is_error")
    with pytest.raises(AnalystError, match="usage limit"):
        call(analyst)


def test_claude_cli_timeout_is_error(tmp_path):
    analyst, _ = cli(tmp_path, "sleep", timeout_s=0.5)
    with pytest.raises(AnalystError, match="timed out"):
        call(analyst)


def test_claude_cli_missing_binary_is_error(tmp_path):
    with pytest.raises(AnalystError, match="No such file"):
        call(ClaudeCliAnalyst(command=(str(tmp_path / "no-claude"),)))


class FakeMessages:
    def __init__(self, tool_input: dict | None) -> None:
        self.tool_input = tool_input
        self.kwargs: dict = {}

    def create(self, **kwargs):
        self.kwargs = kwargs
        blocks = [SimpleNamespace(type="text", text="ok")]
        if self.tool_input is not None:
            blocks.append(SimpleNamespace(type="tool_use", name="answer", input=self.tool_input))
        return SimpleNamespace(content=blocks, stop_reason="tool_use")


def test_anthropic_api_parses_tool_input():
    messages = FakeMessages({"word": "olá", "n": 3})
    analyst = AnthropicApiAnalyst(SimpleNamespace(messages=messages))

    assert call(analyst) == Out(word="olá", n=3)
    sent = messages.kwargs
    assert sent["model"] == "claude-sonnet-5-5" and sent["system"] == "Você avalia."
    assert sent["messages"] == [{"role": "user", "content": "a vaga"}]
    (tool,) = sent["tools"]
    assert tool["name"] == "answer" and tool["input_schema"] == Out.model_json_schema()
    assert sent["tool_choice"] == {"type": "tool", "name": "answer"}


def test_anthropic_api_invalid_answer_is_error():
    analyst = AnthropicApiAnalyst(SimpleNamespace(messages=FakeMessages({"word": 1})))
    with pytest.raises(AnalystError):
        call(analyst)
    analyst = AnthropicApiAnalyst(SimpleNamespace(messages=FakeMessages(None)))
    with pytest.raises(AnalystError):
        call(analyst)


def test_make_analyst_off_when_unset(settings):
    assert make_analyst(settings) is None


def test_make_analyst_picks_implementation(settings, monkeypatch):
    from dataclasses import replace

    assert isinstance(make_analyst(replace(settings, analyst="claude_cli")), ClaudeCliAnalyst)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert isinstance(make_analyst(replace(settings, analyst="anthropic_api")), AnthropicApiAnalyst)


def test_settings_analyst_env(monkeypatch):
    from today.config import load_settings

    monkeypatch.setenv("PASSPHRASE_HASH", "x")
    monkeypatch.setenv("SESSION_SECRET", "y")
    for name in ("ANALYST", "ANALYST_MODEL", "JOBS_PUSH_SCORE", "ANALYZE_LIMIT"):
        monkeypatch.delenv(name, raising=False)
    off = load_settings()
    assert (off.analyst, off.analyst_model, off.jobs_push_score, off.analyze_limit) == (
        None,
        "sonnet",
        75,
        40,  # every-other-day collections (2026-11-26)
    )

    monkeypatch.setenv("ANALYST", "claude_cli")
    monkeypatch.setenv("JOBS_PUSH_SCORE", "80")
    monkeypatch.setenv("ANALYZE_LIMIT", "5")
    on = load_settings()
    assert (on.analyst, on.jobs_push_score, on.analyze_limit) == ("claude_cli", 80, 5)
    monkeypatch.setenv("ANALYST", "gpt")
    with pytest.raises(RuntimeError, match="ANALYST"):
        load_settings()


def test_claude_cli_systemic_errors_are_unavailable(tmp_path):
    from today.llm.analyst import AnalystUnavailable

    with pytest.raises(AnalystUnavailable):
        call(cli(tmp_path, "is_error")[0])
    with pytest.raises(AnalystUnavailable):
        call(ClaudeCliAnalyst(command=(str(tmp_path / "no-claude"),)))
    not_executable = tmp_path / "claude"
    not_executable.write_text("#!/bin/sh\n")
    with pytest.raises(AnalystUnavailable):
        call(ClaudeCliAnalyst(command=(str(not_executable),)))


def test_claude_cli_job_errors_are_not_unavailable(tmp_path):
    from today.llm.analyst import AnalystUnavailable

    for mode in ("no_structured", "sleep"):
        analyst, _ = cli(tmp_path, mode, timeout_s=0.5)
        with pytest.raises(AnalystError) as err:
            call(analyst)
        assert not isinstance(err.value, AnalystUnavailable)


def test_anthropic_api_maps_cli_aliases_to_api_ids():
    messages = FakeMessages({"word": "olá", "n": 3})
    analyst = AnthropicApiAnalyst(SimpleNamespace(messages=messages))
    for alias, model_id in (
        ("sonnet", "claude-sonnet-5-5"),
        ("opus", "claude-opus-5-5"),
        ("haiku", "claude-haiku-5-5"),
    ):
        analyst.complete(model=alias, system="s", prompt="p", schema=Out)
        assert messages.kwargs["model"] == model_id
    analyst.complete(model="claude-sonnet-5-5", system="s", prompt="p", schema=Out)
    assert messages.kwargs["model"] == "claude-sonnet-5-5"


def test_anthropic_api_outage_is_unavailable():
    from today.llm.analyst import AnalystUnavailable

    class Boom:
        def create(self, **kwargs):
            raise ConnectionError("down")

    with pytest.raises(AnalystUnavailable):
        call(AnthropicApiAnalyst(SimpleNamespace(messages=Boom())))
