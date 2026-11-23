"""Stands in for `claude`: `fake_claude.py <dump.json> <mode> [claude args...]`.

Writes its claude args, env, cwd and stdin to <dump.json>, then answers like `claude -p --output-format json`
according to <mode>: ok | no_structured | is_error | sleep."""

import json
import os
import sys
import time

dump, mode, *args = sys.argv[1:]
stdin = sys.stdin.read()
with open(dump, "w") as f:
    json.dump({"args": args, "env": dict(os.environ), "cwd": os.getcwd(), "stdin": stdin}, f)

if mode == "sleep":
    time.sleep(10)
result = {"type": "result", "subtype": "success", "is_error": False, "result": "{}"}
if mode == "ok":
    result["structured_output"] = {"word": "olá", "n": 3}
elif mode == "is_error":
    result.update(is_error=True, subtype="error_during_execution", result="Claude usage limit reached")
print(json.dumps(result))
