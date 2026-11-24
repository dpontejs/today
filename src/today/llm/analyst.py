"""One port for structured LLM calls (ADR 0007): `Analyst.complete(...) -> schema instance`.

`ClaudeCliAnalyst` runs `claude -p` on the owner's subscription in an empty temp dir with a minimal env;
`AnthropicApiAnalyst` uses the API with the schema as the only, forced tool. Both raise `AnalystError` for
anything that is not a valid answer, so callers retry later. `AnalystUnavailable` (a subclass) means the
analyst itself is down — login, usage limit, missing binary, API outage — and says nothing about the job:
callers stop the batch without charging the job's retry budget."""

import json
import os
import subprocess
import tempfile
from typing import Protocol

from pydantic import BaseModel, ValidationError

# Only what the CLI needs; app secrets (SESSION_SECRET, GEMINI_API_KEY, API_TOKEN, ...) never reach it.
CLI_ENV = ("HOME", "PATH", "LANG", "CLAUDE_CODE_OAUTH_TOKEN")
TOOL_NAME = "answer"
# Claude Code aliases (ANALYST_MODEL default "sonnet") mapped to Messages API ids for AnthropicApiAnalyst.
API_MODELS = {"sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5", "haiku": "claude-haiku-5-5"}
# An is_error result about this answer, not about the account: counts against the job.
JOB_ERROR_SUBTYPES = ("error_max_structured_output_retries",)


class AnalystError(Exception):
    """The model gave no valid answer for this job this time."""


class AnalystUnavailable(AnalystError):
    """The analyst cannot answer anything right now (login, limit, outage): not the job's fault."""


class Analyst(Protocol):
    def complete[T: BaseModel](self, *, model: str, system: str, prompt: str, schema: type[T]) -> T: ...


def _validate[T: BaseModel](schema: type[T], data: object) -> T:
    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        raise AnalystError(f"answer does not match {schema.__name__}: {exc}") from exc


class ClaudeCliAnalyst:
    def __init__(self, command: tuple[str, ...] = ("claude",), timeout_s: float = 300) -> None:
        self.command = command
        self.timeout_s = timeout_s

    def complete[T: BaseModel](self, *, model: str, system: str, prompt: str, schema: type[T]) -> T:
        # Never --bare: it ignores CLAUDE_CODE_OAUTH_TOKEN.
        args = [
            *self.command,
            "-p",
            "--output-format",
            "json",
            "--model",
            model,
            "--json-schema",
            json.dumps(schema.model_json_schema()),
            "--system-prompt",
            system,
            "--tools",
            "",
            "--no-session-persistence",
        ]
        env = {k: os.environ[k] for k in CLI_ENV if k in os.environ}
        with tempfile.TemporaryDirectory(prefix="today-claude-") as cwd:
            try:
                done = subprocess.run(
                    args,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    cwd=cwd,
                    env=env,
                    timeout=self.timeout_s,
                )
            except subprocess.TimeoutExpired as exc:
                raise AnalystError(f"claude timed out after {self.timeout_s:g} s") from exc
            except OSError as exc:  # not found, not executable
                raise AnalystUnavailable(f"claude command not runnable: {self.command[0]}: {exc}") from exc
        try:
            result = json.loads(done.stdout)
        except ValueError as exc:
            detail = (done.stderr or done.stdout).strip()[:300]
            error = AnalystUnavailable if done.returncode else AnalystError
            raise error(f"claude exited {done.returncode} without JSON: {detail}") from exc
        if not isinstance(result, dict):
            raise AnalystError("claude answered JSON that is not an object")
        if result.get("is_error"):
            error = AnalystError if result.get("subtype") in JOB_ERROR_SUBTYPES else AnalystUnavailable
            raise error(f"claude error ({result.get('subtype')}): {str(result.get('result'))[:300]}")
        if result.get("structured_output") is None:
            raise AnalystError("claude answered without structured_output")
        return _validate(schema, result["structured_output"])


class AnthropicApiAnalyst:
    def __init__(self, client, max_tokens: int = 4096) -> None:
        self.client = client
        self.max_tokens = max_tokens

    def complete[T: BaseModel](self, *, model: str, system: str, prompt: str, schema: type[T]) -> T:
        try:
            message = self.client.messages.create(
                model=API_MODELS.get(model, model),
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                tools=[
                    {
                        "name": TOOL_NAME,
                        "description": f"Record the answer as {schema.__name__}.",
                        "input_schema": schema.model_json_schema(),
                    }
                ],
                tool_choice={"type": "tool", "name": TOOL_NAME},
            )
        except Exception as exc:
            # 400: this request was bad (counts against the job); anything else is auth, limit or outage.
            error = AnalystError if getattr(exc, "status_code", None) == 400 else AnalystUnavailable
            raise error(f"anthropic api: {exc}") from exc
        for block in message.content:
            if getattr(block, "type", None) == "tool_use" and block.name == TOOL_NAME:
                return _validate(schema, block.input)
        raise AnalystError(f"anthropic api gave no tool call (stop_reason={message.stop_reason})")


def make_analyst(settings) -> Analyst | None:
    """`ANALYST` unset → None (analysis off)."""
    if settings.analyst == "claude_cli":
        return ClaudeCliAnalyst()
    if settings.analyst == "anthropic_api":
        import anthropic

        return AnthropicApiAnalyst(anthropic.Anthropic())  # reads ANTHROPIC_API_KEY
    return None
