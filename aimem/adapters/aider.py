"""
Aider Adapter - Đọc session từ Aider (aider.chat).
Storage: ~/.aider.chat.history.md (Markdown format)
Format: One file per session with chat history in Markdown.
"""

from pathlib import Path
from typing import Literal
import re
import uuid

from ..models import UniversalSession, Message, SessionMetadata


def _get_aider_base() -> Path:
    """Tìm thư mục gốc của Aider config."""
    import os
    home = Path(os.path.expanduser("~"))
    return home / ".aider.chat.history.md"


def _parse_aider_history(file_path: Path) -> list[Message]:
    """Parse Aider history file (Markdown format)."""
    if not file_path.exists():
        return []

    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError:
        return []

    messages = []
    lines = content.split("\n")
    current_role = None
    current_content = []
    msg_id = 0

    # Aider history format:
    # ## context: ...
    # ## ask: ...
    # user message
    # ## ask-2: ...
    # ## ans: ...
    # assistant message

    for line in lines:
        line = line.rstrip()

        if line.startswith("## ask") or line.startswith("## ask-"):
            # Save previous message
            if current_role and current_content:
                content_text = "\n".join(current_content).strip()
                if content_text:
                    messages.append(Message(
                        id=str(uuid.uuid4()),
                        role=current_role,
                        content=content_text,
                        timestamp="",
                        metadata={"source": "aider"}
                    ))
                current_content = []

            current_role = "user"
            msg_id += 1

        elif line.startswith("## ans") or line.startswith("## ans-"):
            if current_role and current_content:
                content_text = "\n".join(current_content).strip()
                if content_text:
                    messages.append(Message(
                        id=str(uuid.uuid4()),
                        role=current_role,
                        content=content_text,
                        timestamp="",
                        metadata={"source": "aider"}
                    ))
                current_content = []

            current_role = "assistant"
            msg_id += 1

        elif line.startswith("## context"):
            # Skip context blocks
            continue

        else:
            if current_role is not None:
                current_content.append(line)

    # Save last message
    if current_role and current_content:
        content_text = "\n".join(current_content).strip()
        if content_text:
            messages.append(Message(
                id=str(uuid.uuid4()),
                role=current_role,
                content=content_text,
                timestamp="",
                metadata={"source": "aider"}
            ))

    return messages


def _find_aider_files() -> list[Path]:
    """Tìm tất cả Aider history files."""
    import os
    home = Path(os.path.expanduser("~"))

    candidates = [
        home / ".aider.chat.history.md",
        home / ".aider" / "chat.history.md",
        home / ".config" / "aider" / "chat.history.md",
        home / ".local" / "share" / "aider" / "chat.history.md",
    ]

    found = []
    for p in candidates:
        if p.exists():
            found.append(p)

    return found


class AiderAdapter:
    """Adapter để đọc session từ Aider."""

    name = "aider"
    description = "Aider (aider.chat)"

    def __init__(self):
        self.base = _get_aider_base()

    def is_available(self) -> bool:
        """Kiểm tra Aider có được cài đặt không."""
        return self.base.exists()

    def list_sessions(self) -> list[dict]:
        """List available Aider sessions."""
        sessions = []
        files = _find_aider_files()

        for f in files:
            msgs = _parse_aider_history(f)
            if not msgs:
                continue

            # Extract first user message as title
            title = ""
            for m in msgs:
                if m.role == "user":
                    title = m.content[:80].replace("\n", " ")
                    break

            sessions.append({
                "path": str(f),
                "session_id": f.stem or "aider-history",
                "project": str(f.parent.name),
                "cwd": "",
                "timestamp": "",
                "user_messages": sum(1 for m in msgs if m.role == "user"),
                "total_messages": len(msgs),
                "title": title,
            })

        return sessions

    def export(self, session_path: str | None = None, session_id: str | None = None) -> UniversalSession:
        """
        Export an Aider session to UniversalSession format.
        """
        if not self.is_available() and not session_path:
            raise RuntimeError("Aider history file not found.")

        target_path = None
        if session_path:
            target_path = Path(session_path)
        else:
            target_path = self.base

        if not target_path.exists():
            raise FileNotFoundError(f"Aider history not found: {target_path}")

        messages = _parse_aider_history(target_path)
        if not messages:
            raise RuntimeError("No messages found in Aider history.")

        token_count = sum(len(m.content) for m in messages) // 4

        return UniversalSession(
            id=f"aider-{uuid.uuid4().hex[:8]}",
            source="aider",
            messages=messages,
            metadata=SessionMetadata(
                source_agent="aider",
                original_session_id="aider-history",
                token_count=token_count,
            ),
            tags=["aider"],
        )
