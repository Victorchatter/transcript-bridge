# transcript-bridge design spec

**Date:** 2026-07-22  
**Status:** Approved for implementation  
**Scope:** v1 — convert agent session logs between Claude Code JSONL, OpenAI messages, Codex traces, and a canonical JSONL.

## One-liner

Convert agent session logs between formats: Claude Code JSONL ↔ OpenAI messages ↔ Codex traces ↔ a canonical JSONL. Lossy fields are recorded in a sidecar `_meta` field and reported at the CLI; `--strict` fails on any loss.

## Why it doesn't exist

engramkit handles *memory*, not raw transcript format conversion. As agents multiply, format lock-in is real and nothing converts cleanly. Sibling projects (agent-vcr, agent-checkpoint) define their own canonical envelopes for recording/resuming; transcript-bridge borrows the shape but is independent, because its purpose is *loss-aware translation*, not recording or resuming.

## Goals and non-goals

**Goals (v1):**
- Read and write three formats: `claude_code_jsonl`, `openai_messages`, `codex`.
- Define a small canonical intermediate JSONL that can be converted into any supported format.
- Report every field that cannot be represented in the target format.
- Provide a single-file self-check that proves round-trip honesty.
- Ship as `pipx install .`, stdlib only, offline, read-only on inputs, no telemetry.

**Non-goals (v1):**
- Streaming/incremental conversion.
- Binary attachment extraction.
- Additional formats (Gemini, etc.).
- Merging multiple runs.

## Canonical envelope

One JSONL line per conversation turn:

```json
{
  "role": "user|assistant|system|tool",
  "content": "<string or array of blocks>",
  "tool_calls": [...],
  "tool_results": [...],
  "provider": "anthropic|openai|codex|...",
  "model": "...",
  "ts": "...",
  "_meta": {
    "loss": [...],
    "source": {...}
  }
}
```

### Fields

- `role` — turn role. Mirrors OpenAI roles plus Anthropic's block-based model. Allowed: `user`, `assistant`, `system`, `tool`.
- `content` — canonical truth. Either a plain string or an array of Anthropic-style content blocks: `{"type": "text", "text": "..."}`, `{"type": "tool_use", "id": "...", "name": "...", "input": {...}}`, `{"type": "tool_result", "tool_use_id": "...", "content": "...", "is_error": false}`.
- `tool_calls` — normalized view of `tool_use` blocks in this turn. Derived from `content`, present for convenience.
- `tool_results` — normalized view of `tool_result` blocks in this turn. Derived from `content`, present for convenience.
- `provider` — source provider hint, e.g. `anthropic`, `openai`, `codex`.
- `model` — model name if known.
- `ts` — ISO-8601 timestamp.
- `_meta` — always present. Holds loss data and source-format metadata.
  - `_meta.loss` — list of loss entries produced when this turn was last written to a target format.
  - `_meta.source` — the original source record or format name, preserved for debugging.

### Design decisions

- `content` as block arrays is the canonical truth because Anthropic content blocks capture both text and tool interactions in one ordered list. OpenAI's separate `tool_calls`/`role: tool` representation can be derived from this ordering.
- System turns and `cache_control` blocks are preserved in their original order inside `content`. Writers decide how faithfully they can reproduce that order in the target format.
- `_meta` is always present so consumers have a stable contract, even when it is empty.

## Format readers and writers

A registry maps format names to `(reader, writer)` callables.

```python
FORMATS = {
    "claude_code_jsonl": (read_claude_code_jsonl, write_claude_code_jsonl),
    "openai_messages": (read_openai_messages, write_openai_messages),
    "codex": (read_codex, write_codex),
}
```

All readers:
- Accept the raw input text.
- Return `list[CanonicalTurn]`.
- Normalize tool interactions into the canonical block model.
- Copy unknown/loss-prone source fields into `_meta.source` so they can be reported or re-emitted later.

All writers:
- Accept `list[CanonicalTurn]`.
- Return `(text: str, losses: list[LossEntry])`.
- Translate canonical blocks into the target format.
- Emit a loss entry for every canonical field that has no native home in the target format.

### Claude Code JSONL

**Reader:** Reads JSONL where each line is `{"type": "user|assistant", "message": {"role": ..., "content": ...}, "timestamp": ...}`. The `message.content` may be a string or a list of Anthropic content blocks. Tool-use and tool-result blocks stay in `content`. The reader also copies the original record into `_meta.source`.

**Writer:** Writes the same JSONL shape. Since the canonical model is already close to Anthropic's block model, losses are minimal: only fields like `cache_control` that cannot be represented are reported as loss.

### OpenAI messages

**Reader:** Reads a JSON array of `{role, content, tool_calls, tool_call_id, name}` messages.

- `role: assistant` with `tool_calls` → becomes an `assistant` turn whose `content` includes `tool_use` blocks, plus a `tool_calls` derived view.
- `role: tool` with `tool_call_id` and `content` → becomes a `tool` turn whose `content` includes one `tool_result` block.
- `role: system` → `system` turn.
- The `name` field on `function` role messages has no Anthropic home; it goes into `_meta.source` and is reported as loss when writing to Anthropic formats.

**Writer:** Writes a JSON array of messages.

- `tool_use` blocks in an `assistant` turn become `tool_calls` entries; the `content` field is set to the remaining text blocks (or `None` if the turn is only tool calls).
- `tool_result` blocks become `role: tool` messages with `tool_call_id`.
- System turns become `role: system` messages.
- Anthropic-only fields (`cache_control`, `thinking`, etc.) are reported as loss.

### Codex

**Reader:** Reads Codex CLI trace JSONL. Codex records are OpenAI-message-like but carry extra keys such as `usage`, `checkpoint`, `command`, `cwd`, `metadata`, and nested event structure. The reader normalizes message-like records into canonical turns and stores the full original record in `_meta.source`.

**Writer:** Writes Codex trace JSONL, preserving message fields that map cleanly. Codex-specific keys are emitted as loss unless the target format has a natural slot for them.

## Loss report

A loss entry has the shape:

```python
{
    "path": "message.content[0].cache_control",
    "source_format": "claude_code_jsonl",
    "target_format": "openai_messages",
    "reason": "OpenAI messages have no slot for Anthropic cache_control blocks",
    "value": {...},
}
```

- `path` — JSON-pointer-ish path to the lost field inside the canonical turn or source record.
- `source_format` — the format that originally held the value.
- `target_format` — the format being written.
- `reason` — human-readable explanation.
- `value` — the actual value that was dropped or flattened.

The CLI prints the loss report to stderr after writing. With `--strict`, a non-empty loss list causes exit code 2. A successful conversion with no losses exits 0. Invalid arguments or read errors exit 1.

## CLI

```
transcript-bridge <file> --from <fmt> --to <fmt> [-o out] [--strict]
transcript-bridge formats
```

- `<file>` — input file path; use `-` for stdin.
- `--from` — source format name.
- `--to` — target format name.
- `-o` — output file; omitted means stdout.
- `--strict` — exit non-zero if any loss occurs.
- `formats` — list supported format names and a one-line description of each.

The CLI loads the whole input into memory, runs the reader, runs the writer, writes the output, and prints the loss report to stderr. This is intentionally simple for v1.

## Project structure

```
transcript-bridge/
  transcript_bridge/
    __init__.py          # exports main helpers and FORMATS registry
    canonical.py         # CanonicalTurn, helpers, jsonl read/write
    loss.py              # LossEntry, loss helpers
    cli.py               # argparse CLI
    formats/
      __init__.py        # registers all formats
      claude_code.py     # reader + writer for Claude Code JSONL
      openai.py          # reader + writer for OpenAI messages
      codex.py           # reader + writer for Codex traces
  selfcheck.py           # round-trip + loss-report verification
  pyproject.toml         # pipx-installable, stdlib only
  README.md              # usage + round-trip + loss-report example
  LICENSE                # MIT
  docs/superpowers/specs/2026-07-22-transcript-bridge-design.md
```

## Self-check

`selfcheck.py` proves round-trip honesty with no external dependencies:

1. Build a canonical transcript containing:
   - one Claude-specific field (`cache_control` on a text block),
   - one OpenAI-specific field (`name` on a `function`/`tool` message).
2. Write it as Claude Code JSONL.
3. Read it back as Claude Code JSONL and assert it equals the original canonical transcript except for `_meta` source hints.
4. Convert Claude → OpenAI messages and capture the loss report. Assert the loss report contains exactly the Claude-specific field.
5. Convert OpenAI → Claude and assert the OpenAI-specific `name` is now reported as loss (because Anthropic tool results have no `name` slot).
6. Convert the OpenAI output back to Claude and assert the final transcript matches the original except for the expected lossy fields.

## Implementation notes

- Python version: 3.10+ (match other sibling projects; type hints allowed).
- Stdlib only. No `pydantic`, no `click`, no `rich`.
- `# ponytail:` comments mark deliberate simplifications.
- Round-trip honesty is more important than perfect fidelity to every exotic field. Unknown fields are loss-reported, not silently dropped.
- The canonical model is a *sibling* to agent-checkpoint's envelope, not a fork or a dependency. It borrows the same shape (`role`, `content`, `tool_calls`, `tool_results`, `provider`, `model`, `ts`) but adds `_meta` and treats block-array content as the canonical truth.
