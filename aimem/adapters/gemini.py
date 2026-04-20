"""
Gemini Adapter - Đọc session từ Gemini CLI (Google).
Storage: ~/.config/gemini/ hoặc ~/.gemini/
Format: JSON + JSONL session files.
"""

from pathlib import Path
from typing import Literal
import json
import uuid

from ..models import UniversalSession, Message, SessionMetadata


def _get_gemini_base() -> Path:
    """Tìm thư mục gốc của Gemini CLI."""
    import os
    home = Path(os.path.expanduser("~"))

    # Try different possible locations
    candidates = [
        home / ".config" / "gemini",
        home / ".gemini",
        home / ".config" / "google" / "gemini",
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return candidates[0]  # Return default even if not exists


def _find_sessions_dirs(base: Path) -> list[Path]:
    """Tìm thư mục chứa sessions."""
    if not base.exists():
        return []

    # Common patterns: chats/, sessions/, data/
    patterns = ["chats", "sessions", "data", ""]
    dirs = []

    for pattern in patterns:
        if pattern:
            d = base / pattern
        else:
            d = base

        if d.exists() and d.is_dir():
            # Look for session files
            for ext in ("*.json", "*.jsonl", "*.chat"):
                dirs.extend(d.glob(ext))
            # Also check subdirs
            for subdir in d.iterdir():
                if subdir.is_dir():
                    for ext in ("*.json", "*.jsonl"):
                        dirs.extend(subdir.glob(ext))

    return dirs


class GeminiAdapter:
    """Adapter để đọc session từ Gemini CLI."""

    name = "gemini"
    description = "Google Gemini CLI"

    def __init__(self):
        self.base = _get_gemini_base()

    def is_available(self) -> bool:
        """Kiểm tra Gemini CLI có được cài đặt không."""
        return self.base.exists()

    def list_sessions(self) -> list[dict]:
        """List all available Gemini sessions."""
        sessions = []
        session_files = _find_sessions_dirs(self.base)

        for f in session_files:
            try:
                data = self._parse_file(f)
                if not data:
                    continue

                session_id = f.stem or f.name
                timestamp = ""
                title = ""

                if isinstance(data, list) and data:
                    timestamp = data[0].get("timestamp", "")
                    for item in data:
                        if item.get("type") == "user":
                            msg = item.get("message", "") or item.get("content", "")
                            if msg:
                                title = str(msg)[:80]
                                break
                elif isinstance(data, dict):
                    timestamp = data.get("timestamp", "") or data.get("createdAt", "")
                    title = data.get("title", data.get("name", ""))[:80]

                sessions.append({
                    "path": str(f),
                    "session_id": session_id,
                    "project": str(f.parent.name),
                    "cwd": "",
                    "timestamp": timestamp,
                    "user_messages": self._count_messages(data),
                    "total_messages": self._count_messages(data),
                    "title": title,
                })
            except Exception:
                continue

        return sorted(sessions, key=lambda s: s.get("timestamp", ""), reverse=True)

    def _parse_file(self, path: Path) -> dict | list | None:
        """Parse session file (JSON hoặc JSONL)."""
        try:
            if path.suffix == ".jsonl":
                messages = []
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            messages.append(json.loads(line))
                return messages
            else:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except (json.JSONDecodeError, OSError, IOError):
            return None

    def _count_messages(self, data) -> int:
        """Đếm số messages trong session."""
        if isinstance(data, list):
            return len(data)
        elif isinstance(data, dict):
            messages = data.get("messages", []) or data.get("history", [])
            if isinstance(messages, list):
                return len(messages)
        return 0

    def export(self, session_path: str | None = None, session_id: str | None = None) -> UniversalSession:
        """
        Export a Gemini session to UniversalSession format.
        """
        if not self.is_available():
            raise RuntimeError("Gemini CLI is not installed.")

        target_path = None

        if session_path:
            target_path = Path(session_path)
        elif session_id:
            # Search
            for f in _find_sessions_dirs(self.base):
                if session_id in f.stem or session_id in f.name:
                    target_path = f
                    break
            if not target_path:
                raise FileNotFoundError(f"Session not found: {session_id}")
        else:
            # Most recent
            files = _find_sessions_dirs(self.base)
            if files:
                # Sort by mtime
                files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                target_path = files[0]
            else:
                raise RuntimeError("No Gemini sessions found.")

        raw_data = self._parse_file(target_path)
        if not raw_data:
            raise RuntimeError(f"Cannot parse session file: {target_path}")

        # Convert to messages
        messages = []
        if isinstance(raw_data, list):
            items = raw_data
        elif isinstance(raw_data, dict):
            items = raw_data.get("messages", []) or raw_data.get("history", [])
            if not isinstance(items, list):
                items = [items]

        for item in items:
            msg_type = item.get("type", "user")
            content = item.get("message", "") or item.get("content", "") or item.get("text", "")

            if not content:
                continue

            role: Literal["system", "user", "assistant"] = "user"
            if msg_type in ("model", "assistant", "gemini"):
                role = "assistant"
            elif msg_type == "system":
                role = "system"

            messages.append(Message(
                id=str(uuid.uuid4()),
                role=role,
                content=str(content),
                timestamp=item.get("timestamp", ""),
                metadata={}
            ))

        session_id_meta = target_path.stem or session_id or "unknown"

        token_count = sum(len(m.content) for m in messages) // 4

        return UniversalSession(
            id=f"gemini-{session_id_meta[:8]}",
            source="gemini",
            messages=messages,
            metadata=SessionMetadata(
                source_agent="gemini",
                original_session_id=session_id_meta,
                token_count=token_count,
            ),
            created_at=items[0].get("timestamp", "") if items else "",
            updated_at=items[-1].get("timestamp", "") if items else "",
            tags=["gemini"],
        )

    def inject(self, session: UniversalSession, project_path: str | None = None) -> Path:
        """
        Inject a UniversalSession into Gemini CLI storage.
        Returns path to the new session file.
        
        Usage:
        - After inject, run: cd <project_path> && gemini --resume latest
        """
        from datetime import datetime, timezone
        import hashlib
        import uuid
        import os

        tmp_dir = self.base / "tmp"
        if not tmp_dir.exists():
            tmp_dir.mkdir(parents=True, exist_ok=True)

        # Use original project path for proper session linkage
        cwd = project_path or session.metadata.project_path or os.getcwd()
        project_name = Path(cwd).name
        project_hash = hashlib.sha256(cwd.encode()).hexdigest()

        project_dir = tmp_dir / project_name
        if not project_dir.exists():
            project_dir.mkdir(parents=True, exist_ok=True)

        chats_dir = project_dir / "chats"
        if not chats_dir.exists():
            chats_dir.mkdir(parents=True, exist_ok=True)

        new_session_id = str(uuid.uuid4())
        ts = datetime.now(timezone.utc)
        session_file = chats_dir / f"session-{ts.strftime('%Y-%m-%dT%H-%M-%S')}-{new_session_id[:8]}.json"

        messages = []
        for i, msg in enumerate(session.messages):
            msg_ts = ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
            msg_id = str(uuid.uuid4())

            entry = {
                "id": msg_id,
                "timestamp": msg_ts,
                "type": "user" if msg.role == "user" else "gemini",
                "content": [{"text": msg.content}],
            }
            messages.append(entry)

        session_data = {
            "sessionId": new_session_id,
            "projectHash": project_hash,
            "startTime": ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "lastUpdated": ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "messages": messages,
        }

        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(session_data, f, indent=2, ensure_ascii=False)

        # Write .project_root file for Gemini to recognize this project
        project_root_file = project_dir / ".project_root"
        project_root_file.write_text(cwd)

        # Update logs.json to register this session
        logs_file = project_dir / "logs.json"
        logs_entry = {
            "sessionId": new_session_id,
            "messageId": 0,
            "type": "user",
            "message": "[Session transferred from " + session.metadata.source_agent + "]",
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        }
        
        if logs_file.exists():
            try:
                existing = json.loads(logs_file.read_text())
                if isinstance(existing, list):
                    existing.append(logs_entry)
                    logs_file.write_text(json.dumps(existing, indent=2))
            except Exception:
                logs_file.write_text(json.dumps([logs_entry], indent=2))
        else:
            logs_file.write_text(json.dumps([logs_entry], indent=2))

        return session_file
