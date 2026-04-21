"""
Qwen Adapter - read/write sessions for Qwen Code CLI.
Storage: ~/.qwen/projects/{project-slug}/chats/{session_id}.jsonl
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


def _get_qwen_base() -> Path:
    home = Path(os.path.expanduser("~"))
    return home / ".qwen"


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


def _project_slug(cwd: str) -> str:
    path = PureWindowsPath(cwd)
    if path.drive:
        drive = path.drive.rstrip(":").lower()
        parts = [part.lower() for part in path.parts[1:] if part not in ("\\", "/")]
        return f"{drive}--{'-'.join(parts)}" if parts else drive
    cleaned = [part.lower() for part in PureWindowsPath(cwd).parts if part not in ("\\", "/")]
    return "-".join(cleaned) or "default"


def _find_chat_files() -> list[Path]:
    chats_root = _get_qwen_base() / "projects"
    if not chats_root.exists():
        return []
    files = list(chats_root.glob("*/chats/*.jsonl"))
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


def _extract_text_parts(parts: list[dict]) -> tuple[str, list[dict]]:
    chunks: list[str] = []
    tool_calls: list[dict] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        text = part.get("text", "")
        if text:
            if part.get("thought"):
                chunks.append(f"[Thinking: {text}]")
            else:
                chunks.append(text)
        function_call = part.get("functionCall")
        if isinstance(function_call, dict):
            tool_calls.append(function_call)
            name = function_call.get("name", "tool")
            chunks.append(f"[Tool: {name}]")
    return "\n".join(chunk for chunk in chunks if chunk).strip(), tool_calls


def _extract_content(raw: dict) -> tuple[str, list[dict]]:
    message = raw.get("message", {})
    if not isinstance(message, dict):
        return "", []
    parts = message.get("parts", [])
    if not isinstance(parts, list):
        return "", []
    return _extract_text_parts(parts)


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


class QwenAdapter:
    name = "qwen"
    description = "Qwen / Qwen-Coder CLI"

    def __init__(self):
        self.base = _get_qwen_base()

    def is_available(self) -> bool:
        return self.base.exists() and (self.base / "projects").exists()

    def list_sessions(self) -> list[dict]:
        sessions = []
        for chat_file in _find_chat_files():
            raw_messages = _parse_jsonl(chat_file)
            if not raw_messages:
                continue

            first = raw_messages[0]
            last = raw_messages[-1]
            session_id = first.get("sessionId", chat_file.stem)
            cwd = first.get("cwd", "")
            title = ""
            user_count = 0
            assistant_count = 0

            for raw in raw_messages:
                raw_type = raw.get("type")
                if raw_type == "user":
                    user_count += 1
                    if not title:
                        title, _ = _extract_content(raw)
                elif raw_type == "assistant":
                    assistant_count += 1

            sessions.append({
                "path": str(chat_file),
                "session_id": session_id,
                "project": chat_file.parent.parent.name,
                "cwd": cwd,
                "timestamp": last.get("timestamp", first.get("timestamp", "")),
                "user_messages": user_count,
                "assistant_messages": assistant_count,
                "total_messages": user_count + assistant_count,
                "title": (title or session_id)[:120].replace("\n", " "),
            })

        return sessions

    def export(self, session_path: str | None = None, session_id: str | None = None) -> UniversalSession:
        if not self.is_available():
            raise RuntimeError("Qwen CLI is not installed.")

        target_path: Path | None = None
        if session_path:
            target_path = Path(session_path)
        elif session_id:
            for chat_file in _find_chat_files():
                if chat_file.stem == session_id:
                    target_path = chat_file
                    break
                raw_messages = _parse_jsonl(chat_file)
                if raw_messages and raw_messages[0].get("sessionId", "").startswith(session_id):
                    target_path = chat_file
                    break
            if target_path is None:
                raise FileNotFoundError(f"Session not found: {session_id}")
        else:
            files = _find_chat_files()
            if not files:
                raise RuntimeError("No Qwen sessions found.")
            target_path = files[0]

        raw_messages = _parse_jsonl(target_path)
        if not raw_messages:
            raise RuntimeError(f"Session file is empty: {target_path}")

        messages: list[Message] = []
        model = ""
        for raw in raw_messages:
            raw_type = raw.get("type")
            if raw_type not in ("user", "assistant"):
                continue
            content, tool_calls = _extract_content(raw)
            if not content and not tool_calls:
                continue
            role: Literal["system", "user", "assistant"] = "user" if raw_type == "user" else "assistant"
            if role == "assistant" and not model:
                model = raw.get("model", "")
            messages.append(Message(
                id=raw.get("uuid", str(uuid.uuid4())),
                role=role,
                content=content,
                timestamp=raw.get("timestamp", ""),
                tool_calls=tool_calls,
                metadata={
                    "parent_uuid": raw.get("parentUuid"),
                    "cwd": raw.get("cwd", ""),
                    "git_branch": raw.get("gitBranch", ""),
                    "version": raw.get("version", ""),
                },
            ))

        first = raw_messages[0]
        last = raw_messages[-1]
        session_id_meta = first.get("sessionId", target_path.stem)
        cwd = first.get("cwd", "")
        version = first.get("version", "")
        token_count = sum(len(message.content) for message in messages) // 4

        return UniversalSession(
            id=f"qwen-{session_id_meta[:8]}",
            source="qwen",
            messages=messages,
            metadata=SessionMetadata(
                source_agent="qwen",
                original_session_id=session_id_meta,
                project_path=cwd,
                model=model,
                entrypoint="cli",
                token_count=token_count,
                version=version,
            ),
            created_at=first.get("timestamp", ""),
            updated_at=last.get("timestamp", ""),
            tags=["qwen"],
        )

    def inject(self, session: UniversalSession) -> Path:
        if not self.is_available():
            raise RuntimeError("Qwen CLI is not installed.")

        cwd = session.metadata.project_path or os.getcwd()
        chats_dir = self.base / "projects" / _project_slug(cwd) / "chats"
        chats_dir.mkdir(parents=True, exist_ok=True)

        new_session_id = str(uuid.uuid4())
        chat_file = chats_dir / f"{new_session_id}.jsonl"
        branch = _detect_git_branch(cwd)
        version = session.metadata.version or "0.14.5"
        model = session.metadata.model or "coder-model"
        parent_uuid: str | None = None
        base_dt = datetime.now(timezone.utc)
        sequence = 0

        with chat_file.open("w", encoding="utf-8") as handle:
            for msg in session.messages:
                if msg.role not in ("user", "assistant"):
                    continue
                timestamp = _format_ts(msg.timestamp, base_dt + timedelta(milliseconds=sequence))
                sequence += 1
                message_id = msg.id or str(uuid.uuid4())
                entry = {
                    "uuid": message_id,
                    "parentUuid": parent_uuid,
                    "sessionId": new_session_id,
                    "timestamp": timestamp,
                    "type": "user" if msg.role == "user" else "assistant",
                    "cwd": cwd,
                    "version": version,
                    "gitBranch": branch,
                    "message": {
                        "role": "user" if msg.role == "user" else "model",
                        "parts": [{"text": msg.content}],
                    },
                }
                if msg.role == "assistant":
                    entry["model"] = model

                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
                parent_uuid = message_id

        return chat_file
