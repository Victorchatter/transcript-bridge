# Changelog

## 0.3.0

- Added provider format packs for Gemini, LangSmith, Langfuse, and Ollama.
- Each new format includes an honest reader and writer with `--strict`-aware loss reporting.
- CLI `formats` subcommand now shows a one-line description for every format.
- Updated README with supported-formats table, conversion matrix, and examples for the new formats.

## 0.1.0

- Initial release with Claude Code JSONL, OpenAI messages, Codex trace, and agent-vcr tape (read-only) support.
- Loss-aware canonical intermediate format and `--strict` failure mode.
