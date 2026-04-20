"""
Context Manager - Smart chunking + context window management.
Dựa trên knowledge base về context limits của các agents phổ biến.
"""

from dataclasses import dataclass, field
from typing import Literal
from aimem.models import UniversalSession, Message


# ─────────────────────────────────────────────────────────────
# Agent Context Limits (Token-based)
# ─────────────────────────────────────────────────────────────

@dataclass
class AgentLimit:
    """Context window limit của một agent."""
    name: str
    provider: str
    context_limit: int          # Total context window (tokens)
    recommended_input: int      # Recommended input size (tokens)
    max_output: int           # Max output reserved for model response
    supports_system: bool      # Có system message không
    notes: str = ""


AGENT_LIMITS: dict[str, AgentLimit] = {
    # Anthropic
    "claude-opus-4-5": AgentLimit(
        name="Claude Opus 4.5", provider="Anthropic",
        context_limit=200_000, recommended_input=180_000,
        max_output=32_768, supports_system=True,
        notes="200K context, supports extended thinking"
    ),
    "claude-sonnet-4-6": AgentLimit(
        name="Claude Sonnet 4.6", provider="Anthropic",
        context_limit=200_000, recommended_input=180_000,
        max_output=32_768, supports_system=True,
        notes="200K context, supports extended thinking"
    ),
    "claude-haiku-4-5": AgentLimit(
        name="Claude Haiku 4.5", provider="Anthropic",
        context_limit=200_000, recommended_input=180_000,
        max_output=32_768, supports_system=True,
        notes="200K context, fast + cheap"
    ),

    # Google
    "gemini-2.0-flash-exp": AgentLimit(
        name="Gemini 2.0 Flash", provider="Google",
        context_limit=1_000_000, recommended_input=800_000,
        max_output=8_192, supports_system=True,
        notes="1M context window, very fast"
    ),
    "gemini-1.5-pro": AgentLimit(
        name="Gemini 1.5 Pro", provider="Google",
        context_limit=2_000_000, recommended_input=1_800_000,
        max_output=8_192, supports_system=True,
        notes="2M context, best for long documents"
    ),
    "gemini-1.5-flash": AgentLimit(
        name="Gemini 1.5 Flash", provider="Google",
        context_limit=1_000_000, recommended_input=800_000,
        max_output=8_192, supports_system=True,
        notes="1M context, fast + cheap"
    ),
    "gemini-2.0-flash": AgentLimit(
        name="Gemini 2.0 Flash", provider="Google",
        context_limit=1_000_000, recommended_input=800_000,
        max_output=8_192, supports_system=True,
        notes="1M context, Google's latest fast model"
    ),

    # OpenAI (for reference)
    "gpt-4o": AgentLimit(
        name="GPT-4o", provider="OpenAI",
        context_limit=128_000, recommended_input=100_000,
        max_output=16_384, supports_system=True,
        notes="128K context, good for coding"
    ),
    "gpt-4o-mini": AgentLimit(
        name="GPT-4o Mini", provider="OpenAI",
        context_limit=128_000, recommended_input=100_000,
        max_output=16_384, supports_system=True,
        notes="128K context, fast + cheap"
    ),

    # Qwen
    "qwen-2.5-coder-32b": AgentLimit(
        name="Qwen 2.5 Coder 32B", provider="Alibaba",
        context_limit=32_768, recommended_input=25_000,
        max_output=8_192, supports_system=True,
        notes="32K context, good for local dev"
    ),
    "qwen-2.5-72b": AgentLimit(
        name="Qwen 2.5 72B", provider="Alibaba",
        context_limit=32_768, recommended_input=25_000,
        max_output=8_192, supports_system=True,
        notes="32K context, strong reasoning"
    ),

    # Groq (Llama via Groq)
    "llama-3.1-8b-instant": AgentLimit(
        name="Llama 3.1 8B (Groq)", provider="Groq",
        context_limit=128_000, recommended_input=100_000,
        max_output=32_768, supports_system=True,
        notes="128K context, very fast inference"
    ),
    "llama-3.1-70b": AgentLimit(
        name="Llama 3.1 70B (Groq)", provider="Groq",
        context_limit=128_000, recommended_input=100_000,
        max_output=32_768, supports_system=True,
        notes="128K context, strong reasoning"
    ),

    # Generic fallback
    "unknown": AgentLimit(
        name="Unknown Agent", provider="Unknown",
        context_limit=64_000, recommended_input=50_000,
        max_output=8_192, supports_system=True,
        notes="Using conservative default"
    ),
}


def _estimate_tokens(text: str) -> int:
    """Estimate token count from text."""
    # Rough: 1 token ≈ 4 characters for typical English
    # For Vietnamese / mixed: 1 token ≈ 2-3 chars
    char_count = len(text)
    # Check if text is mostly Vietnamese (higher density)
    vietnamese_ratio = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or 'ă' <= c <= 'ỹ')
    if vietnamese_ratio > char_count * 0.2:
        return char_count // 2
    return char_count // 4


def _estimate_message_tokens(msg: Message) -> int:
    """Estimate tokens for a single message."""
    # role (6) + content + overhead
    overhead = 10  # role + separators
    return _estimate_tokens(msg.content) + overhead


def _estimate_session_tokens(session: UniversalSession) -> int:
    """Estimate total tokens in a session."""
    return sum(_estimate_message_tokens(m) for m in session.messages)


# ─────────────────────────────────────────────────────────────
# Target Agent Detection
# ─────────────────────────────────────────────────────────────

def _detect_target_model(target: str) -> str:
    """Detect model from target agent name."""
    target_lower = target.lower()

    # Claude detection
    if target in ("claude", "claude-code"):
        return "claude-sonnet-4-6"

    # Gemini detection
    if target in ("gemini", "gemini-cli", "google"):
        return "gemini-2.0-flash-exp"

    # Qwen detection
    if target in ("qwen", "qwen-cli", "opencode", "open-sourcoders"):
        return "qwen-2.5-coder-32b"

    # Continue.dev detection
    if target in ("continue", "continue-dev"):
        return "gpt-4o"

    # Try exact match
    if target in AGENT_LIMITS:
        return target

    return "unknown"


# ─────────────────────────────────────────────────────────────
# Chunking Strategy
# ─────────────────────────────────────────────────────────────

@dataclass
class ChunkResult:
    """Kết quả của quá trình chunking."""
    chunks: list[str]          # List of chunk contents
    total_messages: int         # Total messages in session
    messages_per_chunk: list[int]  # How many messages in each chunk
    dropped_messages: int       # Messages dropped due to size
    original_tokens: int        # Original token count
    chunk_token_counts: list[int]  # Tokens per chunk
    fits_in_target: bool        # Whether session fits in target limit


def chunk_session(
    session: UniversalSession,
    target: str,
    prefer_recent: bool = True,
) -> ChunkResult:
    """
    Chunk a session to fit within target agent's context limit.
    Strategy: keep most recent messages, drop oldest until fits.
    """
    limit = AGENT_LIMITS.get(_detect_target_model(target), AGENT_LIMITS["unknown"])
    max_input = limit.recommended_input

    messages = list(session.messages)
    original_tokens = _estimate_session_tokens(session)

    # Strategy: keep recent, drop old
    if prefer_recent:
        # Start from newest, go backwards
        selected = []
        running_tokens = 0
        dropped = 0

        for msg in reversed(messages):
            msg_tokens = _estimate_message_tokens(msg)
            if running_tokens + msg_tokens <= max_input:
                selected.append(msg)
                running_tokens += msg_tokens
            else:
                dropped += 1

        selected = list(reversed(selected))  # Restore order
    else:
        # Keep all, chunk at message boundaries
        selected = messages
        dropped = 0
        running_tokens = original_tokens

    # Split into chunks if still too large
    chunks = []
    chunk_token_counts = []
    msgs_per_chunk = []
    current_chunk = []
    current_tokens = 0

    for msg in selected:
        msg_tokens = _estimate_message_tokens(msg)
        if current_tokens + msg_tokens > max_input and current_chunk:
            chunks.append(_format_chunk(current_chunk))
            chunk_token_counts.append(current_tokens)
            msgs_per_chunk.append(len(current_chunk))
            current_chunk = []
            current_tokens = 0
        current_chunk.append(msg)
        current_tokens += msg_tokens

    if current_chunk:
        chunks.append(_format_chunk(current_chunk))
        chunk_token_counts.append(current_tokens)
        msgs_per_chunk.append(len(current_chunk))

    fits = running_tokens <= max_input if prefer_recent else all(
        ct <= max_input for ct in chunk_token_counts
    )

    return ChunkResult(
        chunks=chunks,
        total_messages=len(selected),
        messages_per_chunk=msgs_per_chunk,
        dropped_messages=dropped,
        original_tokens=original_tokens,
        chunk_token_counts=chunk_token_counts,
        fits_in_target=fits,
    )


def _format_chunk(messages: list[Message]) -> str:
    """Format a chunk of messages as readable text."""
    lines = []
    for msg in messages:
        content = msg.content.strip()
        if not content:
            continue
        lines.append(f"**{msg.role.upper()}:**")
        lines.append(content)
        lines.append("")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# Warnings & Advisory
# ─────────────────────────────────────────────────────────────

@dataclass
class LoadAdvice:
    """Lời khuyên khi load session vào target agent."""
    target: str
    target_model: str
    limit: AgentLimit
    session_tokens: int
    will_fit: bool
    compression_recommended: bool
    chunk_count: int = 0
    warning_messages: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


def get_load_advice(session: UniversalSession, target: str) -> LoadAdvice:
    """Analyze session vs target agent and return advice."""
    limit = AGENT_LIMITS.get(_detect_target_model(target), AGENT_LIMITS["unknown"])
    session_tokens = _estimate_session_tokens(session)

    warnings = []
    suggestions = []
    will_fit = session_tokens <= limit.recommended_input
    compression_recommended = False

    # Check context fit
    if session_tokens > limit.context_limit:
        warnings.append(
            f"⚠️  Session ({session_tokens:,} tokens) EXCEEDS target context window "
            f"({limit.name}: {limit.context_limit:,} tokens)"
        )
        compression_recommended = True
        suggestions.append("Enable LLM compression: aimem config set compression.enabled true")
        suggestions.append("Or manually trim old messages before loading")
    elif session_tokens > limit.recommended_input:
        pct = session_tokens / limit.recommended_input * 100
        warnings.append(
            f"⚠️  Session uses {pct:.0f}% of recommended input "
            f"({session_tokens:,} / {limit.recommended_input:,} tokens)"
        )
        if pct > 90:
            compression_recommended = True
            suggestions.append("Consider enabling compression to avoid near-limit issues")
    else:
        warnings.append(
            f"✅ Session fits comfortably in {limit.name} "
            f"({session_tokens:,} / {limit.recommended_input:,} tokens = "
            f"{session_tokens / limit.recommended_input * 100:.0f}%)"
        )

    # Model-specific advice
    if limit.name == "Qwen 2.5 Coder 32B":
        if session_tokens > 25_000:
            suggestions.append("Qwen has 32K limit — consider splitting into 2 chunks")
        suggestions.append("Tip: Start with your current goal, not full history")

    if "Claude" in limit.name:
        suggestions.append("Claude supports system prompts — use 'claude' format for best results")

    if "Gemini" in limit.name:
        if session_tokens > 100_000:
            suggestions.append("Gemini has large context — raw transfer should work fine")

    # Check for very long single messages
    for msg in session.messages:
        msg_tokens = _estimate_message_tokens(msg)
        if msg_tokens > limit.max_output:
            warnings.append(
                f"⚠️  Very long message ({msg_tokens:,} tokens) may cause issues. "
                f"Consider using --compress flag."
            )
            break

    return LoadAdvice(
        target=target,
        target_model=limit.name,
        limit=limit,
        session_tokens=session_tokens,
        will_fit=will_fit,
        compression_recommended=compression_recommended,
        warning_messages=warnings,
        suggestions=suggestions,
    )


def print_load_advice(advice: LoadAdvice) -> None:
    """Pretty print load advice."""
    print(f"\n📊 Context Analysis: session → {advice.target.upper()} ({advice.target_model})")
    print(f"   Session size: ~{advice.session_tokens:,} tokens")
    print(f"   Context limit: {advice.limit.context_limit:,} tokens")
    print(f"   Recommended:   {advice.limit.recommended_input:,} tokens")
    print()

    for w in advice.warning_messages:
        print(f"   {w}")

    if advice.suggestions:
        print()
        for s in advice.suggestions:
            print(f"   💡 {s}")


# ─────────────────────────────────────────────────────────────
# Session Merge
# ─────────────────────────────────────────────────────────────

@dataclass
class MergeResult:
    """Kết quả của việc merge sessions."""
    session: UniversalSession
    source_count: int
    original_sessions: list[str]
    merged_tokens: int
    method: str  # "append" | "smart_merge"


def merge_sessions(
    sessions: list[UniversalSession],
    method: Literal["append", "smart_merge"] = "append",
    target: str | None = None,
) -> MergeResult:
    """
    Merge multiple sessions into one.

    Args:
        sessions: List of UniversalSession to merge
        method:
            - "append": Append all messages chronologically
            - "smart_merge": Detect duplicates, merge by topic, keep latest code
        target: Optional target agent for smart sizing
    """
    if not sessions:
        raise ValueError("No sessions provided to merge")

    if len(sessions) == 1:
        return MergeResult(
            session=sessions[0],
            source_count=1,
            original_sessions=[sessions[0].id],
            merged_tokens=_estimate_session_tokens(sessions[0]),
            method=method,
        )

    if method == "append":
        return _merge_append(sessions, target)
    else:
        return _merge_smart(sessions, target)


def _merge_append(
    sessions: list[UniversalSession],
    target: str | None,
) -> MergeResult:
    """Simple append merge — all messages in chronological order."""
    # Sort sessions by created_at
    sorted_sessions = sorted(sessions, key=lambda s: s.created_at or "")

    all_messages: list[Message] = []
    for sess in sorted_sessions:
        all_messages.extend(sess.messages)

    # Build merged metadata
    sources = [s.source for s in sorted_sessions]
    source_ids = [s.id for s in sorted_sessions]
    project = sorted_sessions[0].metadata.project_path
    model = sorted_sessions[0].metadata.model

    import uuid
    merged = UniversalSession(
        id=f"merged-{uuid.uuid4().hex[:8]}",
        source="merged",
        messages=all_messages,
        metadata=sorted_sessions[0].metadata.__class__(
            source_agent=",".join(sources),
            original_session_id=",".join(source_ids),
            project_path=project or "",
            model=model or "",
            token_count=sum(_estimate_session_tokens(s) for s in sorted_sessions),
        ),
        tags=["merged", *sources],
        note=f"Merged {len(sessions)} sessions: {', '.join(source_ids)}",
    )

    return MergeResult(
        session=merged,
        source_count=len(sessions),
        original_sessions=source_ids,
        merged_tokens=_estimate_session_tokens(merged),
        method="append",
    )


def _merge_smart(
    sessions: list[UniversalSession],
    target: str | None,
) -> MergeResult:
    """
    Smart merge:
    1. Deduplicate similar messages
    2. Keep most recent version of code/context
    3. Merge todo lists
    4. Build coherent narrative
    """
    # Sort newest first for priority
    sorted_sessions = sorted(
        sessions,
        key=lambda s: s.created_at or "",
        reverse=True,
    )

    seen_contents: set[str] = set()
    merged_messages: list[Message] = []
    all_goals: list[str] = []
    all_errors: list[str] = []
    all_decisions: list[str] = []
    all_todos: list[str] = []

    import uuid

    for sess in sorted_sessions:
        for msg in sess.messages:
            # Deduplicate by first 200 chars content hash
            content = msg.content.strip()
            if not content:
                continue
            key = content[:200].lower()

            if key in seen_contents:
                continue
            seen_contents.add(key)

            # Keep the most recent version
            merged_messages.append(msg)

        # Collect compressed data
        if sess.compressed:
            if sess.compressed.current_goal:
                all_goals.append(sess.compressed.current_goal)
            all_errors.extend(sess.compressed.current_errors)
            all_decisions.extend(sess.compressed.key_decisions)
            all_todos.extend(sess.compressed.todo_list)

    # Sort by timestamp (oldest first)
    merged_messages.sort(key=lambda m: m.timestamp or "")

    # Deduplicate lists
    all_errors = list(dict.fromkeys(all_errors))
    all_decisions = list(dict.fromkeys(all_decisions))
    all_todos = list(dict.fromkeys(all_todos))
    all_goals = list(dict.fromkeys(all_goals))

    # Build compressed summary
    from .models import CompressedSession, ContextItem
    compressed = CompressedSession(
        current_goal=all_goals[0] if all_goals else "Multi-session context",
        latest_code=[],
        current_errors=all_errors[:10],
        key_decisions=all_decisions[:20],
        todo_list=all_todos[:30],
        summary_token_count=_estimate_session_tokens(
            UniversalSession(messages=merged_messages)
        ),
        compressed_at="",
    )

    sources = [s.source for s in sessions]
    source_ids = [s.id for s in sessions]
    first = sessions[0]

    merged = UniversalSession(
        id=f"merged-{uuid.uuid4().hex[:8]}",
        source="merged",
        messages=merged_messages,
        compressed=compressed,
        metadata=first.metadata.__class__(
            source_agent=",".join(sources),
            original_session_id=",".join(source_ids),
            project_path=first.metadata.project_path,
            model=first.metadata.model,
            token_count=sum(_estimate_session_tokens(s) for s in sessions),
        ),
        tags=["merged", "smart-merge", *sources],
        note=f"Smart-merged {len(sessions)} sessions",
    )

    return MergeResult(
        session=merged,
        source_count=len(sessions),
        original_sessions=source_ids,
        merged_tokens=_estimate_session_tokens(merged),
        method="smart_merge",
    )


# ─────────────────────────────────────────────────────────────
# Auto-trim (save with smart trimming)
# ─────────────────────────────────────────────────────────────

@dataclass
class TrimResult:
    """Kết quả của việc trim session."""
    original_count: int
    trimmed_count: int
    original_tokens: int
    trimmed_tokens: int
    reduction_ratio: float  # 0.0 = no change, 0.8 = 80% reduction
    dropped_items: list[str]


def auto_trim(session: UniversalSession, target: str | None = None) -> TrimResult:
    """
    Auto-trim session for better transfer:
    - Remove duplicate/very similar messages
    - Trim very long tool outputs
    - Keep conversation flow intact
    - Drop system API error noise
    """
    original_count = len(session.messages)
    original_tokens = _estimate_session_tokens(session)
    dropped: list[str] = []

    # Step 1: Filter noise messages
    cleaned_messages = []
    seen_keys: set[str] = set()

    for msg in session.messages:
        content = msg.content.strip()
        if not content:
            dropped.append("empty_message")
            continue

        # Skip API error system messages
        if msg.role == "system" and ("API Error" in content or content.startswith("[System:")):
            dropped.append("api_error_system")
            continue

        # Skip very long HTML pages
        if len(content) > 5000 and ("<html>" in content.lower() or "<!doctype" in content.lower()):
            dropped.append("long_html_dump")
            continue

        # Skip pip/npm upgrade spam
        lines = content.split("\n")
        notice_lines = sum(1 for l in lines if "[notice]" in l.lower())
        if notice_lines > len(lines) * 0.8 and notice_lines > 5:
            dropped.append("pip_upgrade_spam")
            continue

        # Deduplicate by content hash (keep first occurrence)
        content_hash = content[:150].lower()
        if content_hash in seen_keys:
            dropped.append("duplicate_content")
            continue
        seen_keys.add(content_hash)

        # Trim very long tool results (>4000 chars) to summary
        if len(content) > 4000:
            # Extract first meaningful part
            meaningful_lines = []
            truncated = False
            for line in lines[:100]:
                if "<html>" in line.lower() or "<!doctype" in line.lower():
                    truncated = True
                    break
                meaningful_lines.append(line)

            if truncated:
                trimmed_content = "\n".join(meaningful_lines)
                trimmed_content += f"\n[... content truncated ({len(content)} chars)]"
                msg.content = trimmed_content
                dropped.append("long_tool_result_trimmed")

        cleaned_messages.append(msg)

    # Step 2: Trim from oldest if still too large
    if target:
        limit = AGENT_LIMITS.get(_detect_target_model(target), AGENT_LIMITS["unknown"])
        max_tokens = limit.recommended_input
        running = 0

        to_remove = []
        for i, msg in enumerate(cleaned_messages):
            tokens = _estimate_message_tokens(msg)
            if running + tokens > max_tokens:
                to_remove.append(i)
            else:
                running += tokens

        for i in reversed(to_remove):
            dropped.append("trimmed_for_target_limit")
            cleaned_messages.pop(i)

    session.messages = cleaned_messages
    trimmed_tokens = _estimate_session_tokens(session)
    reduction = (original_tokens - trimmed_tokens) / max(original_tokens, 1)

    return TrimResult(
        original_count=original_count,
        trimmed_count=len(cleaned_messages),
        original_tokens=original_tokens,
        trimmed_tokens=trimmed_tokens,
        reduction_ratio=reduction,
        dropped_items=list(dict.fromkeys(dropped)),
    )