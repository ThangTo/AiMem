"""
Context Manager - Smart chunking + context window management.
Dá»±a trÃªn knowledge base vá» context limits cá»§a cÃ¡c agents phá»• biáº¿n.
"""

from dataclasses import dataclass, field, replace
from typing import Literal
from aimem.models import UniversalSession, Message


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Agent Context Limits (Token-based)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@dataclass
class AgentLimit:
    """Context window limit cá»§a má»™t agent."""
    name: str
    provider: str
    context_limit: int          # Total context window (tokens)
    recommended_input: int      # Recommended input size (tokens)
    max_output: int           # Max output reserved for model response
    supports_system: bool      # CÃ³ system message khÃ´ng
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
    "gemini-2.5-flash": AgentLimit(
        name="Gemini 2.5 Flash", provider="Google",
        context_limit=1_000_000, recommended_input=900_000,
        max_output=65_536, supports_system=True,
        notes="1M input context in Gemini API"
    ),
    "gemini-2.5-flash-lite": AgentLimit(
        name="Gemini 2.5 Flash-Lite", provider="Google",
        context_limit=1_000_000, recommended_input=900_000,
        max_output=65_536, supports_system=True,
        notes="1M input context in Gemini API"
    ),
    "gemini-3-flash-preview": AgentLimit(
        name="Gemini 3 Flash Preview", provider="Google",
        context_limit=1_000_000, recommended_input=900_000,
        max_output=65_536, supports_system=True,
        notes="1M-class Gemini API context"
    ),
    "gemma-4-31b-it": AgentLimit(
        name="Gemma 4 31B IT", provider="Google",
        context_limit=262_144, recommended_input=220_000,
        max_output=32_768, supports_system=True,
        notes="256K context window"
    ),
    "gemma-3-27b-it": AgentLimit(
        name="Gemma 3 27B IT", provider="Google",
        context_limit=128_000, recommended_input=112_000,
        max_output=16_384, supports_system=True,
        notes="128K context window"
    ),

    # OpenAI (for reference)
    "gpt-5.4": AgentLimit(
        name="GPT-5.4", provider="OpenAI",
        context_limit=1_050_000, recommended_input=900_000,
        max_output=128_000, supports_system=True,
        notes="1.05M context window"
    ),
    "gpt-5.2-codex": AgentLimit(
        name="GPT-5.2-Codex", provider="OpenAI",
        context_limit=400_000, recommended_input=350_000,
        max_output=128_000, supports_system=True,
        notes="400K context window"
    ),
    "gpt-5.2": AgentLimit(
        name="GPT-5.2", provider="OpenAI",
        context_limit=400_000, recommended_input=350_000,
        max_output=128_000, supports_system=True,
        notes="400K context window"
    ),
    "gpt-5.1": AgentLimit(
        name="GPT-5.1", provider="OpenAI",
        context_limit=400_000, recommended_input=350_000,
        max_output=128_000, supports_system=True,
        notes="400K context window"
    ),
    "gpt-5": AgentLimit(
        name="GPT-5", provider="OpenAI",
        context_limit=400_000, recommended_input=350_000,
        max_output=128_000, supports_system=True,
        notes="400K context window"
    ),
    "gpt-4.1": AgentLimit(
        name="GPT-4.1", provider="OpenAI",
        context_limit=1_047_576, recommended_input=900_000,
        max_output=32_768, supports_system=True,
        notes="1M context window"
    ),
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
    "qwen3-coder": AgentLimit(
        name="Qwen3-Coder", provider="Alibaba",
        context_limit=256_000, recommended_input=230_000,
        max_output=32_768, supports_system=True,
        notes="256K context for Qwen3-Coder family"
    ),
    "qwen3-32b": AgentLimit(
        name="Qwen3 32B", provider="Alibaba/Groq",
        context_limit=131_072, recommended_input=118_000,
        max_output=40_960, supports_system=True,
        notes="131K context on Groq"
    ),
    "qwen-2.5-coder-32b": AgentLimit(
        name="Qwen 2.5 Coder 32B", provider="Alibaba",
        context_limit=128_000, recommended_input=112_000,
        max_output=8_192, supports_system=True,
        notes="128K context on common hosted runtimes"
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
    "llama-4-scout-17b-16e-instruct": AgentLimit(
        name="Llama 4 Scout 17B 16E", provider="Groq",
        context_limit=131_072, recommended_input=118_000,
        max_output=8_192, supports_system=True,
        notes="131K context on Groq"
    ),
    "minimax-m2.5-free": AgentLimit(
        name="MiniMax M2.5 Free", provider="MiniMax/OpenRouter",
        context_limit=196_608, recommended_input=180_000,
        max_output=16_384, supports_system=True,
        notes="~200K context window"
    ),
    "cursor-agent": AgentLimit(
        name="Cursor Agent", provider="Cursor",
        context_limit=200_000, recommended_input=180_000,
        max_output=20_000, supports_system=True,
        notes="Cursor normal mode uses about 200K context; Max Mode can be larger"
    ),

    # Generic fallback
    "unknown": AgentLimit(
        name="Unknown Agent", provider="Unknown",
        context_limit=64_000, recommended_input=50_000,
        max_output=8_192, supports_system=True,
        notes="Using conservative default"
    ),
}


def get_model_limit(model_id: str, provider_id: str = "") -> AgentLimit:
    """Return a best-known context profile for a concrete model id."""
    provider = (provider_id or "").strip().lower()
    model = (model_id or "").strip()
    if not model:
        return AGENT_LIMITS["unknown"]

    if "/" in model and not provider:
        provider, model = model.split("/", 1)

    key = model.lower()
    combined = f"{provider}/{key}" if provider else key

    if key in AGENT_LIMITS:
        return AGENT_LIMITS[key]

    # Order matters: chat aliases can have smaller limits than base GPT-5 models.
    if "chat-latest" in combined and "gpt-5" in combined:
        return AgentLimit(
            name="GPT-5 Chat", provider="OpenAI",
            context_limit=128_000, recommended_input=112_000,
            max_output=16_384, supports_system=True,
            notes="Chat alias context window"
        )
    if "gpt-5.4" in combined:
        return AGENT_LIMITS["gpt-5.4"]
    if "gpt-5.2-codex" in combined or "codex" in combined and "gpt-5.2" in combined:
        return AGENT_LIMITS["gpt-5.2-codex"]
    if "gpt-5.2" in combined:
        return AGENT_LIMITS["gpt-5.2"]
    if "gpt-5.1" in combined:
        return AGENT_LIMITS["gpt-5.1"]
    if "gpt-5" in combined:
        return AGENT_LIMITS["gpt-5"]
    if "gpt-4.1" in combined:
        return AGENT_LIMITS["gpt-4.1"]
    if "gpt-4o" in combined:
        return AGENT_LIMITS["gpt-4o"]

    if "gemini-1.5-pro" in combined:
        return AGENT_LIMITS["gemini-1.5-pro"]
    if "gemini-2.5-flash-lite" in combined:
        return AGENT_LIMITS["gemini-2.5-flash-lite"]
    if "gemini-2.5" in combined:
        return AGENT_LIMITS["gemini-2.5-flash"]
    if "gemini-3" in combined:
        return AGENT_LIMITS["gemini-3-flash-preview"]
    if "gemini" in combined:
        return AGENT_LIMITS["gemini-2.5-flash"]
    if "gemma-4" in combined:
        return AGENT_LIMITS["gemma-4-31b-it"]
    if "gemma-3" in combined:
        return AGENT_LIMITS["gemma-3-27b-it"]

    if "claude" in combined:
        return AgentLimit(
            name="Claude", provider="Anthropic",
            context_limit=200_000, recommended_input=180_000,
            max_output=32_768, supports_system=True,
            notes="Standard Claude API context window"
        )

    if "qwen3-coder" in combined:
        return AGENT_LIMITS["qwen3-coder"]
    if "qwen3-32b" in combined or "qwen/qwen3-32b" in combined:
        return AGENT_LIMITS["qwen3-32b"]
    if "qwen-2.5-coder" in combined:
        return AGENT_LIMITS["qwen-2.5-coder-32b"]
    if "qwen" in combined:
        return AGENT_LIMITS["qwen3-32b"]

    if "minimax-m2.5" in combined or "m2.5" in combined:
        return AGENT_LIMITS["minimax-m2.5-free"]
    if "llama-4-scout" in combined:
        return AGENT_LIMITS["llama-4-scout-17b-16e-instruct"]
    if any(name in combined for name in ("llama-3.1", "llama-3.3", "gpt-oss", "deepseek-r1", "kimi-k2")):
        return AgentLimit(
            name="Hosted 128K Model", provider=provider or "Hosted",
            context_limit=131_072, recommended_input=118_000,
            max_output=16_384, supports_system=True,
            notes="Common hosted model context window"
        )

    if provider == "cursor" or key == "cursor-agent":
        return AGENT_LIMITS["cursor-agent"]
    if provider == "opencode":
        return AgentLimit(
            name="OpenCode Model", provider="OpenCode",
            context_limit=128_000, recommended_input=112_000,
            max_output=16_384, supports_system=True,
            notes="Fallback; select a concrete OpenCode model for accurate sizing"
        )

    return AGENT_LIMITS["unknown"]


def get_target_limit(target: str, model: str | None = None, provider: str | None = None) -> AgentLimit:
    """Return the context profile for a target adapter or explicit model."""
    if model:
        return get_model_limit(model, provider or "")

    detected = _detect_target_model(target)
    if detected in AGENT_LIMITS:
        return AGENT_LIMITS[detected]
    return get_model_limit(detected)


def _estimate_tokens(text: str) -> int:
    """Estimate token count from text."""
    # Rough: 1 token â‰ˆ 4 characters for typical English
    # For Vietnamese / mixed: 1 token â‰ˆ 2-3 chars
    char_count = len(text)
    # Check if text is mostly Vietnamese (higher density)
    vietnamese_ratio = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or 'Äƒ' <= c <= 'á»¹')
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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Target Agent Detection
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _detect_target_model(target: str) -> str:
    """Detect model from target agent name."""
    target_lower = target.lower()

    # Claude detection
    if target_lower in ("claude", "claude-code"):
        return "claude-sonnet-4-6"

    # Gemini detection
    if target_lower in ("gemini", "gemini-cli", "google"):
        return "gemini-2.5-flash"

    # Qwen detection
    if target_lower in ("qwen", "qwen-cli", "open-sourcoders"):
        return "qwen3-coder"

    # Adapter defaults.
    if target_lower == "opencode":
        return "opencode/minimax-m2.5-free"
    if target_lower == "codex":
        return "gpt-5.4"
    if target_lower == "cursor":
        return "cursor-agent"
    if target_lower == "antigravity":
        return "gemini-3-flash-preview"

    # Continue.dev detection
    if target_lower in ("continue", "continue-dev"):
        return "gpt-4o"

    # Try exact match
    if target_lower in AGENT_LIMITS:
        return target_lower

    return "unknown"


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Chunking Strategy
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@dataclass
class ChunkResult:
    """Káº¿t quáº£ cá»§a quÃ¡ trÃ¬nh chunking."""
    chunks: list[str]          # List of chunk contents
    total_messages: int         # Total messages in session
    messages_per_chunk: list[int]  # How many messages in each chunk
    dropped_messages: int       # Messages dropped due to size
    original_tokens: int        # Original token count
    chunk_token_counts: list[int]  # Tokens per chunk
    fits_in_target: bool        # Whether session fits in target limit
    chunk_messages: list[list[Message]] = field(default_factory=list)


def chunk_session(
    session: UniversalSession,
    target: str,
    prefer_recent: bool = False,
    model: str | None = None,
    provider: str | None = None,
) -> ChunkResult:
    """
    Chunk a session to fit within target agent's context limit.
    Default strategy: preserve the whole session and split at message boundaries.
    Set prefer_recent=True only for explicit trimming-style behavior.
    """
    limit = get_target_limit(target, model=model, provider=provider)
    max_input = limit.recommended_input

    messages = list(session.messages)
    original_tokens = _estimate_session_tokens(session)

    if prefer_recent:
        selected: list[Message] = []
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
        selected = messages
        dropped = 0
        running_tokens = original_tokens

    prepared_messages: list[Message] = []
    for msg in selected:
        prepared_messages.extend(_split_oversized_message(msg, max_input))

    chunks: list[str] = []
    chunk_messages: list[list[Message]] = []
    chunk_token_counts: list[int] = []
    msgs_per_chunk: list[int] = []
    current_chunk: list[Message] = []
    current_tokens = 0

    for msg in prepared_messages:
        msg_tokens = _estimate_message_tokens(msg)
        if current_tokens + msg_tokens > max_input and current_chunk:
            chunks.append(_format_chunk(current_chunk))
            chunk_messages.append(current_chunk)
            chunk_token_counts.append(current_tokens)
            msgs_per_chunk.append(len(current_chunk))
            current_chunk = []
            current_tokens = 0
        current_chunk.append(msg)
        current_tokens += msg_tokens

    if current_chunk:
        chunks.append(_format_chunk(current_chunk))
        chunk_messages.append(current_chunk)
        chunk_token_counts.append(current_tokens)
        msgs_per_chunk.append(len(current_chunk))

    fits = original_tokens <= max_input

    return ChunkResult(
        chunks=chunks,
        total_messages=len(selected),
        messages_per_chunk=msgs_per_chunk,
        dropped_messages=dropped,
        original_tokens=original_tokens,
        chunk_token_counts=chunk_token_counts,
        fits_in_target=fits,
        chunk_messages=chunk_messages,
    )


def _split_oversized_message(msg: Message, max_input_tokens: int) -> list[Message]:
    """Split one huge message so every generated chunk can stay under budget."""
    if _estimate_message_tokens(msg) <= max_input_tokens:
        return [msg]

    marker = f"[AiMem split from one long {msg.role} message]"
    marker_tokens = _estimate_tokens(marker) + 20
    max_content_tokens = max(500, max_input_tokens - marker_tokens)
    segments = _split_text_to_token_limit(msg.content or "", max_content_tokens)
    total = len(segments)

    split_messages: list[Message] = []
    for index, segment in enumerate(segments, 1):
        metadata = dict(msg.metadata or {})
        metadata.update({
            "aimem_split": True,
            "aimem_split_part": index,
            "aimem_split_total": total,
        })
        split_messages.append(replace(
            msg,
            id=f"{msg.id or 'message'}-chunk-{index}",
            content=f"{marker} part {index}/{total}\n\n{segment}",
            metadata=metadata,
        ))
    return split_messages


def _split_text_to_token_limit(text: str, max_tokens: int) -> list[str]:
    if not text:
        return [""]

    segments: list[str] = []
    current = ""
    lines = text.splitlines(keepends=True) or [text]

    for line in lines:
        candidate = current + line
        if current and _estimate_tokens(candidate) > max_tokens:
            segments.extend(_hard_split_text(current, max_tokens))
            current = line
        else:
            current = candidate

        if _estimate_tokens(current) > max_tokens:
            hard_parts = _hard_split_text(current, max_tokens)
            segments.extend(hard_parts[:-1])
            current = hard_parts[-1] if hard_parts else ""

    if current.strip():
        segments.extend(_hard_split_text(current, max_tokens))

    return [segment.strip() for segment in segments if segment.strip()]


def _hard_split_text(text: str, max_tokens: int) -> list[str]:
    if _estimate_tokens(text) <= max_tokens:
        return [text]

    parts: list[str] = []
    remaining = text
    while remaining and _estimate_tokens(remaining) > max_tokens:
        token_estimate = max(_estimate_tokens(remaining), 1)
        ratio = len(remaining) / token_estimate
        cut = max(500, int(max_tokens * ratio * 0.90))
        cut = min(cut, max(1, len(remaining) - 1))
        parts.append(remaining[:cut])
        remaining = remaining[cut:]
    if remaining:
        parts.append(remaining)
    return parts


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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Warnings & Advisory
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@dataclass
class LoadAdvice:
    """Lá»i khuyÃªn khi load session vÃ o target agent."""
    target: str
    target_model: str
    limit: AgentLimit
    session_tokens: int
    will_fit: bool
    compression_recommended: bool
    chunk_count: int = 0
    warning_messages: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


def get_load_advice(
    session: UniversalSession,
    target: str,
    model: str | None = None,
    provider: str | None = None,
) -> LoadAdvice:
    """Analyze session vs target agent and return advice."""
    limit = get_target_limit(target, model=model, provider=provider)
    session_tokens = _estimate_session_tokens(session)

    warnings = []
    suggestions = []
    will_fit = session_tokens <= limit.recommended_input
    compression_recommended = False

    # Check context fit
    if session_tokens > limit.context_limit:
        warnings.append(
            f"âš ï¸  Session ({session_tokens:,} tokens) EXCEEDS target context window "
            f"({limit.name}: {limit.context_limit:,} tokens)"
        )
        compression_recommended = True
        suggestions.append("Enable LLM compression: aimem config set compression.enabled true")
        suggestions.append("Or manually trim old messages before loading")
    elif session_tokens > limit.recommended_input:
        pct = session_tokens / limit.recommended_input * 100
        warnings.append(
            f"âš ï¸  Session uses {pct:.0f}% of recommended input "
            f"({session_tokens:,} / {limit.recommended_input:,} tokens)"
        )
        if pct > 90:
            compression_recommended = True
            suggestions.append("Consider enabling compression to avoid near-limit issues")
    else:
        warnings.append(
            f"âœ… Session fits comfortably in {limit.name} "
            f"({session_tokens:,} / {limit.recommended_input:,} tokens = "
            f"{session_tokens / limit.recommended_input * 100:.0f}%)"
        )

    # Model-specific advice
    if "Qwen" in limit.name:
        if session_tokens > limit.recommended_input:
            suggestions.append("Qwen target is over budget; use chunking or compression")
        suggestions.append("Tip: Start with your current goal, not full history")

    if "Claude" in limit.name:
        suggestions.append("Claude supports system prompts â€” use 'claude' format for best results")

    if "Gemini" in limit.name:
        if session_tokens > 100_000:
            suggestions.append("Gemini has large context â€” raw transfer should work fine")

    # Check for very long single messages
    for msg in session.messages:
        msg_tokens = _estimate_message_tokens(msg)
        if msg_tokens > limit.max_output:
            warnings.append(
                f"âš ï¸  Very long message ({msg_tokens:,} tokens) may cause issues. "
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
    print(f"\nðŸ“Š Context Analysis: session â†’ {advice.target.upper()} ({advice.target_model})")
    print(f"   Session size: ~{advice.session_tokens:,} tokens")
    print(f"   Context limit: {advice.limit.context_limit:,} tokens")
    print(f"   Recommended:   {advice.limit.recommended_input:,} tokens")
    print()

    for w in advice.warning_messages:
        print(f"   {w}")

    if advice.suggestions:
        print()
        for s in advice.suggestions:
            print(f"   ðŸ’¡ {s}")


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Session Merge
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@dataclass
class MergeResult:
    """Káº¿t quáº£ cá»§a viá»‡c merge sessions."""
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
    """Simple append merge â€” all messages in chronological order."""
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


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Auto-trim (save with smart trimming)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@dataclass
class TrimResult:
    """Káº¿t quáº£ cá»§a viá»‡c trim session."""
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
        limit = get_target_limit(target)
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
