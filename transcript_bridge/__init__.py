"""transcript-bridge — loss-aware agent transcript format conversion."""
from .formats import claude_code, codex, openai, tape

__version__ = "0.1.0"

FORMATS = {
    "claude_code_jsonl": (claude_code.read_claude_code_jsonl, claude_code.write_claude_code_jsonl),
    "openai_messages": (openai.read_openai_messages, openai.write_openai_messages),
    "codex": (codex.read_codex, codex.write_codex),
    # Read-only: write_tape raises. A tape records wire traffic that
    # canonical turns do not carry, so writing one would fabricate it.
    "tape": (tape.read_tape, tape.write_tape),
}
