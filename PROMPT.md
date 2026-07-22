# transcript-bridge — bootstrap session prompt

You are bootstrapping a new open-source project. Follow the full process: `superpowers:brainstorming` → lock design → write spec to `docs/superpowers/specs/YYYY-MM-DD-transcript-bridge-design.md` → commit → `superpowers:writing-plans` (approve) → implement via `superpowers:executing-plans`. Verify with `selfcheck.py` before done.

## Idea (one-liner)
Convert agent session logs between formats: Claude Code JSONL ↔ OpenAI messages ↔ Codex traces ↔ a canonical JSONL. Enables "run with Claude, debug/replay/analyze with another stack." Lossy where formats don't have a native slot (e.g. Anthropic `cache_control` has no OpenAI home) — bridge records the loss in a sidecar `_meta` field and prints a loss report, never silently drops information.

## Why it doesn't exist
engramkit handles *memory*, not raw transcript format conversion. As agents multiply, format lock-in is real and nothing converts cleanly.

## Hard constraints
- Python, `pipx install .`. Fully local/offline, read-only on inputs, no telemetry.
- Format I/O via a small plugin-ish reader/writer registry, but ship the first three readers+writers in v1 (Claude Code JSONL, OpenAI messages, Codex) — no dynamic plugin loading, just a table of `(format_name, reader, writer)` functions.
- Canonical intermediate model (the "canonical JSONL") shared with agent-vcr/agent-checkpoint where free — reuse, don't fork.
- Round-trip honesty: `transcript-bridge <in> --from X --to Y` prints a loss report (which fields couldn't be represented in Y). Add `--strict` to exit nonzero on any loss.
- CLI: `transcript-bridge <file> --from <fmt> --to <fmt> [-o out] [--strict]`; `transcript-bridge formats` lists supported formats.
- Small and sharp. Ponytail: stdlib only, shortest working diff, no unrequested abstractions. `# ponytail:` comments on simplifications.
- One `selfcheck.py`: a canonical transcript with one Claude-specific and one OpenAI-specific field; convert Claude→OpenAI→Claude; assert the round-trip preserves everything *except* the lossy fields and that the loss report lists exactly those.
- License MIT. README with a round-trip + loss-report example.

## Scope / YAGNI (v1)
Ship: 3 formats (Claude Code JSONL, OpenAI messages, Codex) + canonical, loss report, `--strict`. Out: streaming/incremental, binary attachment extraction, more formats (Gemini, etc. — follow-up), merge of multiple runs.

## Inputs to lock during brainstorming
- Canonical intermediate: reuse agent-vcr's envelope or define a sibling? (recommend reuse where free.)
- How tool calls/results map across Anthropic's `tool_use`/`tool_result` content blocks vs OpenAI's `tool_calls`/`tool` role (this is the core conversion logic — nail it).
- Whether to preserve ordering of cache-control / system blocks exactly.

One of 10 sibling local-first agent-tooling projects. Keep it small and ship it.