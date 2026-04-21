"""
Gemini Adapter - read/write Gemini CLI sessions from local storage.

Observed storage on this machine:
- ~/.gemini/sessions/YYYY-MM-DD/chat-*.json         (archived transcript)
- ~/.gemini/tmp/<project-slug>/chats/session-*.json (resume-able project session)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
import hashlib
import json
import os
import re
import uuid

from ..models import Message, SessionMetadata, UniversalSession


def _get_gemini_base() -> Path:
    """Return Gemini CLI storage base directory."""
    home = Path(os.path.expanduser("~"))
    candidates = [
        home / ".gemini",
        home / ".config" / "gemini",
        home / ".config" / "google" / "gemini",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _load_projects(base: Path) -> dict[str, str]:
    """Load cwd -> project-slug mapping from Gemini."""
    projects_file = base / "projects.json"
    if not projects_file.exists():
        return {}

    try:
        data = json.loads(projects_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}

    projects = data.get("projects", {})
    if isinstance(projects, dict):
        return {str(k): str(v) for k, v in projects.items()}
    return {}


def _save_projects(base: Path, projects: dict[str, str]) -> None:
    """Persist Gemini's projects.json mapping."""
    projects_file = base / "projects.json"
    payload = {"projects": dict(sorted(projects.items()))}
    projects_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _normalize_cwd(path: str) -> str:
    return str(Path(path)).replace("/", "\\").lower()


def _slugify_project_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9._-]+", "-", name.lower()).strip("-")
    return slug or "default"


def _ensure_project_slug(base: Path, cwd: str) -> str:
    projects = _load_projects(base)
    normalized = _normalize_cwd(cwd)
    if normalized in projects:
        return projects[normalized]

    slug = _slugify_project_name(Path(cwd).name or "default")
    projects[normalized] = slug
    base.mkdir(parents=True, exist_ok=True)
    _save_projects(base, projects)
    return slug


def _reverse_projects(base: Path) -> dict[str, str]:
    return {slug: cwd for cwd, slug in _load_projects(base).items()}


def _iter_archive_session_files(base: Path) -> list[Path]:
    sessions_dir = base / "sessions"
    if not sessions_dir.exists():
        return []
    return sorted(sessions_dir.glob("**/chat-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def _iter_tmp_session_files(base: Path) -> list[Path]:
    tmp_dir = base / "tmp"
    if not tmp_dir.exists():
        return []
    return sorted(tmp_dir.glob("*/chats/session-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def _find_session_files(base: Path) -> list[Path]:
    seen: set[Path] = set()
    files: list[Path] = []
    for path in [*_iter_tmp_session_files(base), *_iter_archive_session_files(base)]:
        if path not in seen:
            seen.add(path)
            files.append(path)
    return files


def _parse_json(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _flatten_content(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [_flatten_content(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        parts: list[str] = []
        for key in ("text", "message", "content", "output", "description", "reasoning"):
            text = _flatten_content(value.get(key))
            if text:
                parts.append(text)
        return "\n".join(part for part in parts if part).strip()
    return str(value)


def _message_role(msg_type: str) -> Literal["system", "user", "assistant"]:
    if msg_type in {"model", "assistant", "gemini"}:
        return "assistant"
    if msg_type == "system":
        return "system"
    return "user"


def _convert_item_to_message(item: dict) -> Message | None:
    msg_type = str(item.get("type", "user"))
    content = (
        _flatten_content(item.get("content"))
        or _flatten_content(item.get("message"))
        or _flatten_content(item.get("text"))
    )
    if not content:
        return None

    return Message(
        id=str(item.get("id", "")) or str(uuid.uuid4()),
        role=_message_role(msg_type),
        content=content,
        timestamp=str(item.get("timestamp", "")),
        metadata={"gemini_type": msg_type},
    )


def _extract_items(raw_data: dict | list) -> list[dict]:
    if isinstance(raw_data, list):
        return [item for item in raw_data if isinstance(item, dict)]

    if isinstance(raw_data, dict):
        messages = raw_data.get("messages", [])
        if isinstance(messages, list):
            return [item for item in messages if isinstance(item, dict)]
        history = raw_data.get("history", [])
        if isinstance(history, list):
            return [item for item in history if isinstance(item, dict)]

    return []


def _extract_title(items: list[dict]) -> str:
    for item in items:
        if str(item.get("type", "user")) != "user":
            continue
        text = (
            _flatten_content(item.get("content"))
            or _flatten_content(item.get("message"))
            or _flatten_content(item.get("text"))
        )
        if text:
            return text.replace("\n", " ")[:80]
    return ""


def _extract_timestamp(raw_data: dict | list, items: list[dict]) -> str:
    if isinstance(raw_data, dict):
        for key in ("lastUpdated", "updatedAt", "startTime", "createdAt", "timestamp"):
            value = raw_data.get(key)
            if value:
                return str(value)

    for item in reversed(items):
        ts = item.get("timestamp")
        if ts:
            return str(ts)
    return ""


def _session_id_for_file(path: Path, raw_data: dict | list) -> str:
    if isinstance(raw_data, dict):
        session_id = raw_data.get("sessionId")
        if session_id:
            return str(session_id)
    return path.stem


class GeminiAdapter:
    """Adapter for Gemini CLI sessions."""

    name = "gemini"
    description = "Google Gemini CLI"

    def __init__(self):
        self.base = _get_gemini_base()

    def is_available(self) -> bool:
        return self.base.exists()

    def _session_record(self, path: Path) -> dict | None:
        raw_data = _parse_json(path)
        if raw_data is None:
            return None

        items = _extract_items(raw_data)
        messages = [msg for item in items if (msg := _convert_item_to_message(item))]
        if not messages:
            return None

        reverse_projects = _reverse_projects(self.base)
        project_slug = ""
        cwd = ""
        if "tmp" in path.parts:
            project_slug = path.parent.parent.name
            cwd = reverse_projects.get(project_slug, "")

        return {
            "path": str(path),
            "session_id": _session_id_for_file(path, raw_data),
            "project": project_slug or path.parent.name,
            "cwd": cwd,
            "timestamp": _extract_timestamp(raw_data, items),
            "user_messages": sum(1 for msg in messages if msg.role == "user"),
            "total_messages": len(messages),
            "title": _extract_title(items),
        }

    def list_sessions(self) -> list[dict]:
        sessions: list[dict] = []
        for path in _find_session_files(self.base):
            record = self._session_record(path)
            if record:
                sessions.append(record)
        sessions.sort(key=lambda s: s.get("timestamp", ""), reverse=True)
        return sessions

    def _resolve_target_path(self, session_path: str | None, session_id: str | None) -> Path:
        if session_path:
            target = Path(session_path)
            if not target.exists():
                raise FileNotFoundError(f"Session file not found: {session_path}")
            return target

        files = _find_session_files(self.base)
        if not files:
            raise RuntimeError("No Gemini sessions found.")

        if not session_id:
            return files[0]

        for path in files:
            raw_data = _parse_json(path)
            if raw_data is None:
                continue
            actual_id = _session_id_for_file(path, raw_data)
            if session_id == actual_id or session_id == path.stem or session_id in path.name:
                return path

        raise FileNotFoundError(f"Session not found: {session_id}")

    def export(self, session_path: str | None = None, session_id: str | None = None) -> UniversalSession:
        """Export a Gemini session to UniversalSession."""
        if not self.is_available():
            raise RuntimeError("Gemini CLI storage not found.")

        target_path = self._resolve_target_path(session_path, session_id)
        raw_data = _parse_json(target_path)
        if raw_data is None:
            raise RuntimeError(f"Cannot parse session file: {target_path}")

        items = _extract_items(raw_data)
        messages = [msg for item in items if (msg := _convert_item_to_message(item))]
        if not messages:
            raise RuntimeError(f"No messages found in session: {target_path}")

        created_at = ""
        updated_at = ""
        if isinstance(raw_data, dict):
            created_at = str(raw_data.get("startTime", "") or raw_data.get("createdAt", ""))
            updated_at = str(raw_data.get("lastUpdated", "") or raw_data.get("updatedAt", ""))
        if not created_at and messages:
            created_at = messages[0].timestamp
        if not updated_at and messages:
            updated_at = messages[-1].timestamp

        session_id_meta = _session_id_for_file(target_path, raw_data)
        reverse_projects = _reverse_projects(self.base)
        project_path = ""
        if "tmp" in target_path.parts:
            project_path = reverse_projects.get(target_path.parent.parent.name, "")

        token_count = sum(len(message.content) for message in messages) // 4

        return UniversalSession(
            id=f"gemini-{session_id_meta[:8]}",
            source="gemini",
            messages=messages,
            metadata=SessionMetadata(
                source_agent="gemini",
                original_session_id=session_id_meta,
                project_path=project_path,
                token_count=token_count,
            ),
            created_at=created_at,
            updated_at=updated_at,
            tags=["gemini"],
        )

    def inject(self, session: UniversalSession, project_path: str | None = None) -> Path:
        """
        Inject a UniversalSession into Gemini's resumable project storage.

        After writing, Gemini can resume it with:
          gemini --resume <sessionId>
        """
        cwd = project_path or session.metadata.project_path or os.getcwd()
        project_slug = _ensure_project_slug(self.base, cwd)
        project_dir = self.base / "tmp" / project_slug
        chats_dir = project_dir / "chats"
        chats_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc)
        new_session_id = str(uuid.uuid4())
        session_file = chats_dir / f"session-{now.strftime('%Y-%m-%dT%H-%M-%S')}-{new_session_id[:8]}.json"

        def timestamp_for(index: int, original: str) -> str:
            if original:
                return original
            return (now + timedelta(milliseconds=index)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        messages = []
        for index, msg in enumerate(session.messages):
            content = msg.content or ""
            if not content:
                continue

            msg_type = "user"
            if msg.role == "assistant":
                msg_type = "gemini"
            elif msg.role == "system":
                content = f"[System] {content}"
            elif msg.role == "tool":
                content = f"[Tool] {content}"

            messages.append({
                "id": msg.id or str(uuid.uuid4()),
                "timestamp": timestamp_for(index, msg.timestamp),
                "type": msg_type,
                "content": [{"text": content}],
            })

        session_data = {
            "sessionId": new_session_id,
            "projectHash": hashlib.sha256(_normalize_cwd(cwd).encode("utf-8")).hexdigest(),
            "startTime": messages[0]["timestamp"] if messages else now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "lastUpdated": messages[-1]["timestamp"] if messages else now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "messages": messages,
        }
        session_file.write_text(json.dumps(session_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        (project_dir / ".project_root").write_text(cwd, encoding="utf-8")

        logs_file = project_dir / "logs.json"
        log_entry = {
            "sessionId": new_session_id,
            "messageId": 0,
            "type": "user",
            "message": f"[Session transferred from {session.metadata.source_agent}]",
            "timestamp": session_data["startTime"],
        }
        existing_logs: list[dict] = []
        if logs_file.exists():
            try:
                raw_logs = json.loads(logs_file.read_text(encoding="utf-8"))
                if isinstance(raw_logs, list):
                    existing_logs = [item for item in raw_logs if isinstance(item, dict)]
            except (json.JSONDecodeError, OSError):
                existing_logs = []
        existing_logs.append(log_entry)
        logs_file.write_text(json.dumps(existing_logs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        return session_file
