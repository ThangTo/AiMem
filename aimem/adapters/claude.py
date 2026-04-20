"""
Claude Adapter - Đọc session từ Claude Code (Claude CLI / VS Code).
Storage: ~/.claude/projects/{project}/{session_id}.jsonl (JSON Lines)
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

def _get_claude_base() -> Path:
    """Tìm thư mục gốc của Claude Code config."""
    import os
    home = Path(os.path.expanduser("~"))
    return home / ".claude"


def _get_project_sessions() -> list[Path]:
    """Tìm tất cả session files (JSONL) trong projects directory."""
    base = _get_claude_base()
    projects_dir = base / "projects"

    if not projects_dir.exists():
        return []

    sessions = []
    for jsonl_file in projects_dir.rglob("*.jsonl"):
        # Filter out non-session files (metrics, etc.)
        if jsonl_file.name in ("costs.jsonl", "metrics.jsonl"):
            continue
        sessions.append(jsonl_file)

    return sorted(sessions, key=lambda p: p.stat().st_mtime, reverse=True)


def _parse_jsonl(file_path: Path) -> list[dict]:
    """Parse JSONL file thành list of dicts."""
    if not file_path.exists():
        return []

    messages = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except (OSError, IOError):
        pass

    return messages


def _extract_message_content(msg: dict) -> str:
    """Trích xuất text content từ message dict."""
    content = ""

    # System messages
    if msg.get("type") == "system":
        subtype = msg.get("subtype", "")
        if subtype == "api_error":
            error = msg.get("error", {})
            error_msg = error.get("error", {}).get("message", "")
            content = f"[API Error] {error_msg}"
        else:
            content = f"[System: {subtype}]"
        return content

    # Assistant messages
    if msg.get("type") == "assistant":
        message_data = msg.get("message", {})
        content_list = message_data.get("content", [])

        if isinstance(content_list, list):
            for block in content_list:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        content += block.get("text", "")
                    elif block.get("type") == "thinking":
                        # Skip long thinking blocks
                        thinking = block.get("thinking", "")[:200]
                        if thinking:
                            content += f"[Thinking: {thinking}...]\n"
                    elif block.get("type") == "tool_use":
                        tool_name = block.get("name", "unknown")
                        content += f"[Tool: {tool_name}]\n"
        elif isinstance(content_list, str):
            content = content_list

        return content.strip()

    # User messages
    if msg.get("type") == "user":
        message_data = msg.get("message", {})
        content_list = message_data.get("content", [])

        if isinstance(content_list, list):
            for block in content_list:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        content += block.get("text", "")
                    elif block.get("type") == "tool_result":
                        tool_id = block.get("tool_use_id", "")
                        result = block.get("content", "")
                        is_error = block.get("is_error", False)
                        prefix = "[Error] " if is_error else "[Tool Result] "
                        content += f"{prefix}{result[:500]}\n"
        elif isinstance(content_list, str):
            content = content_list

        # Also check direct 'message' field
        if not content and msg.get("message"):
            if isinstance(msg["message"], str):
                content = msg["message"]
            elif isinstance(msg["message"], dict):
                content = msg["message"].get("content", "")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            content += block.get("text", "")

        return content.strip()

    return content


# ─────────────────────────────────────────────────────────────
# Main Adapter Class
# ─────────────────────────────────────────────────────────────

class ClaudeAdapter:
    """Adapter để đọc session từ Claude Code."""

    name = "claude"
    description = "Claude Code (CLI & VS Code)"

    def __init__(self):
        self.base = _get_claude_base()

    def is_available(self) -> bool:
        """Kiểm tra Claude Code có được cài đặt không."""
        return self.base.exists() and (self.base / "projects").exists()

    def list_sessions(self) -> list[dict]:
        """
        List all available Claude sessions.
        Returns list of {path, session_id, project, cwd, timestamp, message_count}
        """
        sessions = []
        project_sessions = _get_project_sessions()

        for jsonl_path in project_sessions:
            msgs = _parse_jsonl(jsonl_path)

            # Get metadata from first message
            first = msgs[0] if msgs else {}
            session_id = jsonl_path.stem  # filename without .jsonl

            # Find timestamp
            timestamp = ""
            for m in reversed(msgs):
                ts = m.get("timestamp", "")
                if ts:
                    timestamp = ts
                    break

            # Find CWD
            cwd = first.get("cwd", str(jsonl_path.parent))

            # Count messages
            user_msgs = sum(1 for m in msgs if m.get("type") == "user")
            asst_msgs = sum(1 for m in msgs if m.get("type") == "assistant")

            # Extract first user message as title
            title = ""
            for m in msgs:
                if m.get("type") == "user":
                    content = _extract_message_content(m)
                    if content:
                        title = content[:80].replace("\n", " ")
                        break

            sessions.append({
                "path": str(jsonl_path),
                "session_id": session_id,
                "project": jsonl_path.parent.name,
                "cwd": cwd,
                "timestamp": timestamp,
                "user_messages": user_msgs,
                "assistant_messages": asst_msgs,
                "total_messages": len(msgs),
                "title": title,
            })

        return sessions

    def export(self, session_path: str | None = None, session_id: str | None = None) -> UniversalSession:
        """
        Export a Claude session to UniversalSession format.

        Args:
            session_path: Full path to JSONL file
            session_id: Session ID (will search in projects/)
        """
        if not self.is_available():
            raise RuntimeError("Claude Code is not installed or has no sessions.")

        # Resolve path
        if session_path:
            jsonl_path = Path(session_path)
        elif session_id:
            # Search in projects - supports partial match
            projects_dir = self.base / "projects"
            found = []

            # Exact match first
            exact = list(projects_dir.rglob(f"{session_id}.jsonl"))
            found.extend(exact)

            # Partial match (starts with session_id)
            if not found:
                for jsonl_file in projects_dir.rglob("*.jsonl"):
                    if jsonl_file.stem.startswith(session_id) or session_id in jsonl_file.stem:
                        found.append(jsonl_file)

            if not found:
                raise FileNotFoundError(f"Session not found: {session_id}")
            jsonl_path = found[0]
        else:
            # Get most recent session
            sessions = _get_project_sessions()
            if not sessions:
                raise RuntimeError("No Claude sessions found.")
            jsonl_path = sessions[0]

        # Parse
        raw_msgs = _parse_jsonl(jsonl_path)
        if not raw_msgs:
            raise RuntimeError(f"Session file is empty or unreadable: {jsonl_path}")

        # Convert to Message objects
        messages = []
        for raw in raw_msgs:
            content = _extract_message_content(raw)
            if not content:
                continue  # Skip empty messages (system events without content)

            msg_type = raw.get("type", "user")
            role: Literal["system", "user", "assistant"] = "user"
            if msg_type == "assistant":
                role = "assistant"
            elif msg_type == "system":
                role = "system"

            messages.append(Message(
                id=raw.get("uuid", str(uuid.uuid4())),
                role=role,
                content=content,
                timestamp=raw.get("timestamp", ""),
                tool_calls=[],
                metadata={
                    "parent_uuid": raw.get("parentUuid"),
                    "entrypoint": raw.get("entrypoint", ""),
                    "slug": raw.get("slug", ""),
                }
            ))

        # Extract metadata from first message
        first = raw_msgs[0]
        session_id_meta = first.get("sessionId", jsonl_path.stem)
        cwd = first.get("cwd", "")
        version = first.get("version", "")

        # Find model from assistant messages
        model = ""
        for raw in raw_msgs:
            if raw.get("type") == "assistant":
                msg_data = raw.get("message", {})
                if isinstance(msg_data, dict):
                    model = msg_data.get("model", "")
                    if model:
                        break

        # Count tokens (rough)
        total_text = "\n".join(m.content for m in messages)
        token_count = len(total_text) // 4

        # Build metadata
        metadata = SessionMetadata(
            source_agent="claude",
            original_session_id=session_id_meta,
            project_path=cwd,
            model=model,
            entrypoint=first.get("entrypoint", ""),
            token_count=token_count,
            version=version,
        )

        # Determine creation time
        created_at = ""
        for m in raw_msgs:
            ts = m.get("timestamp", "")
            if ts:
                created_at = ts
                break

        updated_at = ""
        for m in reversed(raw_msgs):
            ts = m.get("timestamp", "")
            if ts:
                updated_at = ts
                break

        return UniversalSession(
            id=f"claude-{session_id_meta[:8]}",
            source="claude",
            messages=messages,
            metadata=metadata,
            created_at=created_at,
            updated_at=updated_at,
            tags=["claude"],
        )

    def inject(self, session: UniversalSession, project_path: str | None = None) -> Path:
        """
        Inject a UniversalSession vào Claude Code storage.
        Returns path to the new session file.
        """
        import time
        from datetime import datetime, timezone

        if not self.is_available():
            raise RuntimeError("Claude Code is not installed.")

        projects_dir = self.base / "projects"
        if not projects_dir.exists():
            projects_dir.mkdir(parents=True, exist_ok=True)

        target_dir = Path(project_path) if project_path else None
        if target_dir:
            target_dir = projects_dir / target_dir.name
        else:
            target_dir = projects_dir / f"aimem-transfer-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        if not target_dir.exists():
            target_dir.mkdir(parents=True, exist_ok=True)

        new_session_id = session.id.replace("claude-", "").replace("gemini-", "").replace("qwen-", "")[:16]
        session_file = target_dir / f"{new_session_id}.jsonl"

        base_ts = datetime.now(timezone.utc).isoformat()
        parent_uuid = None

        with open(session_file, "w", encoding="utf-8") as f:
            first_msg = True
            for msg in session.messages:
                ts = msg.timestamp or base_ts
                msg_uuid = msg.id or str(uuid.uuid4())

                if msg.role == "user":
                    entry = {
                        "type": "user",
                        "uuid": msg_uuid,
                        "timestamp": ts,
                        "parentUuid": parent_uuid,
                        "message": {
                            "role": "user",
                            "content": [{"type": "text", "text": msg.content}]
                        }
                    }
                elif msg.role == "assistant":
                    entry = {
                        "type": "assistant",
                        "uuid": msg_uuid,
                        "timestamp": ts,
                        "parentUuid": parent_uuid,
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "text", "text": msg.content}]
                        }
                    }
                else:
                    continue

                if first_msg:
                    entry["cwd"] = session.metadata.project_path or str(target_dir)
                    entry["entrypoint"] = "aimem-transfer"
                    first_msg = False

                f.write(json.dumps(entry) + "\n")
                parent_uuid = msg_uuid

        return session_file
