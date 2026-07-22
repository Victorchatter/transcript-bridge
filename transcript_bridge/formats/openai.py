"""OpenAI messages reader/writer."""
import json
from datetime import datetime, timezone

from ..canonical import make_turn
from ..loss import make_loss


def read_openai_messages(text):
    messages = json.loads(text)
    if not isinstance(messages, list):
        raise ValueError("openai_messages input must be a JSON array of messages")
    now = datetime.now(timezone.utc).isoformat()
    turns = []
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content")
        tool_calls = None
        tool_results = None
        source = dict(msg)
        if role == "assistant" and msg.get("tool_calls"):
            tool_calls = []
            blocks = []
            if isinstance(content, str) and content:
                blocks.append({"type": "text", "text": content})
            elif isinstance(content, list):
                blocks.extend(content)
            for tc in msg["tool_calls"]:
                tool_calls.append(tc)
                blocks.append({
                    "type": "tool_use",
                    "id": tc.get("id"),
                    "name": tc.get("function", {}).get("name") or tc.get("name"),
                    "input": _parse_args(tc.get("function", {}).get("arguments")),
                })
            content = blocks
        elif role == "tool":
            tool_results = [{
                "tool_use_id": msg.get("tool_call_id"),
                "content": content,
            }]
            content = [{"type": "tool_result", "tool_use_id": msg.get("tool_call_id"), "content": content}]
            if msg.get("name"):
                source["_openai_name"] = msg["name"]
        turns.append(make_turn(
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_results=tool_results,
            provider="openai",
            ts=now,
            _meta={"loss": [], "source": source},
        ))
    return turns


def _parse_args(args):
    if args is None:
        return {}
    if isinstance(args, str):
        try:
            return json.loads(args)
        except json.JSONDecodeError:
            return {"_raw": args}
    return args


def write_openai_messages(turns):
    losses = []
    messages = []
    for turn in turns:
        role = turn["role"]
        content = turn.get("content")
        msg = {"role": role}
        if role == "assistant":
            text_blocks = []
            tool_calls = []
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        text_blocks.append(str(block))
                        continue
                    bt = block.get("type")
                    if bt == "text":
                        text_blocks.append(block.get("text", ""))
                        if "cache_control" in block:
                            losses.append(make_loss(
                                path="content text cache_control",
                                source_format=turn.get("provider", "claude_code_jsonl"),
                                target_format="openai_messages",
                                reason="OpenAI messages have no slot for Anthropic cache_control blocks",
                                value=block["cache_control"],
                            ))
                    elif bt == "tool_use":
                        tool_calls.append({
                            "id": block.get("id"),
                            "type": "function",
                            "function": {
                                "name": block.get("name"),
                                "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                            },
                        })
                    else:
                        losses.append(make_loss(
                            path=f"content block type {bt}",
                            source_format=turn.get("provider", "unknown"),
                            target_format="openai_messages",
                            reason="OpenAI assistant messages can only represent text and tool_calls blocks",
                            value=block,
                        ))
            elif isinstance(content, str):
                text_blocks = [content]
            msg["content"] = "\n".join(text_blocks) if text_blocks else None
            if tool_calls:
                msg["tool_calls"] = tool_calls
        elif role == "tool":
            results = turn.get("tool_results") or []
            if results:
                msg["tool_call_id"] = results[0].get("tool_use_id")
                msg["content"] = results[0].get("content")
                if turn.get("_meta", {}).get("source", {}).get("_openai_name"):
                    msg["name"] = turn["_meta"]["source"]["_openai_name"]
        elif role == "system":
            msg["content"] = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        else:
            msg["content"] = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        messages.append(msg)
    return json.dumps(messages, ensure_ascii=False, indent=2), losses


def _selfcheck():
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "Read", "arguments": '{"file_path":"/x"}'}}
        ]},
        {"role": "tool", "tool_call_id": "call_1", "content": "file contents"},
    ]
    turns = read_openai_messages(json.dumps(messages))
    assert len(turns) == 4
    assert turns[0]["role"] == "system"
    assert turns[2]["content"][0]["type"] == "tool_use"
    assert turns[3]["content"][0]["type"] == "tool_result"

    out, losses = write_openai_messages(turns)
    out_messages = json.loads(out)
    assert out_messages[0]["role"] == "system"
    assert out_messages[2]["tool_calls"][0]["id"] == "call_1"
    assert out_messages[3]["role"] == "tool"
    print("openai selfcheck OK")


if __name__ == "__main__":
    _selfcheck()
