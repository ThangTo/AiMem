"""
Codex Adapter - read/write sessions for OpenAI Codex CLI.
Storage: ~/.codex/sessions/{YYYY}/{MM}/{DD}/rollout-{timestamp}-{session_id}.jsonl
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
import json
import os
import re
import uuid

from ..models import UniversalSession, Message, SessionMetadata


def _get_codex_base() -> Path:
    home = Path(os.path.expanduser("~"))
    return home / ".codex"


def _find_all_session_files() -> list[Path]:
    sessions_dir = _get_codex_base() / "sessions"
    if not sessions_dir.exists():
        return []
    files = list(sessions_dir.rglob("rollout-*.jsonl"))
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return files


def _load_session_index() -> dict[str, dict]:
    index_file = _get_codex_base() / "session_index.jsonl"
    if not index_file.exists():
        return {}
    data: dict[str, dict] = {}
    with index_file.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            session_id = entry.get("id")
            if session_id:
                data[session_id] = entry
    return data


def _extract_text_blocks(content: list[dict] | str) -> str:
    if isinstance(content, str):
        return content
    chunks: list[str] = []
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") in ("input_text", "output_text"):
                text = block.get("text", "")
                if text:
                    chunks.append(text)
            elif block.get("type") == "refusal":
                text = block.get("refusal", "")
                if text:
                    chunks.append(f"[Refusal] {text}")
    return "\n".join(chunks).strip()


def _parse_codex_jsonl(file_path: Path) -> tuple[dict, list[dict], str, str]:
    metadata: dict = {}
    cwd = ""
    model = ""
    messages: list[dict] = []

    with file_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = obj.get("type")
            payload = obj.get("payload", {})
            timestamp = obj.get("timestamp", "")

            if msg_type == "session_meta":
                metadata = payload if isinstance(payload, dict) else {}
                cwd = metadata.get("cwd", "")
                provider = metadata.get("model_provider", "")
                model = metadata.get("model", "") or (f"Codex ({provider})" if provider else "")
                continue

            if msg_type != "response_item" or not isinstance(payload, dict):
                continue

            item_type = payload.get("type")
            if item_type == "message":
                role = payload.get("role", "assistant")
                content = _extract_text_blocks(payload.get("content", []))
                if not content:
                    continue
                messages.append({
                    "role": role,
                    "content": content,
                    "timestamp": timestamp,
                })
            elif item_type == "function_call":
                name = payload.get("name", "tool")
                arguments = payload.get("arguments", "")
                messages.append({
                    "role": "assistant",
                    "content": f"[Tool: {name}]\n{arguments}",
                    "timestamp": timestamp,
                })
            elif item_type == "function_call_output":
                output = payload.get("output", "")
                messages.append({
                    "role": "tool",
                    "content": str(output),
                    "timestamp": timestamp,
                })

    return metadata, messages, cwd, model


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


def _thread_name(session: UniversalSession) -> str:
    if session.note:
        return session.note[:120]
    for message in session.messages:
        if message.role == "user" and message.content.strip():
            return message.content.strip().replace("\n", " ")[:120]
    return f"Transferred from {session.metadata.source_agent}"


class CodexAdapter:
    name = "codex"
    description = "OpenAI Codex CLI"

    def __init__(self):
        self.base = _get_codex_base()

    def is_available(self) -> bool:
        return self.base.exists() and (self.base / "sessions").exists()

    def list_sessions(self) -> list[dict]:
        index = _load_session_index()
        sessions = []
        for file_path in _find_all_session_files():
            try:
                metadata, messages, cwd, model = _parse_codex_jsonl(file_path)
            except OSError:
                continue
            if not metadata:
                continue

            session_id = metadata.get("id", file_path.stem)
            title = index.get(session_id, {}).get("thread_name", "")
            if not title:
                for message in messages:
                    if message.get("role") == "user":
                        title = message.get("content", "")[:120].replace("\n", " ")
                        break

            sessions.append({
                "path": str(file_path),
                "session_id": session_id,
                "project": Path(cwd).name,
                "cwd": cwd,
                "timestamp": metadata.get("timestamp", ""),
                "user_messages": sum(1 for message in messages if message.get("role") == "user"),
                "assistant_messages": sum(1 for message in messages if message.get("role") == "assistant"),
                "total_messages": len(messages),
                "title": title,
                "model": model,
                "cli_version": metadata.get("cli_version", ""),
            })
        return sessions

    def export(self, session_path: str | None = None, session_id: str | None = None) -> UniversalSession:
        if not self.is_available():
            raise RuntimeError("Codex CLI is not installed or has no sessions.")

        target_path: Path | None = None
        if session_path:
            target_path = Path(session_path)
        elif session_id:
            for file_path in _find_all_session_files():
                if session_id in file_path.stem:
                    target_path = file_path
                    break
                try:
                    with file_path.open("r", encoding="utf-8", errors="replace") as handle:
                        first_line = next(handle, "")
                except OSError:
                    continue
                if session_id and session_id in first_line:
                    target_path = file_path
                    break
            if target_path is None:
                raise FileNotFoundError(f"Session not found: {session_id}")
        else:
            files = _find_all_session_files()
            if not files:
                raise RuntimeError("No Codex sessions found.")
            target_path = files[0]

        metadata, raw_messages, cwd, model = _parse_codex_jsonl(target_path)
        messages: list[Message] = []
        for raw in raw_messages:
            role_raw = raw.get("role", "user")
            role: Literal["system", "user", "assistant"] = "user"
            if role_raw in ("developer", "system"):
                role = "system"
            elif role_raw in ("assistant", "codex", "tool"):
                role = "assistant"
            messages.append(Message(
                id=str(uuid.uuid4()),
                role=role,
                content=raw.get("content", ""),
                timestamp=raw.get("timestamp", ""),
                metadata={},
            ))

        session_id_meta = metadata.get("id", target_path.stem)
        token_count = sum(len(message.content) for message in messages) // 4
        created_at = metadata.get("timestamp", "")

        return UniversalSession(
            id=f"codex-{session_id_meta[:8]}",
            source="codex",
            messages=messages,
            metadata=SessionMetadata(
                source_agent="codex",
                original_session_id=session_id_meta,
                project_path=cwd,
                model=model or "codex",
                entrypoint=metadata.get("originator", "cli"),
                token_count=token_count,
                version=metadata.get("cli_version", ""),
            ),
            created_at=created_at,
            updated_at=created_at,
            tags=["codex"],
        )

    def inject(self, session: UniversalSession) -> Path:
        if not self.is_available():
            raise RuntimeError("Codex CLI is not installed.")

        now = datetime.now(timezone.utc)
        session_id = str(uuid.uuid4())
        date_dir = self.base / "sessions" / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d")
        date_dir.mkdir(parents=True, exist_ok=True)

        filename = f"rollout-{now.strftime('%Y-%m-%dT%H-%M-%S')}-{session_id}.jsonl"
        session_file = date_dir / filename
        cwd = session.metadata.project_path or os.getcwd()
        base_ts = _format_ts(None, now)
        thread_name = _thread_name(session)
        turn_id = str(uuid.uuid4())
        model_name = session.metadata.model or "gpt-5.4"
        provider = "openai"
        cli_version = session.metadata.version or "0.118.0"

        entries = [{
            "timestamp": base_ts,
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "timestamp": base_ts,
                "cwd": cwd,
                "originator": "codex_cli",
                "cli_version": cli_version,
                "source": "cli",
                "model_provider": provider,
                "model": model_name,
                "base_instructions": {"text": ""},
            },
        }, {
            "timestamp": base_ts,
            "type": "event_msg",
            "payload": {
                "type": "task_started",
                "turn_id": turn_id,
                "started_at": int(now.timestamp()),
                "model_context_window": 258400,
                "collaboration_mode_kind": "default",
            },
        }, {
            "timestamp": base_ts,
            "type": "turn_context",
            "payload": {
                "turn_id": turn_id,
                "cwd": cwd,
                "current_date": now.astimezone().strftime("%Y-%m-%d"),
                "timezone": str(now.astimezone().tzinfo or "UTC"),
                "approval_policy": "never",
                "sandbox_policy": {"type": "danger-full-access"},
                "model": model_name,
                "personality": "friendly",
                "collaboration_mode": {"mode": "default", "settings": {}},
                "realtime_active": False,
                "effort": "high",
                "summary": "none",
                "truncation_policy": {"mode": "tokens", "limit": 10000},
            },
        }, {
            "timestamp": base_ts,
            "type": "event_msg",
            "payload": {
                "type": "thread_name_updated",
                "thread_id": session_id,
                "thread_name": thread_name,
            },
        }]

        sequence = 1
        for msg in session.messages:
            if msg.role not in ("system", "user", "assistant"):
                continue
            ts = _format_ts(msg.timestamp, now + timedelta(milliseconds=sequence))
            sequence += 1
            if msg.role == "assistant":
                payload = {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": msg.content}],
                }
            elif msg.role == "system":
                payload = {
                    "type": "message",
                    "role": "developer",
                    "content": [{"type": "input_text", "text": msg.content}],
                }
            else:
                payload = {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": msg.content}],
                }
            entries.append({
                "timestamp": ts,
                "type": "response_item",
                "payload": payload,
            })

        with session_file.open("w", encoding="utf-8") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

        index_file = self.base / "session_index.jsonl"
        with index_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "id": session_id,
                "thread_name": thread_name,
                "updated_at": _format_ts(None, now),
            }, ensure_ascii=False) + "\n")

        return session_file


def extract_codex_session_id(path: Path) -> str:
    match = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$", path.stem)
    return match.group(1) if match else path.stem
