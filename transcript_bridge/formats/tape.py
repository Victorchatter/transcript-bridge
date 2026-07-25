"""agent-vcr tape format — read-only.

A tape is JSONL of wire-level events (`model_request`, `model_response`,
`tool_call`, `tool_result`) each carrying a `seq`, written by
https://github.com/Victorchatter/AgentVCR

**Reading is supported. Writing is deliberately not.** A tape records what
actually went over the wire: raw request bodies, response encodings, usage
blocks. Canonical turns do not carry that, so writing a tape from them would
mean fabricating wire detail that was never observed — a file that looks
replayable and is not. That is a worse failure than refusing, and refusing is
consistent with this tool's whole premise: report loss, never invent.

# ponytail: covers the Anthropic Messages and OpenAI chat-completions body
# shapes. An exotic provider body yields a turn whose content is empty and a
# recorded loss, rather than a silent drop. Upgrade: per-provider body readers
# keyed on the `provider` field.
"""
import json

from ..canonical import make_turn
from ..loss import make_loss

_KINDS = ("model_request", "model_response", "tool_call", "tool_result")


def _body(ev):
    b = ev.get("body")
    if isinstance(b, str):
        try:
            return json.loads(b)
        except json.JSONDecodeError:
            return None
    return b if isinstance(b, dict) else None


def sniff(text):
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            return False
        return isinstance(rec, dict) and rec.get("kind") in _KINDS
    return False


def _assistant_content(resp):
    """Anthropic content blocks, else OpenAI choices[].message.content."""
    if not resp:
        return ""
    parts = []
    for block in resp.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text") or "")
    if parts:
        return "".join(parts)
    for choice in resp.get("choices") or []:
        msg = (choice or {}).get("message") or {}
        if msg.get("content"):
            parts.append(msg["content"])
    return "".join(parts)


def read_tape(text):
    """Tape JSONL -> canonical turns."""
    by_seq = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(ev, dict) and ev.get("kind") in _KINDS:
            by_seq.setdefault(ev.get("seq"), []).append(ev)

    turns = []
    seeded_user = False

    for seq in sorted(by_seq, key=lambda s: (s is None, s)):
        group = by_seq[seq]

        # The first request carries the conversation opening; emit it once so a
        # converted transcript is not assistant-only.
        req = next((_body(e) for e in group if e.get("kind") == "model_request"), None)
        if req and not seeded_user:
            for m in req.get("messages") or []:
                if isinstance(m, dict) and m.get("role") in ("system", "user"):
                    c = m.get("content")
                    if isinstance(c, str) and c:
                        turns.append(make_turn(role=m["role"], content=c,
                                               provider=req.get("provider")))
            seeded_user = True

        # Canonical shape follows the other readers: assistant content is a
        # list of Anthropic-style blocks (text / tool_use), and each tool result
        # is its own role="tool" turn keyed by tool_use_id. Emitting a bare
        # string plus side fields would be silently dropped by the writers.
        resp_ev = next((e for e in group if e.get("kind") == "model_response"), None)
        call_evs = [e for e in group if e.get("kind") == "tool_call"]
        result_evs = [e for e in group if e.get("kind") == "tool_result"]

        if resp_ev is None and not (call_evs or result_evs):
            continue

        resp = _body(resp_ev) if resp_ev else None
        meta = {"loss": [], "source": {"seq": seq}}
        if resp_ev is not None and resp is None:
            meta["loss"].append(make_loss(
                "body", "tape", "canonical",
                "response body was not JSON-decodable (encoded or streaming)",
                (resp_ev.get("content_type"), resp_ev.get("content_encoding"))))
        if resp_ev is not None and resp_ev.get("usage"):
            meta["source"]["usage"] = resp_ev["usage"]

        blocks = []
        text = _assistant_content(resp)
        if text:
            blocks.append({"type": "text", "text": text})
        for e in call_evs:
            blocks.append({"type": "tool_use",
                           "id": e.get("args_hash"),
                           "name": e.get("tool"),
                           "input": e.get("args") or {}})

        if blocks or resp_ev is not None:
            turns.append(make_turn(
                role="assistant",
                content=blocks,
                provider=(resp_ev or {}).get("provider"),
                _meta=meta,
            ))

        for e in result_evs:
            turns.append(make_turn(
                role="tool",
                content=None,
                tool_results=[{"tool_use_id": e.get("args_hash"),
                               "content": e.get("result")}],
                _meta={"loss": [], "source": {"seq": seq, "tool": e.get("tool")}},
            ))

    return turns


def write_tape(turns):
    """Not supported, by design — see the module docstring."""
    raise NotImplementedError(
        "transcript-bridge cannot write agent-vcr tapes. A tape records raw "
        "wire traffic (request bodies, encodings, usage); canonical turns do "
        "not carry it, so writing one would fabricate detail that was never "
        "observed. Read tapes with --from tape; record them with agent-vcr."
    )
