"""
OpenCode Adapter - read/write sessions for OpenCode CLI.
Reads via the real CLI/database storage under ~/.local/share/opencode.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
import hashlib
import json
import os
import random
import shutil
import sqlite3
import string
import subprocess
import uuid

from ..models import UniversalSession, Message, SessionMetadata


def _get_opencode_db() -> Path:
    home = Path(os.path.expanduser("~"))
    return home / ".local" / "share" / "opencode" / "opencode.db"


def _run_opencode(args: list[str]) -> subprocess.CompletedProcess[str]:
    binary = (
        shutil.which("opencode.cmd")
        or shutil.which("opencode.exe")
        or shutil.which("opencode")
        or "opencode"
    )
    return subprocess.run(
        [binary, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )


def _generate_session_id() -> str:
    chars = string.ascii_letters + string.digits
    return "ses_" + "".join(random.choices(chars, k=22))


def _generate_message_id(prefix: str) -> str:
    chars = string.ascii_letters + string.digits
    return prefix + "".join(random.choices(chars, k=22))


def _project_id_for_directory(cur: sqlite3.Cursor, cwd: str, ts: int) -> str:
    row = cur.execute(
        "select id from project where worktree=? order by time_updated desc limit 1",
        (cwd,),
    ).fetchone()
    if row:
        return row[0]

    project_id = hashlib.sha1(cwd.encode("utf-8", errors="replace")).hexdigest()
    vcs = "git" if (Path(cwd) / ".git").exists() else None
    cur.execute(
        """
        insert into project (
            id, worktree, vcs, name, icon_url, icon_color,
            time_created, time_updated, time_initialized, sandboxes, commands
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_id,
            cwd,
            vcs,
            None,
            None,
            None,
            ts,
            ts,
            None,
            "[]",
            None,
        ),
    )
    return project_id


def _safe_slug(text: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in text).strip("-")
    return cleaned[:80] or "transferred-session"


def _pick_model_info(session: UniversalSession) -> tuple[str, str]:
    model = session.metadata.model or ""
    lowered = model.lower()
    if "ollama" in lowered:
        return "ollama", model.split(":", 1)[-1] or model
    if "openai" in lowered:
        return "openai", model.split(":", 1)[-1] or model
    if model:
        return "opencode", model
    return "opencode", "minimax-m2.5-free"


class OpenCodeAdapter:
    name = "opencode"
    description = "OpenCode CLI"

    def __init__(self):
        self.db_path = _get_opencode_db()

    def is_available(self) -> bool:
        return self.db_path.exists()

    def list_sessions(self) -> list[dict]:
        if not self.is_available():
            return []

        sessions = []
        connection = sqlite3.connect(self.db_path)
        try:
            cursor = connection.cursor()
            rows = cursor.execute(
                """
                select id, title, directory, time_created, time_updated
                from session
                where time_archived is null
                order by time_updated desc
                """
            ).fetchall()
        finally:
            connection.close()

        for session_id, title, directory, created, updated in rows:
            timestamp = datetime.fromtimestamp(updated / 1000, tz=timezone.utc).isoformat() if updated else ""
            sessions.append({
                "path": session_id,
                "session_id": session_id,
                "project": Path(directory or "").name,
                "cwd": directory or "",
                "timestamp": timestamp,
                "title": title or "",
            })
        return sessions

    def export(self, session_path: str | None = None, session_id: str | None = None) -> UniversalSession:
        if not self.is_available():
            raise RuntimeError("OpenCode CLI is not installed.")

        target_session = session_id or session_path
        if not target_session:
            sessions = self.list_sessions()
            if not sessions:
                raise RuntimeError("No OpenCode sessions found.")
            target_session = sessions[0]["session_id"]

        result = _run_opencode(["export", str(target_session)])
        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(stderr or f"Failed to export OpenCode session: {target_session}")

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Unexpected OpenCode export output: {exc}") from exc

        info = data.get("info", {})
        messages_data = data.get("messages", [])
        messages: list[Message] = []

        for msg in messages_data:
            msg_info = msg.get("info", {})
            role_raw = msg_info.get("role", "user")
            role: Literal["system", "user", "assistant"] = "user"
            if role_raw == "assistant":
                role = "assistant"
            elif role_raw in ("system", "developer"):
                role = "system"

            content_parts: list[str] = []
            tool_calls: list[dict] = []
            for part in msg.get("parts", []):
                part_type = part.get("type")
                if part_type == "text":
                    text = part.get("text", "")
                    if text and not part.get("synthetic"):
                        content_parts.append(text)
                elif part_type == "reasoning":
                    text = part.get("text", "")
                    if text:
                        content_parts.append(f"[Thinking: {text}]")
                elif part_type == "tool":
                    tool = part.get("tool", "")
                    if tool:
                        content_parts.append(f"[Tool: {tool}]")
                    tool_calls.append(part)

            content = "\n".join(part for part in content_parts if part).strip()
            if not content and not tool_calls:
                continue

            created = msg_info.get("time", {}).get("created")
            timestamp = ""
            if isinstance(created, (int, float)):
                timestamp = datetime.fromtimestamp(created / 1000, tz=timezone.utc).isoformat()

            messages.append(Message(
                id=msg_info.get("id", str(uuid.uuid4())),
                role=role,
                content=content,
                timestamp=timestamp,
                tool_calls=tool_calls,
                metadata={
                    "parent_id": msg_info.get("parentID"),
                    "agent": msg_info.get("agent"),
                    "mode": msg_info.get("mode"),
                    "provider_id": msg_info.get("providerID") or msg_info.get("model", {}).get("providerID"),
                    "model_id": msg_info.get("modelID") or msg_info.get("model", {}).get("modelID"),
                },
            ))

        created_ts = info.get("time", {}).get("created", 0)
        updated_ts = info.get("time", {}).get("updated", 0)
        created_at = datetime.fromtimestamp(created_ts / 1000, tz=timezone.utc).isoformat() if created_ts else ""
        updated_at = datetime.fromtimestamp(updated_ts / 1000, tz=timezone.utc).isoformat() if updated_ts else ""

        return UniversalSession(
            id=f"opencode-{info.get('id', str(target_session))[:8]}",
            source="opencode",
            messages=messages,
            metadata=SessionMetadata(
                source_agent="opencode",
                original_session_id=info.get("id", str(target_session)),
                project_path=info.get("directory", ""),
                token_count=sum(len(message.content) for message in messages) // 4,
                version=info.get("version", ""),
            ),
            created_at=created_at,
            updated_at=updated_at,
            tags=["opencode"],
            note=info.get("title", ""),
        )

    def inject(self, session: UniversalSession) -> Path:
        if not self.is_available():
            raise RuntimeError("OpenCode CLI is not installed.")

        cwd = session.metadata.project_path or os.getcwd()
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        new_session_id = _generate_session_id()
        provider_id, model_id = _pick_model_info(session)
        title = session.note or f"Transferred from {session.metadata.source_agent}"
        slug = _safe_slug(title)
        message_rows: list[tuple[str, int, int, str]] = []
        part_rows: list[tuple[str, str, int, int, str]] = []
        previous_id: str | None = None

        current_time = now_ms
        for msg in session.messages:
            if msg.role not in ("user", "assistant"):
                continue

            created = current_time
            current_time += 1000
            updated = current_time
            message_id = _generate_message_id("msg_")
            if msg.role == "user":
                data = {
                    "role": "user",
                    "time": {"created": created},
                    "agent": "build",
                    "model": {
                        "providerID": provider_id,
                        "modelID": model_id,
                    },
                    "summary": {"diffs": []},
                }
            else:
                data = {
                    "role": "assistant",
                    "mode": "build",
                    "agent": "build",
                    "path": {"cwd": cwd, "root": cwd},
                    "cost": 0,
                    "tokens": {
                        "total": 0,
                        "input": 0,
                        "output": 0,
                        "reasoning": 0,
                        "cache": {"read": 0, "write": 0},
                    },
                    "modelID": model_id,
                    "providerID": provider_id,
                    "time": {"created": created, "completed": updated},
                    "finish": "stop",
                }
            if previous_id:
                data["parentID"] = previous_id

            message_rows.append((message_id, created, updated, json.dumps(data, ensure_ascii=False)))

            text = (msg.content or "").strip()
            if text:
                part_rows.append((
                    _generate_message_id("prt_"),
                    message_id,
                    created,
                    created,
                    json.dumps({"type": "text", "text": text}, ensure_ascii=False),
                ))

            previous_id = message_id

        if not message_rows:
            raise RuntimeError("Session has no user/assistant messages to inject.")

        final_updated = message_rows[-1][2]
        version = session.metadata.version or "1.14.19"

        connection = sqlite3.connect(self.db_path)
        try:
            cursor = connection.cursor()
            project_id = _project_id_for_directory(cursor, cwd, now_ms)
            cursor.execute(
                """
                insert into session (
                    id, project_id, parent_id, slug, directory, title, version, share_url,
                    summary_additions, summary_deletions, summary_files, summary_diffs, revert,
                    permission, time_created, time_updated, time_compacting, time_archived, workspace_id
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_session_id,
                    project_id,
                    None,
                    slug,
                    cwd,
                    title,
                    version,
                    None,
                    0,
                    0,
                    0,
                    None,
                    None,
                    None,
                    message_rows[0][1],
                    final_updated,
                    None,
                    None,
                    None,
                ),
            )

            for message_id, created, updated, data in message_rows:
                cursor.execute(
                    "insert into message (id, session_id, time_created, time_updated, data) values (?, ?, ?, ?, ?)",
                    (message_id, new_session_id, created, updated, data),
                )

            for part_id, message_id, created, updated, data in part_rows:
                cursor.execute(
                    "insert into part (id, message_id, session_id, time_created, time_updated, data) values (?, ?, ?, ?, ?, ?)",
                    (part_id, message_id, new_session_id, created, updated, data),
                )

            connection.commit()
        finally:
            connection.close()

        return Path(new_session_id)
