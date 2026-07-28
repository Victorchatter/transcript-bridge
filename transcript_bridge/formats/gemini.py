"""Gemini contents[] format reader/writer.

Gemini chat requests use a top-level `contents` array of `{role, parts[]}`
objects. Roles are `user` and `model`; tool calls are `functionCall` parts and
tool responses are `functionResponse` parts inside a `user` turn.

# ponytail: text, functionCall, and functionResponse parts are converted.
Safety metadata, grounding, citations, multimodal parts (`inlineData`,
`fileData`), and flattening system turns into `systemInstruction` are reported
as loss.
"""
import json

from ..canonical import make_turn
from ..loss import make_loss


_GEMINI_CONTENT_ROLES = {"user", "model"}


def _fn_call_id(part, idx):
    fn = part.get("functionCall", {})
    return f"gemini_fn_{fn.get('name', 'call')}_{idx}"


def _text_from_parts(parts):
    return "\n".join(p.get("text", "") for p in parts if isinstance(p, dict) and "text" in p)


def read_gemini(text):
    """Gemini contents JSON -> canonical turns."""
    data = json.loads(text)
    turns = []
    contents = data.get("contents", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])

    # System instruction is a top-level field, not a content turn.
    system_instruction = data.get("systemInstruction") if isinstance(data, dict) else None
    if system_instruction:
        sys_text = _text_from_parts(system_instruction.get("parts", []))
        turns.append(make_turn(
            role="system",
            content=sys_text,
            provider="google",
            _meta={"loss": [], "source": {"systemInstruction": system_instruction}},
        ))

    for i, item in enumerate(contents):
        role = item.get("role", "user")
        parts = item.get("parts", [])
        blocks = []
        tool_calls = None
        tool_results = None
        source = dict(item)
        turn_losses = []
        has_fn_response = False

        for j, part in enumerate(parts):
            if not isinstance(part, dict):
                continue
            if "text" in part:
                blocks.append({"type": "text", "text": part["text"]})
            elif "functionCall" in part:
                fn = part["functionCall"]
                tid = _fn_call_id(part, j)
                blocks.append({
                    "type": "tool_use",
                    "id": tid,
                    "name": fn.get("name"),
                    "input": fn.get("args") or {},
                })
                if tool_calls is None:
                    tool_calls = []
                tool_calls.append({
                    "id": tid,
                    "type": "function",
                    "function": {
                        "name": fn.get("name"),
                        "arguments": json.dumps(fn.get("args", {}), ensure_ascii=False),
                    },
                })
            elif "functionResponse" in part:
                has_fn_response = True
                fn = part["functionResponse"]
                tid = fn.get("name")  # Gemini function responses are keyed by name, not id.
                blocks.append({
                    "type": "tool_result",
                    "tool_use_id": tid,
                    "content": fn.get("response"),
                })
                if tool_results is None:
                    tool_results = []
                tool_results.append({"tool_use_id": tid, "content": fn.get("response")})
            elif "inlineData" in part or "fileData" in part:
                turn_losses.append(make_loss(
                    path=f"contents[{i}].parts[{j}] multimodal",
                    source_format="gemini",
                    target_format="canonical",
                    reason="Gemini inlineData/fileData parts have no canonical representation",
                    value=part,
                ))
            else:
                turn_losses.append(make_loss(
                    path=f"contents[{i}].parts[{j}]",
                    source_format="gemini",
                    target_format="canonical",
                    reason="Unknown Gemini content part type",
                    value=part,
                ))

        if has_fn_response:
            canonical_role = "tool"
        elif role == "model":
            canonical_role = "assistant"
        else:
            canonical_role = "user" if role in _GEMINI_CONTENT_ROLES else role

        if not blocks and not tool_calls and not tool_results:
            blocks = [{"type": "text", "text": ""}]

        turns.append(make_turn(
            role=canonical_role,
            content=blocks,
            tool_calls=tool_calls,
            tool_results=tool_results,
            provider="google",
            _meta={"loss": turn_losses, "source": source},
        ))

    return turns


def write_gemini(turns):
    """Canonical turns -> Gemini contents[] shape."""
    losses = []
    contents = []
    system_parts = []

    for i, turn in enumerate(turns):
        role = turn["role"]
        if role == "system":
            content = turn.get("content", "")
            text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            system_parts.append({"text": text})
            losses.append(make_loss(
                path=f"turn[{i}].role system",
                source_format=turn.get("provider", "canonical"),
                target_format="gemini",
                reason="Gemini flattens system turns into the top-level systemInstruction field",
                value=role,
            ))
            continue

        gemini_role = "model" if role == "assistant" else "user"
        parts = []
        content = turn.get("content")

        if role == "tool":
            results = turn.get("tool_results") or []
            for r in results:
                fn_name = r.get("tool_use_id")
                parts.append({
                    "functionResponse": {
                        "name": fn_name,
                        "response": r.get("content"),
                    },
                })
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    parts.append({"text": str(block)})
                    continue
                bt = block.get("type")
                if bt == "text":
                    parts.append({"text": block.get("text", "")})
                elif bt == "tool_use":
                    if block.get("id"):
                        losses.append(make_loss(
                            path=f"turn[{i}].tool_use.id",
                            source_format=turn.get("provider", "canonical"),
                            target_format="gemini",
                            reason="Gemini functionCall parts have no id field",
                            value=block["id"],
                        ))
                    parts.append({
                        "functionCall": {
                            "name": block.get("name"),
                            "args": block.get("input") or {},
                        },
                    })
                elif bt == "tool_result":
                    parts.append({
                        "functionResponse": {
                            "name": block.get("tool_use_id"),
                            "response": block.get("content"),
                        },
                    })
                elif bt == "image":
                    losses.append(make_loss(
                        path=f"turn[{i}].content image",
                        source_format=turn.get("provider", "canonical"),
                        target_format="gemini",
                        reason="Gemini cannot reconstruct inline image bytes without original mime/data",
                        value=block,
                    ))
                else:
                    losses.append(make_loss(
                        path=f"turn[{i}].content block type {bt}",
                        source_format=turn.get("provider", "canonical"),
                        target_format="gemini",
                        reason="Gemini contents[] can only represent text, functionCall, and functionResponse parts",
                        value=block,
                    ))
        elif isinstance(content, str):
            parts.append({"text": content})
        else:
            parts.append({"text": json.dumps(content, ensure_ascii=False)})

        if parts:
            contents.append({"role": gemini_role, "parts": parts})

    payload = {"contents": contents}
    if system_parts:
        payload["systemInstruction"] = {"parts": system_parts}

    # Honest loss for fields the target format cannot carry.
    losses.append(make_loss(
        path="safetySettings",
        source_format="canonical",
        target_format="gemini",
        reason="Gemini safety metadata has no canonical representation and cannot be re-emitted",
        value=None,
    ))
    losses.append(make_loss(
        path="grounding",
        source_format="canonical",
        target_format="gemini",
        reason="Gemini grounding metadata has no canonical representation and cannot be re-emitted",
        value=None,
    ))
    losses.append(make_loss(
        path="citations",
        source_format="canonical",
        target_format="gemini",
        reason="Gemini citation metadata has no canonical representation and cannot be re-emitted",
        value=None,
    ))

    return json.dumps(payload, ensure_ascii=False, indent=2), losses


def _selfcheck():
    body = {
        "systemInstruction": {"parts": [{"text": "You are helpful."}]},
        "contents": [
            {"role": "user", "parts": [{"text": "Read /x."}]},
            {"role": "model", "parts": [
                {"text": "I'll read it."},
                {"functionCall": {"name": "Read", "args": {"file_path": "/x"}}},
            ]},
            {"role": "user", "parts": [{"functionResponse": {"name": "Read", "response": {"result": "contents"}}}]},
        ],
    }
    turns = read_gemini(json.dumps(body))
    assert turns[0]["role"] == "system"
    assert turns[1]["role"] == "user"
    assert turns[2]["role"] == "assistant"
    assert turns[2]["tool_calls"][0]["function"]["name"] == "Read"
    assert turns[3]["role"] == "tool"

    out, losses = write_gemini(turns)
    data = json.loads(out)
    assert data["contents"][1]["role"] == "model"
    assert data["contents"][1]["parts"][1]["functionCall"]["name"] == "Read"
    print("gemini selfcheck OK")


if __name__ == "__main__":
    _selfcheck()
