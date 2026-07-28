"""transcript-bridge — loss-aware agent transcript format conversion."""
from .formats import claude_code, codex, gemini, langfuse, langsmith, ollama, openai, tape

__version__ = "0.3.0"

DESCRIPTIONS = {
    "claude_code_jsonl": "Anthropic-style content blocks (text, tool_use, tool_result)",
    "openai_messages": "JSON array of {role, content, tool_calls} messages",
    "codex": "Codex CLI traces with extra metadata (usage, checkpoint, etc.)",
    "gemini": "Google Gemini contents[] format with functionCall/functionResponse parts",
    "langsmith": "LangSmith trace export of LLM runs with child tool runs",
    "langfuse": "Langfuse trace export of GENERATION and SPAN observations",
    "ollama": "Ollama /api/chat request/response message array",
    "tape": "agent-vcr wire-level tape (read-only)",
}

FORMATS = {
    "claude_code_jsonl": (claude_code.read_claude_code_jsonl, claude_code.write_claude_code_jsonl),
    "openai_messages": (openai.read_openai_messages, openai.write_openai_messages),
    "codex": (codex.read_codex, codex.write_codex),
    "gemini": (gemini.read_gemini, gemini.write_gemini),
    "langsmith": (langsmith.read_langsmith, langsmith.write_langsmith),
    "langfuse": (langfuse.read_langfuse, langfuse.write_langfuse),
    "ollama": (ollama.read_ollama, ollama.write_ollama),
    # Read-only: write_tape raises. A tape records wire traffic that
    # canonical turns do not carry, so writing one would fabricate it.
    "tape": (tape.read_tape, tape.write_tape),
}
