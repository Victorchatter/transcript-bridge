"""Claude Code JSONL reader/writer."""
import json
from datetime import datetime, timezone

from ..canonical import make_turn
from ..loss import make_loss


def read_claude_code_jsonl(text):
    turns = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        if record.get("type") not in ("user", "assistant", "system", "tool"):
            continue
        message = record.get("message", {})
        content = message.get("content")
        tool_use_blocks = _tool_use_blocks(content)
        tool_result_blocks = _tool_result_blocks(content)
        turns.append(make_turn(
            role=message.get("role", record.get("type")),
            content=content,
            tool_calls=tool_use_blocks,
            tool_results=tool_result_blocks,
            provider=record.get("provider", "anthropic"),
            model=message.get("model") or record.get("model"),
            ts=record.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            _meta={"loss": [], "source": record},
        ))
    return turns


def _tool_use_blocks(content):
    if not isinstance(content, list):
        return None
    blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
    return blocks or None


def _tool_result_blocks(content):
    if not isinstance(content, list):
        return None
    results = []
    for b in content:
        if isinstance(b, dict) and b.get("type") == "tool_result":
            results.append({
                "tool_use_id": b.get("tool_use_id"),
                "content": b.get("content"),
            })
    return results or None


def write_claude_code_jsonl(turns):
    losses = []
    lines = []
    for turn in turns:
        content = turn.get("content")
        # cache_control is preserved verbatim in Claude Code JSONL output, so
        # no loss is reported here. Other formats report the loss when they drop
        # it.
        record = {
            "type": turn["role"],
            "message": {
                "role": turn["role"],
                "content": content,
            },
            "timestamp": turn.get("ts"),
        }
        if turn.get("provider"):
            record["provider"] = turn["provider"]
        if turn.get("model"):
            record["message"]["model"] = turn["model"]
        # Report source-format-specific fields that have no Claude Code home.
        source = (turn.get("_meta") or {}).get("source", {})
        if source.get("_openai_name"):
            losses.append(make_loss(
                path="_meta.source._openai_name",
                source_format=turn.get("provider", "openai_messages"),
                target_format="claude_code_jsonl",
                reason="Claude Code JSONL has no slot for the OpenAI tool message name field",
                value=source["_openai_name"],
            ))
        lines.append(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(lines) + "\n" if lines else "", losses


def _selfcheck():
    sample = json.dumps({
        "type": "assistant",
        "message": {
            "role": "assistant",
            "model": "claude-sonnet-4",
            "content": [
                {"type": "text", "text": "I'll read that."},
                {"type": "tool_use", "id": "tu_1", "name": "Read", "input": {"file_path": "/x"}},
            ],
        },
        "timestamp": "2026-07-22T12:00:00Z",
    }, separators=(",", ":"))
    turns = read_claude_code_jsonl(sample)
    assert len(turns) == 1
    assert turns[0]["role"] == "assistant"
    assert turns[0]["content"][1]["type"] == "tool_use"

    out, losses = write_claude_code_jsonl(turns)
    assert json.loads(out)["message"]["content"][1]["type"] == "tool_use"
    print("claude_code selfcheck OK")


if __name__ == "__main__":
    _selfcheck()
