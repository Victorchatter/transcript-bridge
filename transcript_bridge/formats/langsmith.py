"""LangSmith trace export reader/writer.

LangSmith exports are JSONL of Run objects. Each run has `run_type`, `inputs`,
`outputs`, `child_runs`, and a large surface area of metadata (tags, latency,
scores, etc.) that the canonical model cannot carry.

# ponytail: reads LLM/chat runs with `inputs.messages`/`outputs.message` and
child tool runs; writes a minimal valid single-LLM-run trace. Metadata, tags,
latency, scores, and non-LLM/non-tool spans are reported as loss.
"""
import json
from datetime import datetime, timezone

from ..canonical import make_turn
from ..loss import make_loss
from . import openai


_RUN_TYPES_LLM = {"llm", "chat"}
_RUN_TYPES_TOOL = {"tool", "retriever"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _messages_from_inputs(inputs):
    msgs = inputs.get("messages") if isinstance(inputs, dict) else None
    if msgs is None:
        # Some LangSmith runs wrap the prompt in a string or dict.
        return []
    return msgs


def _output_message(outputs):
    if not isinstance(outputs, dict):
        return None
    return outputs.get("message")


def _set_provider(turns, provider):
    for t in turns:
        t["provider"] = provider
    return turns


def _read_run(run, depth=0):
    """Recursively extract canonical turns from a LangSmith Run."""
    turns = []
    if not isinstance(run, dict):
        return turns

    run_type = run.get("run_type")
    if run_type in _RUN_TYPES_LLM:
        inputs = run.get("inputs", {})
        outputs = run.get("outputs", {})
        messages = _messages_from_inputs(inputs)
        if messages:
            turns.extend(_set_provider(openai.read_openai_messages(json.dumps(messages)), "langsmith"))
        out_msg = _output_message(outputs)
        if isinstance(out_msg, dict):
            turns.extend(_set_provider(openai.read_openai_messages(json.dumps([out_msg])), "langsmith"))

        for child in run.get("child_runs", []) or []:
            if child.get("run_type") in _RUN_TYPES_TOOL:
                turns.extend(_tool_turn(child))
            else:
                turns.extend(_read_run(child, depth + 1))

    elif run_type in _RUN_TYPES_TOOL and depth == 0:
        # Standalone tool run at the top level.
        turns.extend(_tool_turn(run))
    else:
        for child in run.get("child_runs", []) or []:
            turns.extend(_read_run(child, depth + 1))

    return turns


def _tool_turn(run):
    """Convert a LangSmith tool/retriever run to a canonical tool turn."""
    inputs = run.get("inputs", {})
    outputs = run.get("outputs", {})
    name = run.get("name")
    # Use the run id if present; otherwise derive a stable id from the name.
    tid = run.get("id") or f"ls_tool_{name or 'call'}"
    content = outputs if isinstance(outputs, (str, dict, list)) else json.dumps(outputs, ensure_ascii=False)
    return [make_turn(
        role="tool",
        content=[{"type": "tool_result", "tool_use_id": tid, "content": content}],
        tool_results=[{"tool_use_id": tid, "content": content}],
        provider="langsmith",
        ts=run.get("start_time") or _now(),
        _meta={"loss": [], "source": {"name": name, "inputs": inputs, "outputs": outputs}},
    )]


def read_langsmith(text):
    """LangSmith JSONL export -> canonical turns."""
    turns = []
    # Accept JSONL of runs, a single JSON array, or a single run object.
    records = []
    stripped = text.strip()
    if not stripped:
        return turns
    if stripped.startswith("["):
        records = json.loads(stripped)
    elif stripped.startswith("{"):
        records = [json.loads(stripped)]
    else:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))

    for run in records:
        turns.extend(_read_run(run))
    return turns


def write_langsmith(turns):
    """Canonical turns -> minimal valid LangSmith trace export (JSONL)."""
    losses = []
    # Convert the whole transcript to OpenAI messages to preserve history.
    oa_text, oa_losses = openai.write_openai_messages(turns)
    losses.extend(oa_losses)
    messages = json.loads(oa_text)

    # Split messages into input history and output message if the last turn is
    # from the assistant.
    if messages and messages[-1].get("role") == "assistant":
        inputs_messages = messages[:-1]
        outputs = {"message": messages[-1]}
    else:
        inputs_messages = messages
        outputs = {"message": {}}

    run = {
        "id": "transcript-bridge-export",
        "name": "transcript-bridge-export",
        "run_type": "llm",
        "inputs": {"messages": inputs_messages},
        "outputs": outputs,
        "start_time": _now(),
        "child_runs": [],
    }

    losses.append(make_loss(
        path="metadata",
        source_format="canonical",
        target_format="langsmith",
        reason="LangSmith metadata (project, session, etc.) has no canonical representation and cannot be re-emitted",
        value=None,
    ))
    losses.append(make_loss(
        path="tags",
        source_format="canonical",
        target_format="langsmith",
        reason="LangSmith run tags have no canonical representation and cannot be re-emitted",
        value=None,
    ))
    losses.append(make_loss(
        path="latency",
        source_format="canonical",
        target_format="langsmith",
        reason="LangSmith start_time/end_time latency has no canonical representation and cannot be re-emitted",
        value=None,
    ))
    losses.append(make_loss(
        path="scores",
        source_format="canonical",
        target_format="langsmith",
        reason="LangSmith evaluation scores have no canonical representation and cannot be re-emitted",
        value=None,
    ))
    losses.append(make_loss(
        path="spans",
        source_format="canonical",
        target_format="langsmith",
        reason="Additional LangSmith spans/child runs (retrieval, chain, etc.) are not reconstructed",
        value=None,
    ))

    return json.dumps(run, ensure_ascii=False, indent=2), losses


def _selfcheck():
    run = {
        "id": "run_1",
        "name": "LLM",
        "run_type": "llm",
        "inputs": {
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Read /x."},
            ]
        },
        "outputs": {
            "message": {"role": "assistant", "content": "I'll read it.", "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "Read", "arguments": '{"file_path":"/x"}'}}
            ]}
        },
        "child_runs": [
            {"id": "tool_1", "name": "Read", "run_type": "tool", "inputs": {"file_path": "/x"}, "outputs": {"result": "contents"}},
        ],
        "metadata": {"foo": "bar"},
        "tags": ["dev"],
    }
    turns = read_langsmith(json.dumps([run]))
    assert any(t["role"] == "assistant" for t in turns)
    assert any(t["role"] == "tool" for t in turns)

    out, losses = write_langsmith(turns)
    data = json.loads(out)
    assert data["run_type"] == "llm"
    assert data["inputs"]["messages"]
    print("langsmith selfcheck OK")


if __name__ == "__main__":
    _selfcheck()
