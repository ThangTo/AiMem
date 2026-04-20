"""
Codex Adapter - Đọc session từ OpenAI Codex CLI.
Storage: ~/.codex/sessions/{year}/{month}/{day}/rollout-{timestamp}-{session_id}.jsonl
Format: Custom JSONL với event-based structure (session_meta, event_msg, response_item, turn_context).
Model: OpenAI Codex sử dụng GPT-5.
"""

from pathlib import Path
from datetime import datetime, timezone
from typing import Literal
import json
import uuid

from ..models import UniversalSession, Message, ContextItem, SessionMetadata


# ─────────────────────────────────────────────────────────────
# Path Discovery
# ─────────────────────────────────────────────────────────────

def _get_codex_base() -> Path:
    """Tìm thư mục gốc của Codex CLI."""
    import os
    home = Path(os.path.expanduser("~"))
    return home / ".codex"


def _find_sessions_dir() -> Path:
    """Tìm thư mục chứa sessions."""
    base = _get_codex_base()
    sessions_dir = base / "sessions"
    if sessions_dir.exists():
        return sessions_dir
    return base


def _find_all_session_files() -> list[Path]:
    """Tìm tất cả Codex session files."""
    sessions_dir = _find_sessions_dir()
    if not sessions_dir.exists():
        return []

    files = []
    for jsonl_file in sessions_dir.rglob("rollout-*.jsonl"):
        files.append(jsonl_file)

    # Sort by mtime newest first
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def _parse_message_from_payload(payload: dict) -> str:
    """Extract readable text từ message payload."""
    content = payload.get("content", [])

    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "output_text":
                    text = block.get("text", "")
                    parts.append(text)
                elif block.get("type") == "input_text":
                    text = block.get("text", "")
                    parts.append(text)
                elif block.get("type") == "refusal":
                    text = block.get("refusal", "")
                    parts.append(f"[Refusal] {text}")
        return "\n".join(parts)

    elif isinstance(content, str):
        return content

    return ""


# ─────────────────────────────────────────────────────────────
# Parse Codex JSONL
# ─────────────────────────────────────────────────────────────

def _parse_codex_jsonl(file_path: Path) -> tuple[dict, list[dict], str]:
    """
    Parse Codex session file.
    Returns: (metadata, messages, cwd)
    """
    messages = []
    metadata = {}
    cwd = ""
    model = ""

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = obj.get("type", "")
                payload = obj.get("payload", {})
                timestamp = obj.get("timestamp", "")

                if msg_type == "session_meta":
                    metadata = {
                        "id": payload.get("id", ""),
                        "timestamp": payload.get("timestamp", ""),
                        "cwd": payload.get("cwd", ""),
                        "originator": payload.get("originator", ""),
                        "cli_version": payload.get("cli_version", ""),
                        "source": payload.get("source", ""),
                        "model_provider": payload.get("model_provider", ""),
                        "base_instructions": payload.get("base_instructions", {}).get("text", "")[:200] if isinstance(payload.get("base_instructions"), dict) else str(payload.get("base_instructions", ""))[:200],
                    }
                    cwd = metadata.get("cwd", "")
                    model = f"Codex ({metadata.get('model_provider', 'unknown')})"

                elif msg_type == "response_item":
                    item_type = payload.get("type", "")
                    if item_type == "message":
                        role = payload.get("role", "assistant")
                        content = _parse_message_from_payload(payload)
                        if content:
                            messages.append({
                                "role": role,
                                "content": content,
                                "timestamp": timestamp,
                            })
                    elif item_type == "function_call":
                        name = payload.get("name", "unknown")
                        args = payload.get("arguments", "")
                        if isinstance(args, dict):
                            args = json.dumps(args)
                        messages.append({
                            "role": "assistant",
                            "content": f"[Tool: {name}]\n{args[:200]}",
                            "timestamp": timestamp,
                        })
                    elif item_type == "function_call_output":
                        output = payload.get("output", "")
                        messages.append({
                            "role": "tool",
                            "content": str(output)[:500],
                            "timestamp": timestamp,
                        })

                elif msg_type == "turn_context":
                    # turn_context contains additional context
                    context_type = payload.get("type", "")
                    if context_type == "user_input":
                        user_text = payload.get("text", "")
                        if user_text:
                            messages.append({
                                "role": "user",
                                "content": user_text,
                                "timestamp": timestamp,
                            })

    except (OSError, IOError):
        pass

    return metadata, messages, cwd, model


# ─────────────────────────────────────────────────────────────
# Main Adapter Class
# ─────────────────────────────────────────────────────────────

class CodexAdapter:
    """Adapter để đọc session từ OpenAI Codex CLI."""

    name = "codex"
    description = "OpenAI Codex CLI"

    def __init__(self):
        self.base = _get_codex_base()

    def is_available(self) -> bool:
        """Kiểm tra Codex CLI có được cài đặt không."""
        return self.base.exists() and (self.base / "sessions").exists()

    def list_sessions(self) -> list[dict]:
        """List all available Codex sessions."""
        sessions = []
        files = _find_all_session_files()

        for f in files:
            try:
                metadata, messages, cwd, model = _parse_codex_jsonl(f)
                if not metadata:
                    continue

                session_id = metadata.get("id", f.stem) or f.stem
                timestamp = metadata.get("timestamp", "")
                if isinstance(timestamp, (int, float)):
                    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                    timestamp = dt.isoformat()

                # Extract title from first user message
                title = ""
                for msg in messages:
                    if msg.get("role") == "user":
                        title = msg.get("content", "")[:80].replace("\n", " ")
                        break

                sessions.append({
                    "path": str(f),
                    "session_id": session_id,
                    "project": f.parent.parent.name if len(f.parts) >= 3 else "",
                    "cwd": cwd,
                    "timestamp": timestamp,
                    "user_messages": sum(1 for m in messages if m.get("role") == "user"),
                    "total_messages": len(messages),
                    "title": title,
                    "model": model,
                    "cli_version": metadata.get("cli_version", ""),
                })
            except Exception:
                continue

        return sessions

    def export(self, session_path: str | None = None, session_id: str | None = None) -> UniversalSession:
        """
        Export a Codex session to UniversalSession format.
        """
        if not self.is_available():
            raise RuntimeError("Codex CLI is not installed or has no sessions.")

        target_path = None

        if session_path:
            target_path = Path(session_path)
        elif session_id:
            # Search by session ID in filename
            files = _find_all_session_files()
            for f in files:
                if session_id in f.stem:
                    target_path = f
                    break
            if not target_path:
                raise FileNotFoundError(f"Session not found: {session_id}")
        else:
            # Most recent
            files = _find_all_session_files()
            if not files:
                raise RuntimeError("No Codex sessions found.")
            target_path = files[0]

        metadata, raw_messages, cwd, model = _parse_codex_jsonl(target_path)

        # Convert to Message objects
        messages = []
        for raw in raw_messages:
            role: Literal["system", "user", "assistant"] = "user"
            role_raw = raw.get("role", "user")
            if role_raw in ("developer", "system"):
                role = "system"
            elif role_raw in ("assistant", "codex"):
                role = "assistant"
            elif role_raw == "tool":
                role = "assistant"  # Map tool to assistant in UniversalSession

            messages.append(Message(
                id=str(uuid.uuid4()),
                role=role,
                content=raw.get("content", ""),
                timestamp=raw.get("timestamp", ""),
                metadata={}
            ))

        session_id_meta = metadata.get("id", target_path.stem or "unknown")
        token_count = sum(len(m.content) for m in messages) // 4

        # Parse timestamp
        created_at = metadata.get("timestamp", "")
        if created_at and isinstance(created_at, str):
            try:
                dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                created_at = dt.isoformat()
            except (ValueError, AttributeError):
                created_at = ""

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
        """
        Inject a UniversalSession vào Codex CLI storage.
        Returns path to the new session file.
        """
        from datetime import datetime, timezone

        sessions_dir = _find_sessions_dir()
        ts = datetime.now(timezone.utc)

        date_dir = sessions_dir / ts.strftime("%Y") / ts.strftime("%m") / ts.strftime("%d")
        if not date_dir.exists():
            date_dir.mkdir(parents=True, exist_ok=True)

        new_session_id = session.id.replace("claude-", "").replace("gemini-", "").replace("qwen-", "").replace("codex-", "")[:16]
        session_file = date_dir / f"rollout-{ts.strftime('%Y%m%d%H%M%S')}-{new_session_id}.jsonl"

        base_ts = ts.isoformat()

        with open(session_file, "w", encoding="utf-8") as f:
            meta_entry = {
                "type": "session_meta",
                "timestamp": base_ts,
                "payload": {
                    "id": new_session_id,
                    "timestamp": base_ts,
                    "cwd": session.metadata.project_path or "",
                    "originator": "aimem-transfer",
                    "cli_version": "1.0.0",
                    "source": session.metadata.source_agent,
                    "model_provider": session.metadata.model or "unknown",
                }
            }
            f.write(json.dumps(meta_entry) + "\n")

            for msg in session.messages:
                ts_str = msg.timestamp or base_ts
                if msg.role == "user":
                    entry = {
                        "type": "turn_context",
                        "timestamp": ts_str,
                        "payload": {
                            "type": "user_input",
                            "text": msg.content,
                        }
                    }
                elif msg.role == "assistant":
                    entry = {
                        "type": "response_item",
                        "timestamp": ts_str,
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": msg.content}],
                        }
                    }
                else:
                    continue
                f.write(json.dumps(entry) + "\n")

        return session_file
