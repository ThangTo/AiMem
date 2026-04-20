"""
OpenCode Adapter - Đọc/ghi session từ OpenCode CLI.
Storage: ~/.opencode/sessions/{session_id}.json
Format: JSON với info, messages, parts.
"""

from pathlib import Path
from datetime import datetime, timezone
from typing import Literal
import json
import uuid
import os

from ..models import UniversalSession, Message, SessionMetadata


def _get_opencode_base() -> Path:
    """Tìm thư mục gốc của OpenCode config."""
    home = Path(os.path.expanduser("~"))
    candidates = [
        home / ".opencode",
        home / "AppData" / "Local" / "opencode",
        home / "AppData" / "Roaming" / "opencode",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return home / ".opencode"


def _find_sessions_dir() -> Path:
    """Tìm thư mục chứa sessions."""
    base = _get_opencode_base()
    sessions_dir = base / "sessions"
    if sessions_dir.exists():
        return sessions_dir
    return base


def _find_all_session_files() -> list[Path]:
    """Tìm tất cả OpenCode session files."""
    sessions_dir = _find_sessions_dir()
    if not sessions_dir.exists():
        return []

    files = []
    for json_file in sessions_dir.glob("ses_*.json"):
        files.append(json_file)

    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def _generate_session_id() -> str:
    """Generate OpenCode session ID format: ses_xxx."""
    import random
    import string
    import time
    chars = string.ascii_letters + string.digits
    random_part = ''.join(random.choices(chars, k=22))
    return f"ses_{random_part}"


def _generate_message_id(ts: int = None, seq: int = 0) -> str:
    """Generate OpenCode message ID format: msg_<ulid_lowercase>."""
    try:
        import ulid
        new_ulid = ulid.new()
        return f"msg_{str(new_ulid).lower()}"
    except ImportError:
        import random
        import string
        import time
        
        if ts is None:
            ts = int(time.time() * 1000)
        
        hex_ts = hex(ts)[2:13].zfill(11)[-11:]
        chars = string.ascii_letters + string.digits
        random_suffix = ''.join(random.choices(chars, k=14))
        
        return f"msg_{hex_ts}{seq % 10}{random_suffix}"


class OpenCodeAdapter:
    """Adapter để đọc/ghi session từ OpenCode CLI."""

    name = "opencode"
    description = "OpenCode CLI"

    def __init__(self):
        self.base = _get_opencode_base()

    def is_available(self) -> bool:
        """Kiểm tra OpenCode có được cài đặt không."""
        return self.base.exists()

    def list_sessions(self) -> list[dict]:
        """List all available OpenCode sessions."""
        sessions = []
        files = _find_all_session_files()

        for f in files:
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    data = json.load(fp)

                info = data.get("info", {})
                session_id = info.get("id", f.stem)
                title = info.get("title", "")
                timestamp = info.get("time", {}).get("updated", 0)
                
                if timestamp:
                    try:
                        ts = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
                        timestamp_str = ts.isoformat()
                    except Exception:
                        timestamp_str = ""
                else:
                    timestamp_str = ""

                messages = data.get("messages", [])
                user_msgs = sum(1 for m in messages if m.get("info", {}).get("role") == "user")

                sessions.append({
                    "path": str(f),
                    "session_id": session_id,
                    "project": info.get("directory", "").split("/")[-1] if info.get("directory") else "",
                    "cwd": info.get("directory", ""),
                    "timestamp": timestamp_str,
                    "user_messages": user_msgs,
                    "total_messages": len(messages),
                    "title": title,
                })
            except Exception:
                continue

        return sessions

    def export(self, session_path: str | None = None, session_id: str | None = None) -> UniversalSession:
        """Export an OpenCode session to UniversalSession format."""
        if not self.is_available():
            raise RuntimeError("OpenCode CLI is not installed.")

        target_path = None

        if session_path:
            target_path = Path(session_path)
        elif session_id:
            files = _find_all_session_files()
            for f in files:
                if session_id in f.stem or f.stem == session_id:
                    target_path = f
                    break
            if not target_path:
                raise FileNotFoundError(f"Session not found: {session_id}")
        else:
            files = _find_all_session_files()
            if not files:
                raise RuntimeError("No OpenCode sessions found.")
            target_path = files[0]

        with open(target_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        info = data.get("info", {})
        messages_data = data.get("messages", [])

        messages = []
        for msg in messages_data:
            msg_info = msg.get("info", {})
            role: Literal["system", "user", "assistant"] = msg_info.get("role", "user")
            
            parts = msg.get("parts", [])
            content_parts = []
            for part in parts:
                if part.get("type") == "text":
                    text = part.get("text", "")
                    if not part.get("synthetic"):
                        content_parts.append(text)

            content = "\n".join(content_parts)
            if not content.strip():
                continue

            messages.append(Message(
                id=msg_info.get("id", str(uuid.uuid4())),
                role=role,
                content=content,
                timestamp="",
                metadata={}
            ))

        session_id_meta = info.get("id", target_path.stem)
        cwd = info.get("directory", "")
        title = info.get("title", "")

        token_count = sum(len(m.content) for m in messages) // 4

        created_ts = info.get("time", {}).get("created", 0)
        created_at = ""
        if created_ts:
            try:
                created_at = datetime.fromtimestamp(created_ts / 1000, tz=timezone.utc).isoformat()
            except Exception:
                pass

        return UniversalSession(
            id=f"opencode-{session_id_meta[:8]}",
            source="opencode",
            messages=messages,
            metadata=SessionMetadata(
                source_agent="opencode",
                original_session_id=session_id_meta,
                project_path=cwd,
                token_count=token_count,
            ),
            created_at=created_at,
            updated_at=created_at,
            tags=["opencode"],
            note=title,
        )

    def inject(self, session: UniversalSession) -> Path:
        """
        Inject a UniversalSession vào OpenCode storage.
        Uses direct database insert (bypasses opencode import bug).
        Returns path to the exported file.
        """
        import subprocess
        import shutil
        import sqlite3
        import json as json_lib

        tmp_dir = Path.home() / ".aimem" / "tmp"
        if not tmp_dir.exists():
            tmp_dir.mkdir(parents=True, exist_ok=True)

        new_session_id = _generate_session_id()
        ts = int(datetime.now(timezone.utc).timestamp() * 1000)

        cwd = session.metadata.project_path or os.getcwd()

        # First, create the export file (for backup)
        messages_data = []
        prev_msg_id = None
        msg_ids = []  # Store msg_ids for DB insert

        for i, msg in enumerate(session.messages):
            msg_ts = ts + i * 1000
            msg_id = _generate_message_id(msg_ts, i)
            msg_ids.append(msg_id)

            parts = []
            if msg.content.strip():
                parts.append({
                    "type": "text",
                    "text": msg.content,
                })

            if msg.role == "user":
                msg_info = {
                    "role": "user",
                    "time": {"created": msg_ts},
                    "agent": "build",
                    "model": {
                        "providerID": "opencode",
                        "modelID": "minimax-m2.5-free"
                    },
                    "summary": {"diffs": []},
                }
            else:
                msg_info = {
                    "role": "assistant",
                    "mode": "build",
                    "agent": "build",
                    "path": {
                        "cwd": cwd,
                        "root": "/"
                    },
                    "cost": 0,
                    "tokens": {
                        "total": 0,
                        "input": 0,
                        "output": 0,
                        "reasoning": 0,
                        "cache": {"write": 0, "read": 0}
                    },
                    "modelID": "minimax-m2.5-free",
                    "providerID": "opencode",
                    "time": {"created": msg_ts, "completed": msg_ts + 1000},
                    "finish": "stop",
                }

            # Add parentID only for messages after the first
            if prev_msg_id is not None:
                msg_info["parentID"] = prev_msg_id

            messages_data.append({
                "msg_id": msg_id,
                "msg_ts": msg_ts,
                "info": msg_info,
                "parts": parts,
            })
            prev_msg_id = msg_id

        session_info = {
            "id": new_session_id,
            "slug": f"transferred-from-{session.metadata.source_agent}",
            "projectID": "global",
            "directory": cwd,
            "title": session.note or f"Transferred from {session.metadata.source_agent}",
            "version": "1.14.18",
            "summary": {"additions": 0, "deletions": 0, "files": 0},
            "time": {"created": ts, "updated": ts},
        }

        # Direct database insert (bypass opencode import)
        db_path = Path.home() / ".local" / "share" / "opencode" / "opencode.db"

        if not db_path.exists():
            db_path = Path(os.environ.get('APPDATA', '')) / "opencode" / "opencode.db"

        if not db_path.exists():
            db_path = Path.home() / "AppData" / "Roaming" / "opencode" / "opencode.db"

        try:
            conn = sqlite3.connect(str(db_path))
            c = conn.cursor()

            # Look up project_id based on directory
            c.execute("SELECT id FROM project WHERE worktree = ?", (cwd,))
            project_row = c.fetchone()
            if project_row:
                project_id = project_row[0]
            else:
                # Create new project if not exists
                import hashlib
                project_id = hashlib.sha1(cwd.encode()).hexdigest()[:40]
                c.execute('''
                    INSERT INTO project (id, worktree, vcs, name, time_created, time_updated, sandboxes, commands)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (project_id, cwd, "git", None, ts, ts, "[]", None))

            # Insert session - include summary fields
            c.execute('''
                INSERT INTO session (id, project_id, slug, directory, title, version,
                                    summary_additions, summary_deletions, summary_files,
                                    time_created, time_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                new_session_id,
                project_id,
                session_info["slug"],
                session_info["directory"],
                session_info["title"],
                session_info["version"],
                0, 0, 0,
                ts, ts
            ))

            # Insert messages
            for msg_data in messages_data:
                msg_id = msg_data["msg_id"]
                msg_ts = msg_data["msg_ts"]
                info = msg_data["info"]
                parts = msg_data["parts"]

                c.execute('''
                    INSERT INTO message (id, session_id, time_created, time_updated, data)
                    VALUES (?, ?, ?, ?, ?)
                ''', (
                    msg_id,
                    new_session_id,
                    msg_ts,
                    msg_ts,
                    json_lib.dumps(info)
                ))

                for part in parts:
                    part_id = f"prt_{uuid.uuid4().hex[:22]}"
                    c.execute('''
                        INSERT INTO part (id, message_id, session_id, time_created, time_updated, data)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (
                        part_id,
                        msg_id,
                        new_session_id,
                        msg_ts,
                        msg_ts,
                        json_lib.dumps(part)
                    ))

            conn.commit()
            conn.close()

            return Path(new_session_id)

        except Exception as e:
            import traceback
            traceback.print_exc()
            # Fallback to file export if DB insert fails
            session_data = {
                "info": session_info,
                "messages": messages_data,
            }
            export_file = tmp_dir / f"opencode-import-{new_session_id}.json"
            with open(export_file, "w", encoding="utf-8") as f:
                json_lib.dump(session_data, f, indent=2)

            try:
                opencode_exe = shutil.which("opencode")
                if opencode_exe:
                    subprocess.run(
                        [opencode_exe, "import", str(export_file)],
                        capture_output=True,
                        timeout=60,
                        cwd=cwd,
                        shell=True
                    )
            except Exception:
                pass

            return export_file