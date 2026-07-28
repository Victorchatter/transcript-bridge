"""Ollama /api/chat reader/writer.

Ollama chat requests/responses use a `messages` array similar to OpenAI's,
with roles `system`, `user`, `assistant`, and `tool`. Assistant messages may
include `tool_calls` (function-style blocks), and tool messages carry the
result content.

# ponytail: only text content and tool function blocks are converted.
Images (`images`), streaming `done` metadata, and response-level `done_*`
fields are reported as loss because the canonical turn model has no slot for
multimedia bytes or streaming wire events.
"""
import json

from ..canonical import make_turn
from ..loss import make_loss


_OLLAMA_ROLES = {"system", "user", "assistant", "tool"}


def _tool_use_id(tc, idx):
    """Ollama function calls carry no stable id; generate a deterministic one."""
    fn = tc.get("function", {})
    return fn.get("id") or f"ollama_fn_{fn.get('name', 'call')}_{idx}"


def read_ollama(text):
    """Ollama /api/chat JSON -> canonical turns."""
    data = json.loads(text)
    if isinstance(data, list):
        messages = data
        response_meta = {}
    else:
        # Accept both request shape (messages array) and response shape (single message).
        if "message" in data and isinstance(data.get("message"), dict):
            messages = [data["message"]]
            response_meta = {k: v for k, v in data.items() if k != "message"}
        else:
            messages = data.get("messages", [])
            response_meta = {}
    turns = []
    losses = []
    now = None

    if isinstance(data, dict) and data.get("stream"):
        losses.append(make_loss(
            path="stream",
            source_format="ollama",
            target_format="canonical",
            reason="Ollama streaming fragments have no canonical representation",
            value=data["stream"],
        ))
    for key, value in response_meta.items():
        if key.startswith("done") or key in ("total_duration", "load_duration", "prompt_eval_count",
                                               "prompt_eval_duration", "eval_count", "eval_duration",
                                               "created_at"):
            losses.append(make_loss(
                path=key,
                source_format="ollama",
                target_format="canonical",
                reason="Ollama response-level streaming/done metadata has no canonical representation",
                value=value,
            ))

    for i, msg in enumerate(messages):
        role = msg.get("role")
        if role not in _OLLAMA_ROLES:
            role = "user" if role is None else role
        content = msg.get("content")
        images = msg.get("images")
        if images:
            losses.append(make_loss(
                path=f"messages[{i}].images",
                source_format="ollama",
                target_format="canonical",
                reason="Ollama image bytes have no canonical representation",
                value=images,
            ))
        tool_calls = None
        tool_results = None
        source = dict(msg)

        if role == "assistant" and msg.get("tool_calls"):
            tool_calls = []
            blocks = []
            if isinstance(content, str) and content:
                blocks.append({"type": "text", "text": content})
            for j, tc in enumerate(msg["tool_calls"]):
                fn = tc.get("function", {})
                tid = _tool_use_id(tc, j)
                tool_calls.append({
                    "id": tid,
                    "type": "function",
                    "function": {
                        "name": fn.get("name"),
                        "arguments": json.dumps(fn.get("arguments", {}), ensure_ascii=False),
                    },
                })
                blocks.append({
                    "type": "tool_use",
                    "id": tid,
                    "name": fn.get("name"),
                    "input": fn.get("arguments") or {},
                })
            content = blocks
        elif role == "tool":
            tid = msg.get("tool_call_id")
            tool_results = [{"tool_use_id": tid, "content": content}]
            content = [{"type": "tool_result", "tool_use_id": tid, "content": content}]
        elif isinstance(content, list):
            # Normalize any foreign content arrays to text blocks.
            blocks = []
            for b in content:
                if isinstance(b, dict) and b.get("type") == "text":
                    blocks.append(b)
                else:
                    blocks.append({"type": "text", "text": str(b)})
            content = blocks

        turn = make_turn(
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_results=tool_results,
            provider="ollama",
            model=data.get("model") if isinstance(data, dict) else None,
            ts=now,
            _meta={"loss": [], "source": source},
        )
        turn["_meta"]["loss"].extend(losses)
        turns.append(turn)
        losses = []
    return turns


def write_ollama(turns):
    """Canonical turns -> Ollama /api/chat request shape."""
    losses = []
    messages = []
    for i, turn in enumerate(turns):
        role = turn["role"]
        content = turn.get("content")
        msg = {"role": role}
        if role == "assistant":
            text_parts = []
            tool_calls = []
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        text_parts.append(str(block))
                        continue
                    bt = block.get("type")
                    if bt == "text":
                        text_parts.append(block.get("text", ""))
                    elif bt == "tool_use":
                        if block.get("id"):
                            losses.append(make_loss(
                                path=f"turn[{i}].tool_use.id",
                                source_format=turn.get("provider", "canonical"),
                                target_format="ollama",
                                reason="Ollama function tool_calls have no id field",
                                value=block["id"],
                            ))
                        tool_calls.append({
                            "function": {
                                "name": block.get("name"),
                                "arguments": block.get("input") or {},
                            },
                        })
                    else:
                        losses.append(_block_loss(i, block, "assistant"))
            elif isinstance(content, str):
                text_parts = [content]
            msg["content"] = "\n".join(text_parts) if text_parts else ""
            if tool_calls:
                msg["tool_calls"] = tool_calls
        elif role == "tool":
            results = turn.get("tool_results") or []
            if results:
                msg["content"] = results[0].get("content", "")
                msg["tool_call_id"] = results[0].get("tool_use_id")
        elif role in ("system", "user"):
            msg["content"] = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        else:
            msg["content"] = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)

        # Ollama has no slot for canonical provider/model/timestamp fields; stash, don't report.
        messages.append(msg)

    payload = {"model": None, "messages": messages, "stream": False}

    # Honest loss for fields the target format cannot carry.
    losses.append(make_loss(
        path="images",
        source_format="canonical",
        target_format="ollama",
        reason="Ollama /api/chat cannot carry multimodal image bytes in the messages array",
        value=None,
    ))
    losses.append(make_loss(
        path="done_metadata",
        source_format="canonical",
        target_format="ollama",
        reason="Ollama response-level done/done_reason/duration metadata has no canonical representation and cannot be re-emitted",
        value=None,
    ))
    losses.append(make_loss(
        path="streaming_fragments",
        source_format="canonical",
        target_format="ollama",
        reason="Ollama streaming fragments have no canonical representation and cannot be re-emitted",
        value=None,
    ))

    return json.dumps(payload, ensure_ascii=False, indent=2), losses


def _block_loss(idx, block, role):
    if isinstance(block, dict) and block.get("type") == "image":
        return make_loss(
            path=f"turn[{idx}].content image",
            source_format="canonical",
            target_format="ollama",
            reason="Ollama /api/chat cannot carry multimodal image bytes in the messages array",
            value=block,
        )
    return make_loss(
        path=f"turn[{idx}].content block type {block.get('type') if isinstance(block, dict) else type(block).__name__}",
        source_format="canonical",
        target_format="ollama",
        reason=f"Ollama {role} messages can only represent text and function tool_calls",
        value=block,
    )


def _selfcheck():
    body = {
        "model": "llama3.1",
        "messages": [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Read /x."},
            {"role": "assistant", "content": "I'll read it.", "tool_calls": [
                {"function": {"name": "Read", "arguments": {"file_path": "/x"}}}
            ]},
            {"role": "tool", "content": "contents of /x", "tool_call_id": "ollama_fn_Read_0"},
        ],
        "stream": False,
    }
    turns = read_ollama(json.dumps(body))
    assert len(turns) == 4
    assert turns[2]["tool_calls"][0]["function"]["name"] == "Read"
    assert turns[3]["role"] == "tool"

    out, losses = write_ollama(turns)
    data = json.loads(out)
    assert data["messages"][2].get("tool_calls")[0]["function"]["name"] == "Read"
    print("ollama selfcheck OK")


if __name__ == "__main__":
    _selfcheck()
