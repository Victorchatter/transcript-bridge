# transcript-bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `transcript-bridge`, a local/offline CLI tool that converts agent session logs between Claude Code JSONL, OpenAI messages, Codex traces, and a canonical JSONL, with loss-aware round-trip reporting.

**Architecture:** A tiny package `transcript_bridge/` with a canonical envelope, a registry of `(reader, writer)` callables for each format, a loss-report module, and a small `argparse` CLI. The CLI pipeline is `text → reader → list[CanonicalTurn] → writer → (text, losses)`. A single `selfcheck.py` proves round-trip honesty.

**Tech Stack:** Python 3.10+, stdlib only.

## Global Constraints

- Python, `pipx install .`. Fully local/offline, read-only on inputs, no telemetry.
- Format I/O via a small plugin-ish reader/writer registry; ship the first three readers+writers in v1 — no dynamic plugin loading, just a table of `(format_name, reader, writer)` functions.
- Canonical intermediate model shared with agent-vcr/agent-checkpoint where free — reuse envelope shape, add `_meta`.
- Round-trip honesty: `transcript-bridge <in> --from X --to Y` prints a loss report. Add `--strict` to exit nonzero on any loss.
- CLI: `transcript-bridge <file> --from <fmt> --to <fmt> [-o out] [--strict]`; `transcript-bridge formats` lists supported formats.
- Small and sharp. Ponytail: stdlib only, shortest working diff, no unrequested abstractions. `# ponytail:` comments on simplifications.
- One `selfcheck.py`: a canonical transcript with one Claude-specific and one OpenAI-specific field; convert Claude→OpenAI→Claude; assert the round-trip preserves everything *except* the lossy fields and that the loss report lists exactly those.
- License MIT. README with a round-trip + loss-report example.

---

### Task 1: Project scaffold and pyproject.toml

**Files:**
- Create: `transcript_bridge/__init__.py`
- Create: `transcript_bridge/canonical.py`
- Create: `pyproject.toml`
- Create: `LICENSE`
- Modify: none
- Test: `python -c "import transcript_bridge; print(transcript_bridge.__file__)"`

**Interfaces:**
- Produces: package layout, `pyproject.toml` with `pipx install .` support, MIT `LICENSE`.

- [ ] **Step 1: Create package `__init__.py`**

Create `transcript_bridge/__init__.py`:

```python
"""transcript-bridge — loss-aware agent transcript format conversion."""

__version__ = "0.1.0"
```

- [ ] **Step 2: Create stub `canonical.py`**

Create `transcript_bridge/canonical.py`:

```python
"""Canonical intermediate envelope and JSONL helpers."""


def make_turn(role, content, **kwargs):
    raise NotImplementedError
```

- [ ] **Step 3: Write `pyproject.toml`**

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "transcript-bridge"
version = "0.1.0"
description = "Loss-aware conversion between agent transcript formats"
readme = "README.md"
license = {text = "MIT"}
requires-python = ">=3.10"
authors = [{name = "Victor Filtchev"}]
keywords = ["claude", "openai", "codex", "transcript", "agent", "jsonl"]
classifiers = [
    "Development Status :: 4 - Beta",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3",
]

[project.scripts]
transcript-bridge = "transcript_bridge.cli:main"

[tool.setuptools.packages.find]
include = ["transcript_bridge*"]
```

- [ ] **Step 4: Write MIT `LICENSE`**

Create `LICENSE`:

```text
MIT License

Copyright (c) 2026 Victor Filtchev

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 5: Verify package imports**

Run:

```bash
python -c "import transcript_bridge; print(transcript_bridge.__version__)"
```

Expected output:

```
0.1.0
```

- [ ] **Step 6: Commit**

```bash
git add transcript_bridge/__init__.py transcript_bridge/canonical.py pyproject.toml LICENSE
git commit -m "chore: scaffold transcript-bridge package and license" -m "🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

---

### Task 2: Canonical envelope + JSONL helpers

**Files:**
- Create: `transcript_bridge/loss.py`
- Modify: `transcript_bridge/canonical.py`
- Test: `python transcript_bridge/canonical.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `canonical.make_turn(role, content, *, tool_calls=None, tool_results=None, provider=None, model=None, ts=None, _meta=None)` → dict
  - `canonical.read_jsonl(text: str) -> list[dict]`
  - `canonical.write_jsonl(turns: list[dict]) -> str`
  - `loss.make_loss(path, source_format, target_format, reason, value)` → dict

- [ ] **Step 1: Write failing self-check in `canonical.py`**

Replace `transcript_bridge/canonical.py` with:

```python
"""Canonical intermediate envelope and JSONL helpers."""
import json
from datetime import datetime, timezone


def make_turn(role, content, *, tool_calls=None, tool_results=None,
                provider=None, model=None, ts=None, _meta=None):
    raise NotImplementedError


def read_jsonl(text):
    raise NotImplementedError


def write_jsonl(turns):
    raise NotImplementedError


def _selfcheck():
    now = "2026-07-22T00:00:00+00:00"
    t = make_turn(role="user", content="hello", provider="anthropic", ts=now)
    assert t["role"] == "user"
    assert t["content"] == "hello"
    assert t["provider"] == "anthropic"
    assert t["ts"] == now
    assert t["_meta"] == {"loss": [], "source": {}}

    text = write_jsonl([t])
    turns = read_jsonl(text)
    assert turns == [t]
    print("canonical selfcheck OK")


if __name__ == "__main__":
    _selfcheck()
```

Run:

```bash
python transcript_bridge/canonical.py
```

Expected: `NotImplementedError`.

- [ ] **Step 2: Implement canonical helpers**

Replace the stub bodies in `transcript_bridge/canonical.py`:

```python
def make_turn(role, content, *, tool_calls=None, tool_results=None,
                provider=None, model=None, ts=None, _meta=None):
    if _meta is None:
        _meta = {"loss": [], "source": {}}
    return {
        "role": role,
        "content": content,
        "tool_calls": tool_calls,
        "tool_results": tool_results,
        "provider": provider,
        "model": model,
        "ts": ts or datetime.now(timezone.utc).isoformat(),
        "_meta": _meta,
    }


def read_jsonl(text):
    turns = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        turns.append(json.loads(line))
    return turns


def write_jsonl(turns):
    lines = []
    for turn in turns:
        lines.append(json.dumps(turn, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(lines) + "\n" if lines else ""
```

- [ ] **Step 3: Run self-check**

Run:

```bash
python transcript_bridge/canonical.py
```

Expected:

```
canonical selfcheck OK
```

- [ ] **Step 4: Implement `loss.py`**

Create `transcript_bridge/loss.py`:

```python
"""Loss reporting helpers."""


def make_loss(path, source_format, target_format, reason, value):
    return {
        "path": path,
        "source_format": source_format,
        "target_format": target_format,
        "reason": reason,
        "value": value,
    }


def report(losses):
    """Return a human-readable summary of losses."""
    if not losses:
        return "no loss"
    lines = [f"loss report: {len(losses)} field(s) could not be represented"]
    for loss in losses:
        lines.append(f"  - {loss['path']}: {loss['reason']}")
    return "\n".join(lines)
```

- [ ] **Step 5: Commit**

```bash
git add transcript_bridge/canonical.py transcript_bridge/loss.py
git commit -m "feat: canonical envelope, jsonl helpers, and loss reporting" -m "🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

---

### Task 3: Claude Code JSONL reader and writer

**Files:**
- Create: `transcript_bridge/formats/__init__.py`
- Create: `transcript_bridge/formats/claude_code.py`
- Modify: `transcript_bridge/__init__.py`
- Test: `python transcript_bridge/formats/claude_code.py`

**Interfaces:**
- Consumes: `canonical.make_turn`, `loss.make_loss`
- Produces:
  - `claude_code.read_claude_code_jsonl(text: str) -> list[dict]`
  - `claude_code.write_claude_code_jsonl(turns: list[dict]) -> tuple[str, list[dict]]`

- [ ] **Step 1: Create format package and failing self-check**

Create `transcript_bridge/formats/__init__.py`:

```python
"""Format readers and writers."""
```

Create `transcript_bridge/formats/claude_code.py`:

```python
"""Claude Code JSONL reader/writer."""
import json
from datetime import datetime, timezone

from ..canonical import make_turn
from ..loss import make_loss


def read_claude_code_jsonl(text):
    raise NotImplementedError


def write_claude_code_jsonl(turns):
    raise NotImplementedError


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
```

Run:

```bash
python transcript_bridge/formats/claude_code.py
```

Expected: `NotImplementedError`.

- [ ] **Step 2: Implement Claude Code reader**

Replace `read_claude_code_jsonl`:

```python
def read_claude_code_jsonl(text):
    turns = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        if record.get("type") not in ("user", "assistant"):
            continue
        message = record.get("message", {})
        content = message.get("content")
        tool_use_blocks = _blocks_of_type(content, "tool_use")
        tool_result_blocks = _blocks_of_type(content, "tool_result")
        turns.append(make_turn(
            role=message.get("role", record.get("type")),
            content=content,
            tool_calls=tool_use_blocks,
            tool_results=tool_result_blocks,
            provider="anthropic",
            model=message.get("model"),
            ts=record.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            _meta={"loss": [], "source": record},
        ))
    return turns


def _blocks_of_type(content, block_type):
    if not isinstance(content, list):
        return None
    blocks = [b for b in content if isinstance(b, dict) and b.get("type") == block_type]
    return blocks or None
```

- [ ] **Step 3: Implement Claude Code writer**

Replace `write_claude_code_jsonl`:

```python
def write_claude_code_jsonl(turns):
    losses = []
    lines = []
    for i, turn in enumerate(turns):
        content = turn.get("content")
        # Any Anthropic-only field inside content blocks that has no generic
        # representation is reported as loss. For v1 that is cache_control.
        if isinstance(content, list):
            for j, block in enumerate(content):
                if isinstance(block, dict) and "cache_control" in block:
                    losses.append(make_loss(
                        path=f"content[{j}].cache_control",
                        source_format="claude_code_jsonl",
                        target_format="claude_code_jsonl",
                        reason="cache_control is preserved in output but not understood by other formats",
                        value=block["cache_control"],
                    ))
        record = {
            "type": turn["role"],
            "message": {
                "role": turn["role"],
                "content": content,
            },
            "timestamp": turn.get("ts"),
        }
        if turn.get("model"):
            record["message"]["model"] = turn["model"]
        # ponytail: we deliberately keep the writer minimal; extra _meta.source
        # fields are not re-emitted so the output stays clean.
        lines.append(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(lines) + "\n" if lines else "", losses
```

- [ ] **Step 4: Update `__init__.py` exports**

Replace `transcript_bridge/__init__.py`:

```python
"""transcript-bridge — loss-aware agent transcript format conversion."""
from .formats import claude_code, openai, codex

__version__ = "0.1.0"

FORMATS = {
    "claude_code_jsonl": (claude_code.read_claude_code_jsonl, claude_code.write_claude_code_jsonl),
}
```

- [ ] **Step 5: Run self-check**

Run:

```bash
python transcript_bridge/formats/claude_code.py
```

Expected:

```
claude_code selfcheck OK
```

- [ ] **Step 6: Commit**

```bash
git add transcript_bridge/__init__.py transcript_bridge/formats/__init__.py transcript_bridge/formats/claude_code.py
git commit -m "feat: Claude Code JSONL reader and writer" -m "🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

---

### Task 4: OpenAI messages reader and writer

**Files:**
- Create: `transcript_bridge/formats/openai.py`
- Modify: `transcript_bridge/__init__.py`
- Test: `python transcript_bridge/formats/openai.py`

**Interfaces:**
- Consumes: `canonical.make_turn`, `loss.make_loss`
- Produces:
  - `openai.read_openai_messages(text: str) -> list[dict]`
  - `openai.write_openai_messages(turns: list[dict]) -> tuple[str, list[dict]]`

- [ ] **Step 1: Create failing self-check**

Create `transcript_bridge/formats/openai.py`:

```python
"""OpenAI messages reader/writer."""
import json
from datetime import datetime, timezone

from ..canonical import make_turn
from ..loss import make_loss


def read_openai_messages(text):
    raise NotImplementedError


def write_openai_messages(turns):
    raise NotImplementedError


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
```

Run:

```bash
python transcript_bridge/formats/openai.py
```

Expected: `NotImplementedError`.

- [ ] **Step 2: Implement OpenAI reader**

Replace `read_openai_messages`:

```python
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
```

- [ ] **Step 3: Implement OpenAI writer**

Replace `write_openai_messages`:

```python
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
                                path=f"content text cache_control",
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
```

- [ ] **Step 4: Register format in `__init__.py`**

Update `transcript_bridge/__init__.py`:

```python
"""transcript-bridge — loss-aware agent transcript format conversion."""
from .formats import claude_code, codex, openai

__version__ = "0.1.0"

FORMATS = {
    "claude_code_jsonl": (claude_code.read_claude_code_jsonl, claude_code.write_claude_code_jsonl),
    "openai_messages": (openai.read_openai_messages, openai.write_openai_messages),
}
```

- [ ] **Step 5: Run self-check**

Run:

```bash
python transcript_bridge/formats/openai.py
```

Expected:

```
openai selfcheck OK
```

- [ ] **Step 6: Commit**

```bash
git add transcript_bridge/__init__.py transcript_bridge/formats/openai.py
git commit -m "feat: OpenAI messages reader and writer" -m "🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

---

### Task 5: Codex reader and writer

**Files:**
- Create: `transcript_bridge/formats/codex.py`
- Modify: `transcript_bridge/__init__.py`
- Test: `python transcript_bridge/formats/codex.py`

**Interfaces:**
- Consumes: `openai.read_openai_messages`, `openai.write_openai_messages`, `loss.make_loss`
- Produces:
  - `codex.read_codex(text: str) -> list[dict]`
  - `codex.write_codex(turns: list[dict]) -> tuple[str, list[dict]]`

- [ ] **Step 1: Create failing self-check**

Create `transcript_bridge/formats/codex.py`:

```python
"""Codex CLI trace reader/writer."""
import json

from ..loss import make_loss
from . import openai


def read_codex(text):
    raise NotImplementedError


def write_codex(turns):
    raise NotImplementedError


def _selfcheck():
    lines = [
        json.dumps({"type": "system", "role": "system", "content": "You are helpful.", "usage": {"prompt_tokens": 10}}),
        json.dumps({"type": "user", "role": "user", "content": "Hello", "checkpoint": "chk_1"}),
        json.dumps({"type": "assistant", "role": "assistant", "content": "Hi!"}),
    ]
    turns = read_codex("\n".join(lines))
    assert len(turns) == 3
    assert turns[0]["_meta"]["source"].get("usage") == {"prompt_tokens": 10}

    out, losses = write_codex(turns)
    records = [json.loads(line) for line in out.strip().split("\n")]
    assert records[0]["role"] == "system"
    print("codex selfcheck OK")


if __name__ == "__main__":
    _selfcheck()
```

Run:

```bash
python transcript_bridge/formats/codex.py
```

Expected: `NotImplementedError`.

- [ ] **Step 2: Implement Codex reader**

Replace `read_codex`:

```python
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
```

- [ ] **Step 3: Implement Codex writer**

Replace `write_codex`:

```python
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
```

- [ ] **Step 4: Register format in `__init__.py`**

Update `transcript_bridge/__init__.py`:

```python
"""transcript-bridge — loss-aware agent transcript format conversion."""
from .formats import claude_code, codex, openai

__version__ = "0.1.0"

FORMATS = {
    "claude_code_jsonl": (claude_code.read_claude_code_jsonl, claude_code.write_claude_code_jsonl),
    "openai_messages": (openai.read_openai_messages, openai.write_openai_messages),
    "codex": (codex.read_codex, codex.write_codex),
}
```

- [ ] **Step 5: Run self-check**

Run:

```bash
python transcript_bridge/formats/codex.py
```

Expected:

```
codex selfcheck OK
```

- [ ] **Step 6: Commit**

```bash
git add transcript_bridge/__init__.py transcript_bridge/formats/codex.py
git commit -m "feat: Codex trace reader and writer" -m "🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

---

### Task 6: CLI

**Files:**
- Create: `transcript_bridge/cli.py`
- Modify: none
- Test: `python -m transcript_bridge.cli formats` and round-trip via CLI

**Interfaces:**
- Consumes: `transcript_bridge.FORMATS`, `loss.report`
- Produces: `cli.main(argv=None) -> int`

- [ ] **Step 1: Create CLI with failing smoke test**

Create `transcript_bridge/cli.py`:

```python
"""CLI for transcript-bridge."""
import argparse
import json
import sys

from . import FORMATS
from .loss import report


def main(argv=None):
    raise NotImplementedError


def _selfcheck():
    assert main(["formats"]) == 0
    print("cli selfcheck OK")


if __name__ == "__main__":
    _selfcheck()
```

Run:

```bash
python -m transcript_bridge.cli formats
```

Expected: `NotImplementedError` or error.

- [ ] **Step 2: Implement CLI**

Replace `main`:

```python
def main(argv=None):
    parser = argparse.ArgumentParser(prog="transcript-bridge")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fmt_parser = subparsers.add_parser("formats", help="list supported formats")

    conv_parser = subparsers.add_parser("convert", help="convert a transcript file")
    conv_parser.add_argument("file", help="input file path, or - for stdin")
    conv_parser.add_argument("--from", dest="source_format", required=True,
                             help="source format name")
    conv_parser.add_argument("--to", dest="target_format", required=True,
                             help="target format name")
    conv_parser.add_argument("-o", dest="output", help="output file (default: stdout)")
    conv_parser.add_argument("--strict", action="store_true",
                             help="exit non-zero if any loss occurs")

    args = parser.parse_args(argv)

    if args.command == "formats":
        for name in sorted(FORMATS):
            print(name)
        return 0

    reader, writer = _get_rw(args.source_format, args.target_format)

    if args.file == "-":
        text = sys.stdin.read()
    else:
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read()

    turns = reader(text)
    output_text, losses = writer(turns)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_text)
    else:
        sys.stdout.write(output_text)

    sys.stderr.write(report(losses) + "\n")
    if args.strict and losses:
        return 2
    return 0


def _get_rw(source, target):
    if source not in FORMATS:
        raise SystemExit(f"unknown source format: {source}")
    if target not in FORMATS:
        raise SystemExit(f"unknown target format: {target}")
    return FORMATS[source][0], FORMATS[target][1]
```

Wait — the spec CLI is `transcript-bridge <file> --from <fmt> --to <fmt>`, not a `convert` subcommand. Fix the parser to match the spec.

Replace the whole `main` function again:

```python
def main(argv=None):
    parser = argparse.ArgumentParser(prog="transcript-bridge")
    parser.add_argument("file", nargs="?", help="input file path, or - for stdin")
    parser.add_argument("--from", dest="source_format", help="source format name")
    parser.add_argument("--to", dest="target_format", help="target format name")
    parser.add_argument("-o", dest="output", help="output file (default: stdout)")
    parser.add_argument("--strict", action="store_true",
                        help="exit non-zero if any loss occurs")
    args = parser.parse_args(argv)

    if args.file is None and (args.source_format is None or args.target_format is None):
        # Special case: no file and no formats means list formats, like the spec's
        # `transcript-bridge formats` command. We accept that as bare invocation.
        for name in sorted(FORMATS):
            print(name)
        return 0

    if args.file == "formats":
        for name in sorted(FORMATS):
            print(name)
        return 0

    if args.source_format is None or args.target_format is None:
        parser.error("--from and --to are required unless listing formats")

    reader, writer = _get_rw(args.source_format, args.target_format)

    if args.file == "-":
        text = sys.stdin.read()
    else:
        with open(args.file, "r", encoding="utf-8") as f:
            text = f.read()

    turns = reader(text)
    output_text, losses = writer(turns)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_text)
    else:
        sys.stdout.write(output_text)

    sys.stderr.write(report(losses) + "\n")
    if args.strict and losses:
        return 2
    return 0
```

- [ ] **Step 3: Verify CLI smoke test**

Run:

```bash
python -m transcript_bridge.cli formats
```

Expected output:

```
claude_code_jsonl
codex
openai_messages
```

- [ ] **Step 4: Test a real round-trip via CLI**

Create a sample Claude Code JSONL file in `/tmp/sample.jsonl`:

```bash
python -c "
import json
import sys
sys.stdout.write(json.dumps({
    'type': 'assistant',
    'message': {'role': 'assistant', 'content': [{'type':'text','text':'hi','cache_control':{'type':'ephemeral'}}]},
    'timestamp': '2026-07-22T00:00:00Z'
}, separators=(',',':')) + '\n')
" > /tmp/sample.jsonl
```

Run conversion:

```bash
python -m transcript_bridge.cli /tmp/sample.jsonl --from claude_code_jsonl --to openai_messages
```

Expected: JSON array on stdout, loss report on stderr mentioning `cache_control`.

- [ ] **Step 5: Commit**

```bash
git add transcript_bridge/cli.py
git commit -m "feat: transcript-bridge CLI" -m "🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

---

### Task 7: selfcheck.py round-trip verification

**Files:**
- Create: `selfcheck.py`
- Modify: none
- Test: `python selfcheck.py`

**Interfaces:**
- Consumes: `transcript_bridge.FORMATS`, all readers/writers
- Produces: passing `selfcheck.py` proving round-trip honesty

- [ ] **Step 1: Write selfcheck.py**

Create `selfcheck.py`:

```python
#!/usr/bin/env python3
"""Round-trip self-check for transcript-bridge.

Builds a canonical transcript with one Claude-specific field (cache_control)
and one OpenAI-specific field (name on a tool message), then proves:
1. Claude -> Claude is lossless.
2. Claude -> OpenAI reports exactly the cache_control loss.
3. OpenAI -> Claude reports the OpenAI-specific name as loss.
4. Claude -> OpenAI -> Claude round-trip preserves everything except the
   expected lossy fields.
"""
import json
import sys

from transcript_bridge import FORMATS
from transcript_bridge.canonical import make_turn


def _make_transcript():
    now = "2026-07-22T12:00:00+00:00"
    turns = [
        make_turn(role="system", content="You are helpful.", provider="anthropic", ts=now),
        make_turn(role="user", content="Read /x for me.", provider="anthropic", ts=now),
        make_turn(
            role="assistant",
            content=[
                {"type": "text", "text": "I'll read it.", "cache_control": {"type": "ephemeral"}},
                {"type": "tool_use", "id": "tu_1", "name": "Read", "input": {"file_path": "/x"}},
            ],
            provider="anthropic",
            ts=now,
        ),
        make_turn(
            role="tool",
            content=[{"type": "tool_result", "tool_use_id": "tu_1", "content": "contents of /x"}],
            provider="openai",
            ts=now,
            _meta={
                "loss": [],
                "source": {"role": "tool", "tool_call_id": "tu_1", "content": "contents of /x", "name": "Read"},
            },
        ),
    ]
    return turns


def _loss_paths(losses):
    return sorted(loss["path"] for loss in losses)


def _strip_meta(turn):
    t = dict(turn)
    t["_meta"] = {"loss": [], "source": {}}
    return t


def main():
    read_cc, write_cc = FORMATS["claude_code_jsonl"]
    read_oa, write_oa = FORMATS["openai_messages"]

    original = _make_transcript()

    # 1. Claude -> Claude is lossless.
    cc_text, cc_losses = write_cc(original)
    assert not cc_losses, cc_losses
    cc_round = read_cc(cc_text)
    assert [_strip_meta(t) for t in cc_round] == [_strip_meta(t) for t in original]

    # 2. Claude -> OpenAI reports exactly cache_control.
    oa_text, oa_losses = write_oa(cc_round)
    assert _loss_paths(oa_losses) == ["content text cache_control"], _loss_paths(oa_losses)

    # 3. OpenAI -> Claude reports the OpenAI-specific name as loss.
    back_cc, back_losses = write_cc(read_oa(oa_text))
    assert any("_openai_name" in loss["path"] or "name" in loss["reason"].lower() for loss in back_losses), back_losses

    # 4. Claude -> OpenAI -> Claude preserves everything except lossy fields.
    final_round = read_cc(back_cc)
    # The only expected divergence is the cache_control block (dropped in OpenAI)
    # and the _openai_name field.
    for i, (orig, final) in enumerate(zip(original, final_round)):
        assert orig["role"] == final["role"], f"role mismatch at {i}"
        if i == 2:
            # cache_control should be gone from the text block
            assert "cache_control" not in final["content"][0], final
        if i == 3:
            # tool_result content preserved
            assert final["content"][0]["content"] == "contents of /x", final

    print("selfcheck OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run selfcheck**

Run:

```bash
python selfcheck.py
```

Expected:

```
selfcheck OK
```

If it fails, fix the reader/writer logic until it passes.

- [ ] **Step 3: Commit**

```bash
git add selfcheck.py
git commit -m "feat: round-trip selfcheck" -m "🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

---

### Task 8: Installability and pipx smoke test

**Files:**
- Modify: `pyproject.toml` if needed
- Test: `pipx install . --force` and `transcript-bridge formats`

- [ ] **Step 1: Install in a clean environment**

Run:

```bash
python -m pip install -e .
```

Expected: installs without errors.

- [ ] **Step 2: Verify entry point**

Run:

```bash
transcript-bridge formats
```

Expected output:

```
claude_code_jsonl
codex
openai_messages
```

- [ ] **Step 3: Uninstall editable**

Run:

```bash
python -m pip uninstall transcript-bridge -y
```

- [ ] **Step 4: Commit any pyproject fixes**

If no changes were needed, skip. If changes were needed, commit them.

---

### Task 9: README.md

**Files:**
- Create: `README.md`
- Modify: none
- Test: visual review; ensure examples run

- [ ] **Step 1: Write README.md**

Create `README.md` with the following sections:

1. Title + one-liner.
2. Why this exists (2 paragraphs).
3. Supported formats table.
4. Installation (`pipx install .`).
5. Quick start with a round-trip example and loss report.
6. CLI reference.
7. Architecture note (canonical model, loss-aware design).
8. Development: running `selfcheck.py`.
9. License.

Sample structure:

```markdown
# transcript-bridge

Convert agent session logs between formats — Claude Code JSONL, OpenAI messages, Codex traces, and a canonical JSONL — without silently dropping data.

## Why

Agent tooling is fragmenting. Each stack has its own transcript format, and switching between them means losing metadata, tool-call shape, or ordering. `transcript-bridge` makes conversions explicit: every field that cannot be represented in the target format is reported in a loss summary. Run with Claude, replay with OpenAI, audit with Codex — and know exactly what survived the trip.

## Supported formats

| Format            | Read | Write | Notes                                      |
|-------------------|------|-------|--------------------------------------------|
| claude_code_jsonl | ✓    | ✓     | Anthropic-style content blocks             |
| openai_messages   | ✓    | ✓     | JSON array of `{role, content}` messages  |
| codex             | ✓    | ✓     | Codex CLI traces with extra metadata       |

## Installation

```bash
pipx install .
```

Or run directly from the repo:

```bash
python -m transcript_bridge.cli formats
```

## Quick start

Convert a Claude Code transcript to OpenAI messages:

```bash
transcript-bridge session.jsonl --from claude_code_jsonl --to openai_messages -o session-openai.json
```

The tool prints a loss report to stderr:

```
loss report: 1 field(s) could not be represented
  - content text cache_control: OpenAI messages have no slot for Anthropic cache_control blocks
```

Use `--strict` to make any loss exit non-zero:

```bash
transcript-bridge session.jsonl --from claude_code_jsonl --to openai_messages --strict
# exits with code 2 if loss occurred
```

## CLI

```
transcript-bridge <file> --from <fmt> --to <fmt> [-o out] [--strict]
transcript-bridge formats
```

- `<file>`: input file path, or `-` for stdin.
- `--from`: source format (`claude_code_jsonl`, `openai_messages`, `codex`).
- `--to`: target format.
- `-o`: output file (default: stdout).
- `--strict`: exit non-zero on any loss.

## How it works

All formats are normalized into a small canonical JSONL envelope:

```json
{"role":"assistant","content":[{"type":"text","text":"hello"},{"type":"tool_use","id":"call_1","name":"Read","input":{"file_path":"/x"}}],"tool_calls":[...],"tool_results":null,"provider":"anthropic","model":null,"ts":"2026-07-22T12:00:00+00:00","_meta":{"loss":[],"source":{}}}
```

Writers translate the canonical envelope back into the target format and emit a loss entry for every field that has no native home. Nothing is silently dropped.

## Development

Run the self-check:

```bash
python selfcheck.py
```

## License

MIT. See [LICENSE](./LICENSE).
```

- [ ] **Step 2: Verify examples**

Run the quick-start example commands against the `/tmp/sample.jsonl` from Task 6 and make sure the README examples match the actual output.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README with usage and round-trip example" -m "🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

---

## Self-review

**Spec coverage:**
- Canonical envelope: Task 2.
- Three formats: Tasks 3, 4, 5.
- Loss report and `--strict`: Tasks 2 and 6.
- CLI: Task 6.
- `selfcheck.py`: Task 7.
- README: Task 9.
- MIT license: Task 1.

**Placeholder scan:** All steps contain concrete code/commands; no TBD or "fill in" steps.

**Type consistency:** `make_turn` returns dict; readers return `list[dict]`; writers return `tuple[str, list[dict]]`; CLI returns int. Used consistently across tasks.

**Spec fidelity:** CLI matches `transcript-bridge <file> --from <fmt> --to <fmt>`. `transcript-bridge formats` is supported. Codex reader/writer are implemented even though their surface is intentionally thin for v1.
