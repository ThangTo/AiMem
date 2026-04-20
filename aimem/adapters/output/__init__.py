"""
Output Adapters - Chuyển đổi UniversalSession sang format của các agent đích.
"""

from aimem.models import UniversalSession, Message


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _is_noise_message(msg: Message) -> bool:
    """Kiểm tra message có phải là noise không (API errors, HTML, system noise)."""
    content = msg.content.strip()
    if not content:
        return True
    # Skip system API errors
    if msg.role == "system" and ("API Error" in content or content.startswith("[System:")):
        return True
    # Skip empty tool results
    if content in ("[Tool: ]", "Tool: ", "[]", ""):
        return True
    return False


def _should_skip_tool_result(content: str) -> bool:
    """
    Skip tool result / message content that is pure noise:
    - Mostly pip/npm upgrade notices
    - External-tool failure dumps (WeasyPrint, GTK, npm, pip) — not user's code
    - Long HTML error pages from external tools
    """
    c = content.strip()
    if not c:
        return True

    lines = c.split("\n")
    lower = c.lower()

    # Skip if >70% is pip/npm upgrade notices
    notice_lines = sum(1 for l in lines if "[notice]" in l.lower())
    if notice_lines > max(len(lines) * 0.7, 3):
        return True

    # External-tool failure keywords — skip regardless of length
    if any(kw in lower for kw in [
        "weasyprint could not import",
        "external libraries",
        "follow the installation steps",
        "doc.courtbouillon.org/weasyprint",
        "gtk3 libraries",
        "pangocairo",
        "libpangocairo",
        "gi.repository",
        "npm err!",
        "enoent: no such file",
    ]):
        return True

    # Skip if primarily an error exit-code report + external tool failure
    # (Exit code + GTK/WeasyPrint/stack trace = external tool noise)
    has_exit_code = "[error]" in lower or "exit code" in lower
    has_external_trace = any(kw in lower for kw in [
        "follow the installation", "installation steps", "troubleshooting",
        "gtk", "pango", "cairo", "pangocairo",
    ])
    if has_exit_code and has_external_trace:
        return True

    # Skip long external-tool HTML/stack dumps
    if len(c) > 200:
        if "<html>" in lower or "<!doctype" in lower:
            return True
        # Stack traces from external tools
        trace_count = sum(
            1 for l in lines
            if l.strip().startswith(("at ", "File ", "  ", "Traceback", "Error:"))
            and len(l.strip()) < 120
        )
        if trace_count > 10 and len(c) > 1500:
            return True

    return False


def _trim_message(content: str, max_len: int = 600) -> str:
    """
    Trim message content for readability.
    - Truncates long HTML/error dumps to a meaningful summary.
    - Replaces pip/npm boilerplate notices with a one-liner.
    """
    total_len = len(content)

    # Step 1: Replace pip/npm upgrade notices with a summary
    lower = content.lower()
    if "[notice]" in lower and ("new release" in lower or "pip is available" in lower or "npm is available" in lower):
        lines = content.split("\n")
        notice_lines = []
        normal_lines = []
        for line in lines:
            l = line.lower()
            if "[notice]" in l and ("new release" in l or "pip is available" in l or "npm is available" in l):
                notice_lines.append(line)
            else:
                normal_lines.append(line)
        if normal_lines and len(normal_lines) < len(lines):
            pkg = ""
            for nl in notice_lines:
                if "new release of" in nl.lower():
                    parts = nl.split()
                    for i, p in enumerate(parts):
                        if p in ("pip", "npm", "node", "python"):
                            pkg = parts[i]
                            break
            content = "\n".join(normal_lines)
            if pkg:
                content += f"\n[... {len(notice_lines)} pip/npm upgrade notices omitted]"

    # Step 2: Truncate if still too long
    if len(content) <= max_len:
        return content

    # Step 3: If contains HTML error page, extract the meaningful part
    lower = content.lower()
    if "<html>" in lower or "<!doctype" in lower:
        # Extract meaningful text before HTML block
        lines = content.split("\n")
        meaningful = []
        in_html = False
        for line in lines:
            l = line.lower()
            if "<html>" in l or "<!doctype" in l:
                in_html = True
            if not in_html:
                meaningful.append(line)

        result = "\n".join(meaningful).strip()
        if result:
            return result + f"\n[... tool output truncated ({total_len} chars, HTML error)]"
        return f"[HTML error output truncated ({total_len} chars)]"

    # Step 4: Simple truncation
    return content[:max_len] + f"\n[... truncated, {total_len - max_len} more chars]"


def _filter_messages(messages: list[Message], limit: int | None = None) -> list[Message]:
    """Filter noise messages and optionally limit count."""
    filtered = [m for m in messages if not _is_noise_message(m)]
    # Also filter from the front (older messages) if too many
    if limit and len(filtered) > limit:
        filtered = filtered[-limit:]
    return filtered


# ─────────────────────────────────────────────────────────────
# Markdown Output (Universal - dán vào bất kỳ đâu)
# ─────────────────────────────────────────────────────────────

class MarkdownOutput:
    """Format session thành Markdown — dùng được cho mọi agent."""

    @staticmethod
    def transform(session: UniversalSession, include_system: bool = False) -> str:
        lines = []

        # Header
        lines.append("# AI Context Transfer")
        lines.append("")
        if session.metadata.source_agent:
            lines.append(f"**Source:** {session.metadata.source_agent.upper()}")
        if session.metadata.project_path:
            lines.append(f"**Project:** `{session.metadata.project_path}`")
        if session.metadata.model:
            lines.append(f"**Model:** {session.metadata.model}")
        if session.metadata.original_session_id:
            lines.append(f"**Session:** `{session.metadata.original_session_id}`")
        lines.append("")

        # Compressed info (nếu có)
        if session.compressed:
            lines.append("## Current Goal")
            lines.append(session.compressed.current_goal)
            lines.append("")

            if session.compressed.key_decisions:
                lines.append("## Key Decisions")
                for d in session.compressed.key_decisions:
                    lines.append(f"- {d}")
                lines.append("")

            if session.compressed.todo_list:
                lines.append("## Todo List")
                for t in session.compressed.todo_list:
                    lines.append(f"- [ ] {t}")
                lines.append("")

            if session.compressed.latest_code:
                lines.append("## Latest Code")
                for snippet in session.compressed.latest_code[:5]:
                    lines.append(f"**{snippet.path or 'snippet'}:**")
                    lines.append(f"```{snippet.language or ''}")
                    lines.append(snippet.content[:500])
                    lines.append("```")
                    lines.append("")

            if session.compressed.current_errors:
                lines.append("## Current Errors")
                for err in session.compressed.current_errors:
                    lines.append(f"```\n{err}\n```")
                lines.append("")

        # Full conversation
        lines.append("## Conversation History")
        lines.append("")

        msgs_to_show = session.messages
        if not include_system:
            msgs_to_show = _filter_messages(msgs_to_show)

        for msg in msgs_to_show:
            content = msg.content.strip()
            if not content:
                continue
            if _is_noise_message(msg):
                continue
            lines.append(f"**{msg.role.upper()}:**")
            lines.append(content)
            lines.append("")

        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# Claude Format
# ─────────────────────────────────────────────────────────────

class ClaudeOutput:
    """Format session cho Claude Code CLI."""

    @staticmethod
    def transform(session: UniversalSession) -> str:
        lines = []

        # System prompt
        lines.append("# Previous Context")
        lines.append("")
        lines.append("Here's the context from a previous session that I was working on:")
        lines.append("")

        if session.metadata.project_path:
            lines.append(f"Project: `{session.metadata.project_path}`")
        if session.metadata.original_session_id:
            lines.append(f"Previous Session: `{session.metadata.original_session_id}`")
        lines.append("")

        # Compressed
        if session.compressed:
            if session.compressed.current_goal:
                lines.append(f"**Goal:** {session.compressed.current_goal}")
            if session.compressed.key_decisions:
                lines.append("**Decisions:**")
                for d in session.compressed.key_decisions:
                    lines.append(f"- {d}")
            if session.compressed.todo_list:
                lines.append("**Todo:**")
                for t in session.compressed.todo_list:
                    lines.append(f"- [ ] {t}")
        else:
            # Raw messages (last 10), skip noise
            lines.append("**Recent messages:**")
            recent = _filter_messages(session.messages, limit=10)
            for msg in recent:
                content = msg.content.strip()
                if not content or _is_noise_message(msg):
                    continue
                if _should_skip_tool_result(content):
                    continue
                lines.append(f"\n__{msg.role}__:\n{_trim_message(content, 400)}")

        lines.append("")
        lines.append("---")
        lines.append("Please continue from where we left off.")

        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# Gemini Format
# ─────────────────────────────────────────────────────────────

class GeminiOutput:
    """Format session cho Gemini CLI."""

    @staticmethod
    def transform(session: UniversalSession) -> str:
        lines = []

        lines.append("## Previous Context")
        lines.append("")
        lines.append("Continuing from previous session:")
        lines.append("")

        if session.metadata.project_path:
            lines.append(f"Project: `{session.metadata.project_path}`")

        if session.compressed:
            lines.append(f"\n**Current Goal:** {session.compressed.current_goal}")

            if session.compressed.key_decisions:
                lines.append("\n**Decisions made:**")
                for d in session.compressed.key_decisions:
                    lines.append(f"- {d}")

            if session.compressed.latest_code:
                lines.append("\n**Latest code:**")
                for snippet in session.compressed.latest_code[:3]:
                    path = snippet.path or "file"
                    lines.append(f"\n{path}:")
                    lines.append(f"```{snippet.language or ''}")
                    lines.append(snippet.content[:300])
                    lines.append("```")

            if session.compressed.current_errors:
                lines.append("\n**Errors:**")
                for err in session.compressed.current_errors:
                    lines.append(f"```\n{err}\n```")

            if session.compressed.todo_list:
                lines.append("\n**Todo:**")
                for t in session.compressed.todo_list:
                    lines.append(f"- [ ] {t}")
        else:
            lines.append("\n**Recent conversation:**")
            recent = _filter_messages(session.messages, limit=8)
            for msg in recent:
                content = msg.content.strip()
                if not content or _is_noise_message(msg):
                    continue
                if _should_skip_tool_result(content):
                    continue
                lines.append(f"\n__{msg.role}__:\n{_trim_message(content, 400)}")

        lines.append("\n\n---\nContinue from where we left off.")

        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# OpenCode Format
# ─────────────────────────────────────────────────────────────

class OpenCodeOutput:
    """Format session cho OpenCode CLI."""

    @staticmethod
    def transform(session: UniversalSession) -> str:
        lines = []

        lines.append("# Previous Session Context")
        lines.append("")
        lines.append("Continuing from a previous session:")
        lines.append("")

        if session.metadata.project_path:
            lines.append(f"Project: `{session.metadata.project_path}`")

        if session.compressed:
            if session.compressed.current_goal:
                lines.append(f"\n**Goal:** {session.compressed.current_goal}")
            if session.compressed.key_decisions:
                lines.append("\n**Decisions:**")
                for d in session.compressed.key_decisions:
                    lines.append(f"- {d}")
            if session.compressed.todo_list:
                lines.append("\n**Todo:**")
                for t in session.compressed.todo_list:
                    lines.append(f"- [ ] {t}")
        else:
            lines.append("\n**Recent conversation:**")
            recent = _filter_messages(session.messages, limit=10)
            for msg in recent:
                content = msg.content.strip()
                if not content or _is_noise_message(msg):
                    continue
                if _should_skip_tool_result(content):
                    continue
                lines.append(f"\n__{msg.role}__:\n{_trim_message(content, 400)}")

        lines.append("\n\n---\nContinue from where we left off.")

        return "\n".join(lines)


def _get_output_formatter(format: str):
    """Get output formatter by name."""
    formatters = {
        "markdown": MarkdownOutput,
        "claude": ClaudeOutput,
        "gemini": GeminiOutput,
        "qwen": QwenOutput,
        "prompt": PromptOutput,
        "continue": ContinueOutput,
        "codex": CodexOutput,
        "opencode": OpenCodeOutput,
    }
    fmt = formatters.get(format, MarkdownOutput)
    return fmt()


# ─────────────────────────────────────────────────────────────
# Qwen Format
# ─────────────────────────────────────────────────────────────

class QwenOutput:
    """Format session cho Qwen CLI."""

    @staticmethod
    def transform(session: UniversalSession) -> str:
        lines = []

        lines.append("# Previous Session Context")
        lines.append("")
        lines.append("Continuing from a previous session:")
        lines.append("")

        if session.compressed:
            if session.compressed.current_goal:
                lines.append(f"**目标 (Goal):** {session.compressed.current_goal}")
            if session.compressed.todo_list:
                lines.append("\n**待办 (Todo):**")
                for t in session.compressed.todo_list:
                    lines.append(f"- [ ] {t}")
        else:
            recent = _filter_messages(session.messages, limit=10)
            for msg in recent:
                content = msg.content.strip()
                if not content or _is_noise_message(msg):
                    continue
                if _should_skip_tool_result(content):
                    continue
                lines.append(f"\n__{msg.role}__:\n{_trim_message(content, 400)}")

        lines.append("\n\n请继续。")

        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# Prompt Template (Generic)
# ─────────────────────────────────────────────────────────────

class PromptOutput:
    """Format session thành prompt template — dùng cho API calls."""

    @staticmethod
    def transform(session: UniversalSession, system_prompt: str = "") -> str:
        parts = []

        if system_prompt:
            parts.append(f"<system>\n{system_prompt}\n</system>")

        parts.append("<context>")
        if session.metadata.source_agent:
            parts.append(f"Previous session from: {session.metadata.source_agent}")
        if session.metadata.project_path:
            parts.append(f"Project: {session.metadata.project_path}")

        if session.compressed:
            if session.compressed.current_goal:
                parts.append(f"GOAL: {session.compressed.current_goal}")
            if session.compressed.todo_list:
                parts.append("TODO:")
                for t in session.compressed.todo_list:
                    parts.append(f"  - {t}")
        else:
            parts.append("\nPrevious conversation:")
            recent = _filter_messages(session.messages, limit=15)
            for msg in recent:
                content = msg.content.strip()
                if not content or _is_noise_message(msg):
                    continue
                if _should_skip_tool_result(content):
                    continue
                parts.append(f"[{msg.role}] {_trim_message(content, 600)}")

        parts.append("</context>")
        parts.append("<task>Continue from where we left off.</task>")

        return "\n".join(parts)


# ─────────────────────────────────────────────────────────────
# Continue.dev Format
# ─────────────────────────────────────────────────────────────

class ContinueOutput:
    """Format session cho Continue.dev (VS Code / JetBrains)."""

    @staticmethod
    def transform(session: UniversalSession) -> str:
        lines = []

        lines.append("## Context from Previous Session")
        lines.append("")
        lines.append("The following context was saved from a previous AI coding session.")
        lines.append("Please continue working from where we left off.")
        lines.append("")

        if session.metadata.project_path:
            lines.append(f"**Project:** `{session.metadata.project_path}`")
        if session.metadata.source_agent:
            lines.append(f"**Previous Tool:** {session.metadata.source_agent.capitalize()}")
        lines.append("")

        if session.compressed:
            if session.compressed.current_goal:
                lines.append(f"**Goal:** {session.compressed.current_goal}")
                lines.append("")

            if session.compressed.key_decisions:
                lines.append("**Key Decisions:**")
                for d in session.compressed.key_decisions:
                    lines.append(f"- {d}")
                lines.append("")

            if session.compressed.latest_code:
                lines.append("**Relevant Code:**")
                for snippet in session.compressed.latest_code[:5]:
                    path = snippet.path or "file"
                    lines.append(f"\n`{path}:`")
                    lines.append(f"```{snippet.language or ''}")
                    lines.append(snippet.content[:500])
                    lines.append("```")
                lines.append("")

            if session.compressed.current_errors:
                lines.append("**Current Errors:**")
                for err in session.compressed.current_errors:
                    lines.append(f"```\n{err}\n```")
                lines.append("")

            if session.compressed.todo_list:
                lines.append("**Tasks:**")
                for t in session.compressed.todo_list:
                    lines.append(f"- [ ] {t}")
                lines.append("")
        else:
            lines.append("**Recent conversation:**")
            recent = _filter_messages(session.messages, limit=12)
            for msg in recent:
                content = msg.content.strip()
                if not content or _is_noise_message(msg):
                    continue
                if _should_skip_tool_result(content):
                    continue
                lines.append(f"\n__{msg.role.upper()}__:\n{_trim_message(content, 600)}")

        lines.append("\n---\n**Continue from here.**")

        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# Codex Format (OpenAI)
# ─────────────────────────────────────────────────────────────

class CodexOutput:
    """Format session cho OpenAI Codex CLI."""

    @staticmethod
    def transform(session: UniversalSession) -> str:
        lines = []

        lines.append("# Previous Session Context")
        lines.append("")
        lines.append("Continuing from a previous session:")
        lines.append("")

        if session.metadata.project_path:
            lines.append(f"Project: `{session.metadata.project_path}`")

        if session.compressed:
            if session.compressed.current_goal:
                lines.append(f"\n**Goal:** {session.compressed.current_goal}")
            if session.compressed.key_decisions:
                lines.append("\n**Decisions:**")
                for d in session.compressed.key_decisions:
                    lines.append(f"- {d}")
            if session.compressed.todo_list:
                lines.append("\n**Todo:**")
                for t in session.compressed.todo_list:
                    lines.append(f"- [ ] {t}")
        else:
            lines.append("\n**Recent conversation:**")
            recent = _filter_messages(session.messages, limit=10)
            for msg in recent:
                content = msg.content.strip()
                if not content or _is_noise_message(msg):
                    continue
                if _should_skip_tool_result(content):
                    continue
                lines.append(f"\n__{msg.role}__:\n{_trim_message(content, 400)}")

        lines.append("\n\n---\nPlease continue from where we left off.")

        return "\n".join(lines)
