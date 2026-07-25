#!/usr/bin/env python3
"""Round-trip self-check for transcript-bridge.

Builds canonical transcripts with one Claude-specific field (cache_control)
and one OpenAI-specific field (name on a tool message), then proves:
1. Claude -> Claude is lossless.
2. Claude -> OpenAI reports exactly the cache_control loss.
3. OpenAI -> Claude reports the OpenAI-specific name as loss.
4. Claude -> OpenAI -> Claude preserves content except the lossy fields.
"""
import json
import sys

from transcript_bridge import FORMATS
from transcript_bridge.canonical import make_turn


def _make_claude_transcript():
    now = "2026-07-22T12:00:00+00:00"
    return [
        make_turn(role="system", content="You are helpful.", provider="anthropic", ts=now),
        make_turn(role="user", content="Read /x for me.", provider="anthropic", ts=now),
        make_turn(
            role="assistant",
            content=[
                {"type": "text", "text": "I'll read it.", "cache_control": {"type": "ephemeral"}},
                {"type": "tool_use", "id": "tu_1", "name": "Read", "input": {"file_path": "/x"}},
            ],
            tool_calls=[{"type": "tool_use", "id": "tu_1", "name": "Read", "input": {"file_path": "/x"}}],
            provider="anthropic",
            ts=now,
        ),
        make_turn(
            role="tool",
            content=[{"type": "tool_result", "tool_use_id": "tu_1", "content": "contents of /x"}],
            tool_results=[{"tool_use_id": "tu_1", "content": "contents of /x"}],
            provider="openai",
            ts=now,
            _meta={
                "loss": [],
                "source": {"role": "tool", "tool_call_id": "tu_1", "content": "contents of /x", "name": "Read"},
            },
        ),
    ]


def _loss_paths(losses):
    return sorted(loss["path"] for loss in losses)


def _strip_meta(turn):
    t = dict(turn)
    t["_meta"] = {"loss": [], "source": {}}
    return t


def _make_tape():
    """A minimal agent-vcr tape: request, tool call, tool result, response."""
    def L(o):
        return json.dumps(o)
    req = L({"system": "You are careful.",
             "tools": [{"name": "read", "input_schema": {"type": "object"}}],
             "messages": [{"role": "user", "content": "audit this repo"}]})
    return "\n".join([
        L({"kind": "model_request", "seq": 1, "provider": "anthropic", "body": req}),
        L({"kind": "tool_call", "seq": 2, "server": "fs", "tool": "read",
           "args": {"p": "/a.py"}, "args_hash": "h1"}),
        L({"kind": "tool_result", "seq": 3, "server": "fs", "tool": "read",
           "args_hash": "h1", "result": {"text": "x = 1"}}),
        L({"kind": "model_response", "seq": 4, "provider": "anthropic",
           "body": L({"content": [{"type": "text", "text": "Found it."}]}),
           "usage": {"input_tokens": 100, "output_tokens": 10}}),
    ]) + "\n"


def check_tape():
    """agent-vcr tape -> canonical -> OpenAI.

    This is the cross-tool interop the LocalLab README advertises. It is
    asserted here so it cannot rot silently. The reader must emit the same
    canonical shape as the other readers (Anthropic-style content blocks plus
    separate role="tool" turns) — an earlier version emitted a bare string and
    side fields, which the writers dropped while still reporting "no loss".
    """
    read_tape, write_tape = FORMATS["tape"]
    turns = read_tape(_make_tape())

    roles = [t["role"] for t in turns]
    assert roles == ["user", "assistant", "tool", "assistant"], roles

    tool_uses = [b for t in turns if isinstance(t.get("content"), list)
                 for b in t["content"] if b.get("type") == "tool_use"]
    assert len(tool_uses) == 1, tool_uses
    assert tool_uses[0]["name"] == "read", tool_uses[0]
    assert tool_uses[0]["input"] == {"p": "/a.py"}, tool_uses[0]

    # The tool call and its result must survive conversion, not vanish silently.
    _, write_oa = FORMATS["openai_messages"]
    oa_text, _ = write_oa(turns)
    oa = json.loads(oa_text)
    assert any(m.get("tool_calls") for m in oa), "tool_calls lost converting tape -> openai"
    assert any(m.get("role") == "tool" for m in oa), "tool result lost converting tape -> openai"

    # Usage is preserved in _meta rather than discarded.
    assert any(t["_meta"]["source"].get("usage") for t in turns), "usage not carried into _meta"

    # Writing a tape is refused by design — canonical turns cannot reconstruct
    # wire traffic, and fabricating it would be worse than refusing.
    try:
        write_tape(turns)
    except NotImplementedError:
        pass
    else:
        raise AssertionError("write_tape must refuse; a fabricated tape is not replayable")


def main():
    read_cc, write_cc = FORMATS["claude_code_jsonl"]
    read_oa, write_oa = FORMATS["openai_messages"]
    read_cx, write_cx = FORMATS["codex"]

    original = _make_claude_transcript()

    # 1. Claude -> Claude is lossless.
    cc_text, cc_losses = write_cc(original)
    assert not cc_losses, cc_losses
    cc_round = read_cc(cc_text)
    assert len(cc_round) == len(original)
    assert [_strip_meta(t) for t in cc_round] == [_strip_meta(t) for t in original]

    # 2. Claude -> OpenAI reports exactly cache_control.
    oa_text, oa_losses = write_oa(cc_round)
    assert _loss_paths(oa_losses) == ["content text cache_control"], _loss_paths(oa_losses)

    # 3. Claude -> OpenAI -> Claude preserves content except cache_control.
    final_round = read_cc(write_cc(read_oa(oa_text))[0])
    assert len(final_round) == len(original)
    for i, (orig, final) in enumerate(zip(original, final_round)):
        assert orig["role"] == final["role"], f"role mismatch at {i}"
        if i == 2:
            assert "cache_control" not in final["content"][0], final
        if i == 3:
            assert final["content"][0]["content"] == "contents of /x", final

    # 4. OpenAI -> Claude reports the OpenAI-specific name as loss.
    oa_messages = [
        {"role": "tool", "tool_call_id": "call_1", "content": "result", "name": "Read"},
    ]
    oa_turns = read_oa(json.dumps(oa_messages))
    _, name_losses = write_cc(oa_turns)
    assert any("_openai_name" in loss["path"] or "name" in loss["reason"].lower()
               for loss in name_losses), name_losses

    # 5. Codex usage/checkpoint: stashed in _meta on the OpenAI hop, re-emitted
    #    on the Codex hop. Note: the OpenAI writer does NOT report usage as loss
    #    (it is stashed in _meta.source._codex_extra, not surfaced as a loss
    #    entry), so we assert absence from the OpenAI output rather than a loss.
    codex_lines = [
        json.dumps({"role": "assistant", "content": "Hi!",
                    "usage": {"prompt_tokens": 10, "completion_tokens": 4},
                    "checkpoint": "chk_1"}),
    ]
    cx_turns = read_cx("\n".join(codex_lines))
    extra = cx_turns[0]["_meta"]["source"].get("_codex_extra", {})
    assert extra.get("usage") == {"prompt_tokens": 10, "completion_tokens": 4}
    assert extra.get("checkpoint") == "chk_1"

    # OpenAI hop: usage/checkpoint have no slot and are not reported as loss.
    oa_from_cx, oa_from_cx_losses = write_oa(cx_turns)
    oa_msgs = json.loads(oa_from_cx)
    assert "usage" not in oa_msgs[0] and "checkpoint" not in oa_msgs[0]
    assert not any("usage" in l["path"] or "checkpoint" in l["path"] for l in oa_from_cx_losses)

    # Codex hop: usage/checkpoint re-emitted from _meta.source._codex_extra.
    cx_back, cx_back_losses = write_cx(cx_turns)
    cx_records = [json.loads(l) for l in cx_back.strip().split("\n")]
    assert cx_records[0]["usage"] == {"prompt_tokens": 10, "completion_tokens": 4}
    assert cx_records[0]["checkpoint"] == "chk_1"
    assert not cx_back_losses

    check_tape()

    print("selfcheck OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
