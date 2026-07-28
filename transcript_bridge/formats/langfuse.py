"""Langfuse trace export reader/writer.

Langfuse traces contain `observations`: `GENERATION` observations carry
`input`/`output` messages, and `SPAN` observations typically represent tool or
intermediate work.

# ponytail: converts GENERATION input/output messages and SPAN tool results.
modelParameters, usage, scores, release/version, and metadata are reported as
loss because the canonical turn model has no slot for them.
"""
import json
from datetime import datetime, timezone

from ..canonical import make_turn
from ..loss import make_loss
from . import openai


def _now():
    return datetime.now(timezone.utc).isoformat()


def _as_messages(value):
    """Normalize an observation input/output value to an OpenAI message list."""
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        if value.get("role"):
            return [value]
        return value.get("messages", [])
    return []


def _set_provider(turns, provider):
    for t in turns:
        t["provider"] = provider
    return turns


def _read_generation(obs):
    """Convert a Langfuse GENERATION observation to canonical turns."""
    turns = []
    input_msgs = _as_messages(obs.get("input"))
    if input_msgs:
        turns.extend(_set_provider(openai.read_openai_messages(json.dumps(input_msgs)), "langfuse"))
    out = obs.get("output")
    out_msgs = _as_messages(out)
    if out_msgs:
        turns.extend(_set_provider(openai.read_openai_messages(json.dumps(out_msgs)), "langfuse"))
    elif isinstance(out, (str, dict)):
        turns.append(make_turn(
            role="assistant",
            content=str(out),
            provider="langfuse",
            ts=obs.get("startTime") or _now(),
            model=obs.get("model"),
            _meta={"loss": [], "source": {"output": out}},
        ))
    # Child span tool observations are usually nested; handled by the caller.
    return turns


def _read_span_tool(obs):
    """Convert a Langfuse SPAN observation to a canonical tool turn."""
    tid = obs.get("id") or f"lf_span_{obs.get('name', 'call')}"
    content = obs.get("output")
    if not isinstance(content, (str, dict, list)):
        content = json.dumps(content, ensure_ascii=False) if content is not None else ""
    return make_turn(
        role="tool",
        content=[{"type": "tool_result", "tool_use_id": tid, "content": content}],
        tool_results=[{"tool_use_id": tid, "content": content}],
        provider="langfuse",
        ts=obs.get("startTime") or _now(),
        _meta={"loss": [], "source": {"name": obs.get("name"), "input": obs.get("input"), "output": content}},
    )


def read_langfuse(text):
    """Langfuse trace JSON -> canonical turns."""
    data = json.loads(text)
    if isinstance(data, list):
        observations = data
    elif isinstance(data, dict) and "type" in data:
        # Single observation object (e.g., a GENERATION or SPAN).
        observations = [data]
    elif isinstance(data, dict):
        observations = data.get("observations", [])
    else:
        observations = []

    turns = []
    for obs in observations:
        if not isinstance(obs, dict):
            continue
        obs_type = obs.get("type")
        if obs_type == "GENERATION":
            turns.extend(_read_generation(obs))
            # Pull nested span/tool observations as child tool turns.
            for child in obs.get("observations", []) or []:
                if child.get("type") == "SPAN":
                    turns.append(_read_span_tool(child))
        elif obs_type == "SPAN":
            turns.append(_read_span_tool(obs))
    return turns


def write_langfuse(turns):
    """Canonical turns -> minimal valid Langfuse trace export."""
    losses = []
    oa_text, oa_losses = openai.write_openai_messages(turns)
    losses.extend(oa_losses)
    messages = json.loads(oa_text)

    if messages and messages[-1].get("role") == "assistant":
        input_messages = messages[:-1]
        output_message = messages[-1]
    else:
        input_messages = messages
        output_message = {}

    trace = {
        "id": "transcript-bridge-trace",
        "name": "transcript-bridge-export",
        "observations": [
            {
                "id": "gen-1",
                "type": "GENERATION",
                "input": input_messages,
                "output": output_message,
            }
        ],
    }

    losses.append(make_loss(
        path="modelParameters",
        source_format="canonical",
        target_format="langfuse",
        reason="Langfuse modelParameters have no canonical representation and cannot be re-emitted",
        value=None,
    ))
    losses.append(make_loss(
        path="usage",
        source_format="canonical",
        target_format="langfuse",
        reason="Langfuse token usage has no canonical representation and cannot be re-emitted",
        value=None,
    ))
    losses.append(make_loss(
        path="scores",
        source_format="canonical",
        target_format="langfuse",
        reason="Langfuse evaluation scores have no canonical representation and cannot be re-emitted",
        value=None,
    ))
    losses.append(make_loss(
        path="release",
        source_format="canonical",
        target_format="langfuse",
        reason="Langfuse release/version have no canonical representation and cannot be re-emitted",
        value=None,
    ))
    losses.append(make_loss(
        path="metadata",
        source_format="canonical",
        target_format="langfuse",
        reason="Langfuse observation metadata has no canonical representation and cannot be re-emitted",
        value=None,
    ))

    return json.dumps(trace, ensure_ascii=False, indent=2), losses


def _selfcheck():
    trace = {
        "id": "trace_1",
        "name": "test",
        "observations": [
            {
                "id": "gen_1",
                "type": "GENERATION",
                "model": "gpt-4o",
                "input": [
                    {"role": "system", "content": "You are helpful."},
                    {"role": "user", "content": "Read /x."},
                ],
                "output": {"role": "assistant", "content": "I'll read it.", "tool_calls": [
                    {"id": "call_1", "type": "function", "function": {"name": "Read", "arguments": '{"file_path":"/x"}'}}
                ]},
                "modelParameters": {"temperature": 0},
                "usage": {"input": 10, "output": 5},
                "metadata": {"env": "dev"},
                "observations": [
                    {"id": "span_1", "type": "SPAN", "name": "Read", "output": {"result": "contents"}},
                ],
            }
        ],
    }
    turns = read_langfuse(json.dumps(trace))
    assert any(t["role"] == "assistant" for t in turns)
    assert any(t["role"] == "tool" for t in turns)

    out, losses = write_langfuse(turns)
    data = json.loads(out)
    assert data["observations"][0]["type"] == "GENERATION"
    print("langfuse selfcheck OK")


if __name__ == "__main__":
    _selfcheck()
