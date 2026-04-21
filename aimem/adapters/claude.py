"""
Claude Adapter - read/write sessions for Claude Code.
Storage: ~/.claude/projects/{project}/{session_id}.jsonl
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path, PureWindowsPath
from typing import Literal
import json
import os
import subprocess
import uuid

from ..models import UniversalSession, Message, SessionMetadata


def _get_claude_base() -> Path:
    home = Path(os.path.expanduser("~"))
    return home / ".claude"


def _project_dir_name(cwd: str) -> str:
    path = PureWindowsPath(cwd)
    if path.drive:
        drive = path.drive.rstrip(":").lower()
        parts = [part for part in path.parts[1:] if part not in ("\\", "/")]
        return f"{drive}--{'-'.join(parts)}" if parts else drive
    cleaned = [part for part in path.parts if part not in ("\\", "/")]
    return "-".join(cleaned) or "default"


def _get_project_sessions() -> list[Path]:
    projects_dir = _get_claude_base() / "projects"
    if not projects_dir.exists():
        return []
    files = []
    for jsonl_file in projects_dir.rglob("*.jsonl"):
        if jsonl_file.name in {"costs.jsonl", "metrics.jsonl"}:
            continue
        files.append(jsonl_file)
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return files


def _parse_jsonl(file_path: Path) -> list[dict]:
    messages: list[dict] = []
    try:
        with file_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return messages


def _extract_message_content(msg: dict) -> str:
    msg_type = msg.get("type")
    if msg_type == "assistant":
        message = msg.get("message", {})
        content = message.get("content", []) if isinstance(message, dict) else []
        if isinstance(content, str):
            return content.strip()
        chunks: list[str] = []
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text = block.get("text", "")
                    if text:
                        chunks.append(text)
                elif block.get("type") == "thinking":
                    thinking = block.get("thinking", "")
                    if thinking:
                        chunks.append(f"[Thinking: {thinking}]")
                elif block.get("type") == "tool_use":
                    name = block.get("name", "tool")
                    chunks.append(f"[Tool: {name}]")
        return "\n".join(chunks).strip()

    if msg_type == "user":
        message = msg.get("message", {})
        content = message.get("content", "") if isinstance(message, dict) else message
        if isinstance(content, str):
            return content.strip()
        chunks: list[str] = []
        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text = block.get("text", "")
                    if text:
                        chunks.append(text)
                elif block.get("type") == "tool_result":
                    text = block.get("content", "")
                    if text:
                        chunks.append(str(text))
        return "\n".join(chunks).strip()

    if msg_type == "system":
        subtype = msg.get("subtype", "")
        if subtype == "api_error":
            error = msg.get("error", {}).get("error", {}).get("message", "")
            return f"[API Error] {error}".strip()
    return ""


def _detect_defaults(cwd: str) -> dict[str, str]:
    project_dir = _get_claude_base() / "projects" / _project_dir_name(cwd)
    candidate_files = []
    if project_dir.exists():
        candidate_files.extend(sorted(project_dir.glob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True))
    candidate_files.extend(_get_project_sessions())

    for file_path in candidate_files:
        for raw in _parse_jsonl(file_path):
            if raw.get("type") not in {"user", "assistant"}:
                continue
            return {
                "version": raw.get("version", ""),
                "git_branch": raw.get("gitBranch", ""),
                "entrypoint": raw.get("entrypoint", "cli"),
                "user_type": raw.get("userType", "external"),
                "model": raw.get("message", {}).get("model", "") if isinstance(raw.get("message"), dict) else "",
            }
    return {
        "version": "",
        "git_branch": "",
        "entrypoint": "cli",
        "user_type": "external",
        "model": "",
    }


def _detect_git_branch(cwd: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "branch", "--show-current"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def _format_ts(ts: str | None, fallback: datetime) -> str:
    if ts:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            dt = fallback
    else:
        dt = fallback
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class ClaudeAdapter:
    name = "claude"
    description = "Claude Code (CLI & VS Code)"

    def __init__(self):
        self.base = _get_claude_base()

    def is_available(self) -> bool:
        return self.base.exists() and (self.base / "projects").exists()

    def list_sessions(self) -> list[dict]:
        sessions = []
        for jsonl_path in _get_project_sessions():
            raw_messages = _parse_jsonl(jsonl_path)
            if not raw_messages:
                continue
            title = ""
            user_msgs = 0
            assistant_msgs = 0
            for raw in raw_messages:
                if raw.get("type") == "user":
                    user_msgs += 1
                    if not title:
                        title = _extract_message_content(raw)
                elif raw.get("type") == "assistant":
                    assistant_msgs += 1

            first = raw_messages[0]
            timestamp = ""
            for raw in reversed(raw_messages):
                ts = raw.get("timestamp", "")
                if ts:
                    timestamp = ts
                    break

            sessions.append({
                "path": str(jsonl_path),
                "session_id": jsonl_path.stem,
                "project": jsonl_path.parent.name,
                "cwd": first.get("cwd", ""),
                "timestamp": timestamp,
                "user_messages": user_msgs,
                "assistant_messages": assistant_msgs,
                "total_messages": user_msgs + assistant_msgs,
                "title": title[:120].replace("\n", " "),
            })
        return sessions

    def export(self, session_path: str | None = None, session_id: str | None = None) -> UniversalSession:
        if not self.is_available():
            raise RuntimeError("Claude Code is not installed or has no sessions.")

        if session_path:
            jsonl_path = Path(session_path)
        elif session_id:
            matches = [path for path in _get_project_sessions() if path.stem == session_id or path.stem.startswith(session_id)]
            if not matches:
                raise FileNotFoundError(f"Session not found: {session_id}")
            jsonl_path = matches[0]
        else:
            sessions = _get_project_sessions()
            if not sessions:
                raise RuntimeError("No Claude sessions found.")
            jsonl_path = sessions[0]

        raw_messages = _parse_jsonl(jsonl_path)
        if not raw_messages:
            raise RuntimeError(f"Session file is empty or unreadable: {jsonl_path}")

        messages: list[Message] = []
        for raw in raw_messages:
            raw_type = raw.get("type")
            if raw_type not in {"system", "user", "assistant"}:
                continue
            content = _extract_message_content(raw)
            if not content:
                continue
            role: Literal["system", "user", "assistant"] = "user"
            if raw_type == "assistant":
                role = "assistant"
            elif raw_type == "system":
                role = "system"
            messages.append(Message(
                id=raw.get("uuid", str(uuid.uuid4())),
                role=role,
                content=content,
                timestamp=raw.get("timestamp", ""),
                metadata={
                    "parent_uuid": raw.get("parentUuid"),
                    "entrypoint": raw.get("entrypoint", ""),
                    "slug": raw.get("slug", ""),
                },
            ))

        first = raw_messages[0]
        model = ""
        for raw in raw_messages:
            if raw.get("type") == "assistant":
                message = raw.get("message", {})
                if isinstance(message, dict):
                    model = message.get("model", "")
                if model:
                    break

        token_count = sum(len(message.content) for message in messages) // 4
        created_at = next((raw.get("timestamp", "") for raw in raw_messages if raw.get("timestamp")), "")
        updated_at = next((raw.get("timestamp", "") for raw in reversed(raw_messages) if raw.get("timestamp")), "")

        return UniversalSession(
            id=f"claude-{first.get('sessionId', jsonl_path.stem)[:8]}",
            source="claude",
            messages=messages,
            metadata=SessionMetadata(
                source_agent="claude",
                original_session_id=first.get("sessionId", jsonl_path.stem),
                project_path=first.get("cwd", ""),
                model=model,
                entrypoint=first.get("entrypoint", ""),
                token_count=token_count,
                version=first.get("version", ""),
            ),
            created_at=created_at,
            updated_at=updated_at,
            tags=["claude"],
        )

    def inject(self, session: UniversalSession, project_path: str | None = None) -> Path:
        if not self.is_available():
            raise RuntimeError("Claude Code is not installed.")

        cwd = project_path or session.metadata.project_path or os.getcwd()
        target_dir = self.base / "projects" / _project_dir_name(cwd)
        target_dir.mkdir(parents=True, exist_ok=True)

        defaults = _detect_defaults(cwd)
        version = session.metadata.version or defaults["version"]
        git_branch = defaults["git_branch"] or _detect_git_branch(cwd)
        entrypoint = defaults["entrypoint"] or "cli"
        user_type = defaults["user_type"] or "external"
        assistant_model = session.metadata.model or defaults["model"]

        new_session_id = str(uuid.uuid4())
        session_file = target_dir / f"{new_session_id}.jsonl"
        base_time = datetime.now(timezone.utc)
        first_uuid: str | None = None
        parent_uuid: str | None = None
        lines: list[dict] = []
        index = 0

        for msg in session.messages:
            if msg.role not in {"user", "assistant"}:
                continue
            message_uuid = msg.id or str(uuid.uuid4())
            if first_uuid is None:
                first_uuid = message_uuid
            timestamp = _format_ts(msg.timestamp, base_time + timedelta(milliseconds=index))
            index += 1

            if msg.role == "user":
                message_payload: dict = {
                    "role": "user",
                    "content": msg.content,
                }
            else:
                message_payload = {
                    "id": f"msg_{uuid.uuid4().hex[:24]}",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "text", "text": msg.content}],
                    "model": assistant_model,
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                    "usage": {
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                    "service_tier": "standard",
                }

            lines.append({
                "parentUuid": parent_uuid,
                "isSidechain": False,
                "type": "user" if msg.role == "user" else "assistant",
                "message": message_payload,
                "uuid": message_uuid,
                "timestamp": timestamp,
                "userType": user_type,
                "entrypoint": entrypoint,
                "cwd": cwd,
                "sessionId": new_session_id,
                "version": version,
                "gitBranch": git_branch,
            })
            parent_uuid = message_uuid

        if not lines:
            raise RuntimeError("Session has no user/assistant messages to inject.")

        snapshot = {
            "type": "file-history-snapshot",
            "messageId": first_uuid,
            "snapshot": {
                "messageId": first_uuid,
                "trackedFileBackups": {},
                "timestamp": lines[0]["timestamp"],
            },
            "isSnapshotUpdate": False,
        }

        with session_file.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
            for line in lines:
                handle.write(json.dumps(line, ensure_ascii=False) + "\n")

        history_file = self.base / "history.jsonl"
        with history_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "display": session.note or f"Transferred from {session.metadata.source_agent}",
                "pastedContents": {},
                "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
                "project": cwd,
                "sessionId": new_session_id,
            }, ensure_ascii=False) + "\n")

        return session_file
