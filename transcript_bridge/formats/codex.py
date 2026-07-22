"""Codex CLI trace reader/writer."""
import json

from ..loss import make_loss
from . import openai


def read_codex(text):
    # ponytail: Codex records are OpenAI-message-like with extra keys.
    # We normalize message-ish records and stash the full record in _meta.source.
    records = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        records.append(record)

    # Try to extract a JSON array if the whole input is an array first.
    if len(records) == 1 and isinstance(records[0], list):
        records = records[0]

    # Codex fields that are not part of the OpenAI message shape.
    codex_only_fields = {"usage", "checkpoint", "command", "cwd", "metadata", "type", "id"}

    message_like = []
    for record in records:
        if not isinstance(record, dict):
            continue
        if "role" not in record:
            # Non-message record; we still keep it in source for debugging but
            # do not create a turn for it.
            continue
        msg = {k: v for k, v in record.items() if k not in codex_only_fields}
        # Preserve codex-only keys under a nested key so the OpenAI reader can
        # store them in _meta.source.
        if any(k in record for k in codex_only_fields):
            msg["_codex_extra"] = {k: record[k] for k in codex_only_fields if k in record}
        message_like.append(msg)

    return openai.read_openai_messages(json.dumps(message_like))


def write_codex(turns):
    losses = []
    records = []
    openai_text, openai_losses = openai.write_openai_messages(turns)
    losses.extend(openai_losses)
    messages = json.loads(openai_text)
    for i, msg in enumerate(messages):
        record = dict(msg)
        # Re-inject codex-only source fields if available.
        source = (turns[i].get("_meta") or {}).get("source", {})
        extra = source.get("_codex_extra", {})
        for k, v in extra.items():
            if k not in record:
                record[k] = v
            else:
                losses.append(make_loss(
                    path=f"turn[{i}]._meta.source.{k}",
                    source_format="codex",
                    target_format="codex",
                    reason="Codex extra field conflicts with normalized message field",
                    value=v,
                ))
        records.append(record)
    return "\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in records) + "\n", losses


def _selfcheck():
    lines = [
        json.dumps({"type": "system", "role": "system", "content": "You are helpful.", "usage": {"prompt_tokens": 10}}),
        json.dumps({"type": "user", "role": "user", "content": "Hello", "checkpoint": "chk_1"}),
        json.dumps({"type": "assistant", "role": "assistant", "content": "Hi!"}),
    ]
    turns = read_codex("\n".join(lines))
    assert len(turns) == 3
    assert turns[0]["_meta"]["source"].get("_codex_extra", {}).get("usage") == {"prompt_tokens": 10}

    out, losses = write_codex(turns)
    records = [json.loads(line) for line in out.strip().split("\n")]
    assert records[0]["role"] == "system"
    print("codex selfcheck OK")


if __name__ == "__main__":
    _selfcheck()
