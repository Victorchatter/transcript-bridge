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


def main():
    read_cc, write_cc = FORMATS["claude_code_jsonl"]
    read_oa, write_oa = FORMATS["openai_messages"]

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

    print("selfcheck OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
