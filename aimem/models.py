"""
Universal Session Schema - Định dạng trung gian cho tất cả AI agents.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Literal
import json


@dataclass
class Message:
    """Một tin nhắn trong cuộc hội thoại."""
    id: str = ""
    role: Literal["system", "user", "assistant", "tool"] = "user"
    content: str = ""
    timestamp: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    tool_results: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ContextItem:
    """File, diff, artifact, hoặc snippet được attach vào session."""
    type: Literal["file", "diff", "url", "artifact", "snippet", "image"] = "file"
    path: str | None = None
    content: str = ""
    language: str | None = None
    size_kb: int = 0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SessionMetadata:
    """Metadata về session gốc."""
    source_agent: str = ""
    original_session_id: str = ""
    project_path: str = ""
    model: str = ""
    entrypoint: str = ""  # "cli" | "vscode" | "web"
    token_count: int = 0
    context_window: int = 200_000
    version: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CompressedSession:
    """
    LLM-compressed version của session (optional - Phase 2).
    Chỉ được tạo khi user bật --compress flag.
    """
    current_goal: str = ""
    latest_code: list[ContextItem] = field(default_factory=list)
    current_errors: list[str] = field(default_factory=list)
    key_decisions: list[str] = field(default_factory=list)
    todo_list: list[str] = field(default_factory=list)
    summary_token_count: int = 0
    compressed_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class UniversalSession:
    """
    Định dạng trung gian universal cho tất cả AI agents.
    Đây là "ngôn ngữ chung" mà mọi adapter sẽ dùng.
    """
    id: str = ""
    source: str = ""  # "claude" | "gemini" | "qwen" | "aider" | "clipboard"

    # Core data
    messages: list[Message] = field(default_factory=list)
    context_items: list[ContextItem] = field(default_factory=list)

    # Optional LLM compression
    compressed: CompressedSession | None = None

    # Metadata
    metadata: SessionMetadata = field(default_factory=SessionMetadata)

    # Timestamps
    created_at: str = ""
    updated_at: str = ""
    exported_at: str = ""

    # Tags & labels
    tags: list[str] = field(default_factory=list)
    note: str = ""

    def __post_init__(self):
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
        if not self.exported_at:
            self.exported_at = now
        if not self.id:
            import uuid
            self.id = f"sess-{uuid.uuid4().hex[:8]}"

    def to_dict(self) -> dict:
        data = asdict(self)
        # Remove None compressed
        if data.get("compressed") is None:
            data["compressed"] = None
        return data

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> "UniversalSession":
        # Handle compressed field
        if "compressed" in data and data["compressed"]:
            data["compressed"] = CompressedSession(**data["compressed"])
        else:
            data["compressed"] = None

        # Handle messages
        if "messages" in data:
            data["messages"] = [Message(**m) for m in data["messages"]]

        # Handle context_items
        if "context_items" in data:
            data["context_items"] = [ContextItem(**c) for c in data["context_items"]]

        # Handle metadata
        if "metadata" in data:
            data["metadata"] = SessionMetadata(**data["metadata"])

        return cls(**data)

    @classmethod
    def from_json(cls, json_str: str) -> "UniversalSession":
        return cls.from_dict(json.loads(json_str))

    def estimate_tokens(self) -> int:
        """Ước tính token count (rough approximation)."""
        text = self.to_json()
        # Rough: 1 token ≈ 4 chars
        return len(text) // 4

    def summary(self) -> str:
        """Trả về một dòng tóm tắt session."""
        msg_count = len(self.messages)
        token_est = self.estimate_tokens()
        src = self.source.upper()
        goal = self.compressed.current_goal if self.compressed else "(raw)"
        return f"[{src}] {msg_count} messages, ~{token_est:,} tokens | {goal}"
