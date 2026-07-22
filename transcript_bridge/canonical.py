"""Canonical intermediate envelope and JSONL helpers."""
import json
from datetime import datetime, timezone


def make_turn(role, content, *, tool_calls=None, tool_results=None,
                provider=None, model=None, ts=None, _meta=None):
    if _meta is None:
        _meta = {"loss": [], "source": {}}
    return {
        "role": role,
        "content": content,
        "tool_calls": tool_calls,
        "tool_results": tool_results,
        "provider": provider,
        "model": model,
        "ts": ts or datetime.now(timezone.utc).isoformat(),
        "_meta": _meta,
    }


def read_jsonl(text):
    turns = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        turns.append(json.loads(line))
    return turns


def write_jsonl(turns):
    lines = []
    for turn in turns:
        lines.append(json.dumps(turn, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(lines) + "\n" if lines else ""


def _selfcheck():
    now = "2026-07-22T00:00:00+00:00"
    t = make_turn(role="user", content="hello", provider="anthropic", ts=now)
    assert t["role"] == "user"
    assert t["content"] == "hello"
    assert t["provider"] == "anthropic"
    assert t["ts"] == now
    assert t["_meta"] == {"loss": [], "source": {}}

    text = write_jsonl([t])
    turns = read_jsonl(text)
    assert turns == [t]
    print("canonical selfcheck OK")


if __name__ == "__main__":
    _selfcheck()
