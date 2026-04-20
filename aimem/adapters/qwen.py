"""
Qwen Adapter - Đọc session từ Qwen CLI / Qwen-Coder.
Storage: ~/.qwen/tmp/{hash}/logs.json (JSON array)
"""

from pathlib import Path
from typing import Literal
import json
import uuid

from ..models import UniversalSession, Message, ContextItem, SessionMetadata


def _get_qwen_base() -> Path:
    """Tìm thư mục gốc của Qwen config."""
    import os
    home = Path(os.path.expanduser("~"))
    return home / ".qwen"


def _find_all_logs() -> list[Path]:
    """Tìm tất cả logs.json files trong Qwen tmp dirs."""
    base = _get_qwen_base()
    tmp_dir = base / "tmp"

    if not tmp_dir.exists():
        return []

    logs_files = []
    for logs_path in tmp_dir.rglob("logs.json"):
        logs_files.append(logs_path)

    return sorted(logs_files, key=lambda p: p.stat().st_mtime, reverse=True)


def _parse_qwen_logs(logs_path: Path) -> list[dict]:
    """Parse Qwen logs.json file."""
    if not logs_path.exists():
        return []

    try:
        with open(logs_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and "messages" in data:
                return data["messages"]
    except (json.JSONDecodeError, OSError, IOError):
        pass

    return []


class QwenAdapter:
    """Adapter để đọc session từ Qwen CLI."""

    name = "qwen"
    description = "Qwen / Qwen-Coder CLI"

    def __init__(self):
        self.base = _get_qwen_base()

    def is_available(self) -> bool:
        """Kiểm tra Qwen CLI có được cài đặt không."""
        return self.base.exists()

    def list_sessions(self) -> list[dict]:
        """List all available Qwen sessions."""
        sessions = []
        logs_files = _find_all_logs()

        for logs_path in logs_files:
            msgs = _parse_qwen_logs(logs_path)
            if not msgs:
                continue

            # Get session ID from first message
            first = msgs[0]
            session_id = first.get("sessionId", logs_path.parent.name)

            # Find timestamp
            timestamp = first.get("timestamp", "")

            # Count
            user_msgs = sum(1 for m in msgs if m.get("type") == "user")

            # Extract title
            title = ""
            for m in msgs:
                if m.get("type") == "user":
                    msg = m.get("message", "")
                    if isinstance(msg, str) and msg:
                        title = msg[:80].replace("\n", " ")
                        break

            sessions.append({
                "path": str(logs_path),
                "session_id": session_id,
                "project": logs_path.parent.name[:16],
                "cwd": "",
                "timestamp": timestamp,
                "user_messages": user_msgs,
                "total_messages": len(msgs),
                "title": title,
            })

        return sessions

    def export(self, session_path: str | None = None, session_id: str | None = None) -> UniversalSession:
        """
        Export a Qwen session to UniversalSession format.
        """
        if not self.is_available():
            raise RuntimeError("Qwen CLI is not installed.")

        logs_path = None

        if session_path:
            logs_path = Path(session_path)
        elif session_id:
            # Search by session_id in the logs (not by directory name)
            base = _get_qwen_base()
            tmp_dir = base / "tmp"
            found = []

            for logs_file in tmp_dir.rglob("logs.json"):
                try:
                    with open(logs_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, list):
                        for entry in data:
                            if entry.get("sessionId", "").startswith(session_id):
                                found = [logs_file]
                                break
                    elif isinstance(data, dict) and data.get("sessionId", "").startswith(session_id):
                        found = [logs_file]
                except Exception:
                    continue

                if found:
                    break

            if not found:
                raise FileNotFoundError(f"Session not found: {session_id}")
            logs_path = found[0]
        else:
            # Get most recent
            logs_files = _find_all_logs()
            if not logs_files:
                raise RuntimeError("No Qwen sessions found.")
            logs_path = logs_files[0]

        raw_msgs = _parse_qwen_logs(logs_path)
        if not raw_msgs:
            raise RuntimeError(f"Session file is empty: {logs_path}")

        # Convert to Message objects
        messages = []
        for raw in raw_msgs:
            msg_type = raw.get("type", "user")
            content = raw.get("message", "")

            if isinstance(content, str) and not content.strip():
                continue

            role: Literal["system", "user", "assistant"] = "user"
            if msg_type in ("assistant", "ai", "qwen"):
                role = "assistant"
            elif msg_type == "system":
                role = "system"

            messages.append(Message(
                id=raw.get("messageId", str(uuid.uuid4())),
                role=role,
                content=content if isinstance(content, str) else str(content),
                timestamp=raw.get("timestamp", ""),
                metadata={}
            ))

        # Metadata
        first = raw_msgs[0]
        session_id_meta = first.get("sessionId", logs_path.parent.name)

        token_count = sum(len(m.content) for m in messages) // 4

        return UniversalSession(
            id=f"qwen-{session_id_meta[:8]}",
            source="qwen",
            messages=messages,
            metadata=SessionMetadata(
                source_agent="qwen",
                original_session_id=session_id_meta,
                token_count=token_count,
            ),
            created_at=first.get("timestamp", ""),
            updated_at=raw_msgs[-1].get("timestamp", ""),
            tags=["qwen"],
        )

    def inject(self, session: UniversalSession) -> Path:
        """
        Inject a UniversalSession vào Qwen CLI storage.
        Returns path to the new session file.
        """
        from datetime import datetime, timezone
        import hashlib

        tmp_dir = self.base / "tmp"
        if not tmp_dir.exists():
            tmp_dir.mkdir(parents=True, exist_ok=True)

        session_hash = hashlib.md5(session.id.encode()).hexdigest()[:12]
        session_dir = tmp_dir / session_hash
        if not session_dir.exists():
            session_dir.mkdir(parents=True, exist_ok=True)

        logs_file = session_dir / "logs.json"

        new_session_id = session.id.replace("claude-", "").replace("gemini-", "").replace("qwen-", "")[:16]
        ts = datetime.now(timezone.utc)

        entries = []
        for msg in session.messages:
            ts_str = msg.timestamp or ts.isoformat()
            entry = {
                "type": "user" if msg.role == "user" else "assistant",
                "messageId": msg.id or str(uuid.uuid4()),
                "sessionId": new_session_id,
                "timestamp": ts_str,
            }
            if msg.role == "user":
                entry["message"] = msg.content
            else:
                entry["message"] = msg.content
            entries.append(entry)

        with open(logs_file, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)

        return logs_file
