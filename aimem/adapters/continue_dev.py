"""
Continue.dev Adapter - Đọc session từ Continue.dev (VS Code / JetBrains).
Storage: ~/.continue/sessions/ (SQLite + JSON)
Format: SQLite database hoặc JSON session files.
"""

from pathlib import Path
from datetime import datetime, timezone
from typing import Literal
import json
import uuid
import sqlite3

from ..models import UniversalSession, Message, SessionMetadata


def _get_continue_base() -> Path:
    """Tìm thư mục gốc của Continue.dev config."""
    import os
    home = Path(os.path.expanduser("~"))

    candidates = [
        home / ".continue",
        home / ".continue-dev",
        home / "AppData" / "Roaming" / "continue",
        home / ".config" / "continue",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return candidates[0]


def _find_sessions_sqlite(base: Path) -> list[Path]:
    """Tìm SQLite database chứa sessions."""
    if not base.exists():
        return []

    db_candidates = [
        base / "sessions.db",
        base / "continue.db",
        base / "history.db",
    ]

    for db_path in db_candidates:
        if db_path.exists():
            return [db_path]

    # Search recursively
    for db_path in base.rglob("*.db"):
        if db_path.name in ("sessions.db", "history.db", "continue.db"):
            return [db_path]

    return []


def _query_sessions_from_sqlite(db_path: Path) -> list[dict]:
    """Đọc sessions từ SQLite database."""
    sessions = []
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Try to read sessions table
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table'
            AND name NOT LIKE 'sqlite_%'
        """)
        tables = [row[0] for row in cursor.fetchall()]

        for table in tables:
            try:
                cursor.execute(f"SELECT * FROM {table} LIMIT 1")
                cols = [desc[0] for desc in cursor.description]
            except sqlite3.OperationalError:
                continue

            # Look for session-like tables
            session_cols = {"id", "session_id", "history", "messages", "created_at", "timestamp"}
            if any(c.lower() in session_cols for c in cols):
                try:
                    cursor.execute(f"SELECT * FROM {table}")
                    rows = cursor.fetchall()

                    for row in rows:
                        row_dict = dict(zip(cols, row))

                        # Extract relevant fields
                        session_id = str(row_dict.get("id", row_dict.get("session_id", "")))

                        # Try to find history/messages
                        history_json = row_dict.get("history") or row_dict.get("messages") or row_dict.get("content")
                        if isinstance(history_json, str):
                            try:
                                messages = json.loads(history_json)
                            except json.JSONDecodeError:
                                messages = []
                        elif isinstance(history_json, list):
                            messages = history_json
                        else:
                            messages = []

                        title = ""
                        if messages:
                            for m in messages:
                                if isinstance(m, dict):
                                    c = m.get("content", "") or m.get("message", "") or m.get("text", "")
                                    if c:
                                        title = str(c)[:80].replace("\n", " ")
                                        break
                                elif isinstance(m, str) and m:
                                    title = m[:80].replace("\n", " ")
                                    break

                        timestamp = row_dict.get("created_at", "") or row_dict.get("timestamp", "")
                        if isinstance(timestamp, (int, float)):
                            timestamp = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()

                        sessions.append({
                            "path": str(db_path),
                            "session_id": session_id,
                            "table": table,
                            "timestamp": timestamp,
                            "title": title,
                            "raw_messages": messages,
                            "total_messages": len(messages) if isinstance(messages, list) else 0,
                        })
                except (sqlite3.OperationalError, json.JSONDecodeError):
                    continue

        conn.close()
    except sqlite3.Error:
        pass

    return sessions


def _find_json_sessions(base: Path) -> list[Path]:
    """Tìm JSON session files."""
    if not base.exists():
        return []

    patterns = [
        base / "sessions",
        base / "history",
        base / "conversations",
    ]

    files = []
    for d in patterns:
        if d.exists():
            files.extend(path for path in d.glob("*.json") if path.name != "sessions.json")
            files.extend(d.glob("*.jsonl"))

    if not files:
        files.extend(base.rglob("session-*.json"))
        files.extend(base.rglob("conversation-*.json"))

    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def _parse_json_session(path: Path) -> tuple[list[dict], str]:
    """Parse JSON session file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        title = ""
        messages = []

        if isinstance(data, list):
            messages = data
            if messages:
                first = messages[0]
                if isinstance(first, dict):
                    title = str(first.get("content", "") or first.get("message", ""))[:80]
        elif isinstance(data, dict):
            messages = data.get("messages", []) or data.get("history", []) or data.get("conversation", [])
            title = str(data.get("title", data.get("name", "")))[:80]
            if isinstance(messages, dict):
                messages = messages.get("messages", [])

        timestamp = ""
        if messages and isinstance(messages[0], dict):
            timestamp = messages[0].get("timestamp", "") or messages[0].get("created_at", "")

        return messages, title, timestamp, str(path)
    except (json.JSONDecodeError, OSError):
        return [], "", "", ""


class ContinueAdapter:
    """Adapter để đọc session từ Continue.dev."""

    name = "continue"
    description = "Continue.dev (VS Code / JetBrains)"

    def __init__(self):
        self.base = _get_continue_base()

    def is_available(self) -> bool:
        """Kiểm tra Continue.dev có được cài đặt không."""
        return self.base.exists()

    def list_sessions(self) -> list[dict]:
        """List all available Continue.dev sessions."""
        sessions = []

        # From SQLite
        db_files = _find_sessions_sqlite(self.base)
        for db_path in db_files:
            sess_list = _query_sessions_from_sqlite(db_path)
            sessions.extend(sess_list)

        # From JSON files
        json_files = _find_json_sessions(self.base)
        for f in json_files:
            messages, title, timestamp, path = _parse_json_session(f)
            if messages:
                sessions.append({
                    "path": path,
                    "session_id": f.stem,
                    "timestamp": timestamp,
                    "title": title,
                    "total_messages": len(messages),
                })

        # Sort by timestamp
        sessions.sort(key=lambda s: s.get("timestamp", ""), reverse=True)
        return sessions

    def export(self, session_path: str | None = None, session_id: str | None = None) -> UniversalSession:
        """
        Export a Continue.dev session to UniversalSession format.
        """
        if not self.is_available():
            raise RuntimeError("Continue.dev is not installed.")

        messages: list[Message] = []
        session_id_meta = session_id or "unknown"
        title = ""

        # Try SQLite first
        if not session_path:
            db_files = _find_sessions_sqlite(self.base)
            if db_files:
                sess_list = _query_sessions_from_sqlite(db_files[0])
                if session_id:
                    for s in sess_list:
                        if s.get("session_id") == session_id or session_id in str(s.get("session_id", "")):
                            raw_msgs = s.get("raw_messages", [])
                            messages = self._convert_messages(raw_msgs)
                            session_id_meta = s.get("session_id", session_id)
                            title = s.get("title", "")
                            break
                elif sess_list:
                    # Use most recent
                    s = sess_list[0]
                    raw_msgs = s.get("raw_messages", [])
                    messages = self._convert_messages(raw_msgs)
                    session_id_meta = s.get("session_id", "unknown")
                    title = s.get("title", "")

        # Fallback to JSON
        if not messages:
            json_files = _find_json_sessions(self.base)
            target = None
            if session_path:
                target = Path(session_path)
            elif session_id:
                for f in json_files:
                    if session_id in f.stem or session_id in f.name:
                        target = f
                        break
                if not target:
                    target = json_files[0] if json_files else None
            else:
                target = json_files[0] if json_files else None

            if target and target.exists():
                raw_msgs, title, timestamp, path = _parse_json_session(target)
                messages = self._convert_messages(raw_msgs)
                session_id_meta = target.stem

        if not messages:
            raise RuntimeError("No Continue.dev sessions found or session is empty.")

        token_count = sum(len(m.content) for m in messages) // 4

        return UniversalSession(
            id=f"continue-{session_id_meta[:8]}",
            source="continue",
            messages=messages,
            metadata=SessionMetadata(
                source_agent="continue",
                original_session_id=session_id_meta,
                project_path=str(self.base),
                model="continue",
                token_count=token_count,
            ),
            tags=["continue"],
            note=title,
        )

    def _convert_messages(self, raw_msgs: list) -> list[Message]:
        """Convert raw messages to Message objects."""
        messages = []
        for raw in raw_msgs:
            if isinstance(raw, str):
                content = raw
                role = "user"
            elif isinstance(raw, dict):
                content = raw.get("content", "") or raw.get("message", "") or raw.get("text", "")
                role_raw = raw.get("role", "user")
                role = "user"
                if role_raw in ("assistant", "ai", "model", "bot"):
                    role = "assistant"
                elif role_raw == "system":
                    role = "system"
            else:
                continue

            if not content:
                continue

            messages.append(Message(
                id=str(uuid.uuid4()),
                role=role,  # type: ignore
                content=str(content),
                timestamp=raw.get("timestamp", "") if isinstance(raw, dict) else "",
                metadata={}
            ))

        return messages
