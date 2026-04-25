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
import re
import shutil
import sqlite3
import string
import subprocess
import uuid

from ..models import UniversalSession, Message, SessionMetadata
from ..context_manager import get_model_limit


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


def _generate_import_message_id(batch_id: str, index: int) -> str:
    # OpenCode's prompt loop currently compares message IDs lexicographically to
    # decide whether the latest assistant response is after the latest user turn.
    # Keep imported message IDs safely below OpenCode's runtime-generated IDs so
    # the next real user prompt is treated as the active turn.
    return f"msg_000{batch_id}{index:08x}"


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


def _normalize_provider_model(provider_id: str, model_id: str) -> tuple[str, str] | None:
    provider = provider_id.strip()
    model = model_id.strip()
    if not provider or not model:
        return None
    if any(ch.isspace() for ch in provider):
        return None
    # Reject human-readable labels like "Codex (openai)".
    if any(ch.isspace() for ch in model) or "(" in model or ")" in model:
        return None
    return provider, model


def _parse_provider_model(text: str) -> tuple[str, str] | None:
    value = text.strip()
    if not value:
        return None
    for separator in ("/", ":"):
        if separator in value:
            provider, model = value.split(separator, 1)
            normalized = _normalize_provider_model(provider, model)
            if normalized:
                return normalized
    return None


def _latest_db_model_info(db_path: Path) -> tuple[str, str] | None:
    if not db_path.exists():
        return None

    connection = sqlite3.connect(db_path)
    try:
        cursor = connection.cursor()
        rows = cursor.execute(
            """
            select data
            from message
            order by time_updated desc
            limit 200
            """
        ).fetchall()
    except sqlite3.Error:
        return None
    finally:
        connection.close()

    for row in rows:
        if not row:
            continue
        payload_raw = row[0]
        if not isinstance(payload_raw, str) or not payload_raw:
            continue
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue

        candidates: list[tuple[str, str]] = []

        provider = payload.get("providerID")
        model_id = payload.get("modelID")
        if isinstance(provider, str) and isinstance(model_id, str):
            candidates.append((provider, model_id))

        model_block = payload.get("model")
        if isinstance(model_block, dict):
            provider = model_block.get("providerID")
            model_id = model_block.get("modelID")
            if isinstance(provider, str) and isinstance(model_id, str):
                candidates.append((provider, model_id))

        for candidate_provider, candidate_model in candidates:
            normalized = _normalize_provider_model(candidate_provider, candidate_model)
            if normalized:
                return normalized

    return None


def _recent_db_model_infos(db_path: Path, limit: int = 500) -> list[tuple[str, str]]:
    if not db_path.exists():
        return []

    connection = sqlite3.connect(db_path)
    try:
        cursor = connection.cursor()
        rows = cursor.execute(
            """
            select data
            from message
            order by time_updated desc
            limit ?
            """,
            (limit,),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        connection.close()

    models: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if not row:
            continue
        payload_raw = row[0]
        if not isinstance(payload_raw, str) or not payload_raw:
            continue
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue

        candidates: list[tuple[str, str]] = []
        provider = payload.get("providerID")
        model_id = payload.get("modelID")
        if isinstance(provider, str) and isinstance(model_id, str):
            candidates.append((provider, model_id))

        model_block = payload.get("model")
        if isinstance(model_block, dict):
            provider = model_block.get("providerID")
            model_id = model_block.get("modelID")
            if isinstance(provider, str) and isinstance(model_id, str):
                candidates.append((provider, model_id))

        for candidate_provider, candidate_model in candidates:
            normalized = _normalize_provider_model(candidate_provider, candidate_model)
            if normalized and normalized not in seen:
                seen.add(normalized)
                models.append(normalized)

    return models


def _model_choice(provider_id: str, model_id: str, source: str = "opencode") -> dict | None:
    normalized = _normalize_provider_model(provider_id, model_id)
    if not normalized:
        return None
    provider, model = normalized
    return {
        "provider_id": provider,
        "model_id": model,
        "value": f"{provider}/{model}",
        "label": f"{provider}/{model}",
        "source": source,
    }


def _add_model_choice(
    choices: list[dict],
    seen: set[str],
    provider_id: str,
    model_id: str,
    source: str,
) -> None:
    choice = _model_choice(provider_id, model_id, source=source)
    if not choice:
        return
    key = choice["value"].lower()
    if key in seen:
        return
    seen.add(key)
    choices.append(choice)


def _models_from_text(output: str) -> list[tuple[str, str]]:
    models: list[tuple[str, str]] = []
    current_provider: str | None = None
    ansi = re.compile(r"\x1b\[[0-9;]*m")
    provider_header = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*:?\s*$")
    provider_model = re.compile(r"\b([A-Za-z0-9_.-]+)/([A-Za-z0-9][A-Za-z0-9_.:-]*)\b")
    bare_model = re.compile(r"^\s*[-*]?\s*([A-Za-z0-9][A-Za-z0-9_.:-]*(?:-[A-Za-z0-9_.:-]+)+)")

    for raw_line in output.splitlines():
        clean_line = ansi.sub("", raw_line)
        line = clean_line.strip()
        if not line:
            continue

        matched_provider_model = False
        for match in provider_model.finditer(line):
            normalized = _normalize_provider_model(match.group(1), match.group(2))
            if normalized:
                models.append(normalized)
                current_provider = normalized[0]
                matched_provider_model = True

        if matched_provider_model:
            continue

        if current_provider:
            model_match = bare_model.match(line)
            if model_match:
                normalized = _normalize_provider_model(current_provider, model_match.group(1))
                if normalized:
                    models.append(normalized)
                    continue

        is_indented = clean_line[:1].isspace()
        header_match = provider_header.match(line)
        if not is_indented and header_match and not any(ch.isspace() for ch in header_match.group(1)):
            current_provider = header_match.group(1)

    return models


def _model_info_from_override(model: str | None) -> tuple[str, str] | None:
    if not model:
        return None
    parsed = _parse_provider_model(model)
    if parsed:
        return parsed
    raise ValueError("OpenCode model override must be in provider/model format.")


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _message_tokens(msg: Message) -> int:
    return _estimate_tokens(msg.content or "") + 10


def _messages_tokens(messages: list[Message]) -> int:
    return sum(_message_tokens(msg) for msg in messages)


def _max_input_tokens_for_model(provider_id: str, model_id: str) -> int:
    return get_model_limit(model_id, provider_id).recommended_input


def _compressed_summary_message(session: UniversalSession) -> Message:
    compressed = session.compressed
    if compressed is None:
        raise ValueError("Session has no compressed summary.")

    lines = [
        "# Previous Session Summary",
        "",
        f"Source: {session.metadata.source_agent or session.source or 'unknown'}",
    ]
    if session.metadata.project_path:
        lines.append(f"Project: {session.metadata.project_path}")
    if session.metadata.original_session_id:
        lines.append(f"Original session: {session.metadata.original_session_id}")

    if compressed.current_goal:
        lines.extend(["", "## Current Goal", compressed.current_goal])
    if compressed.key_decisions:
        lines.append("")
        lines.append("## Key Decisions")
        lines.extend(f"- {item}" for item in compressed.key_decisions)
    if compressed.todo_list:
        lines.append("")
        lines.append("## Todo")
        lines.extend(f"- [ ] {item}" for item in compressed.todo_list)
    if compressed.current_errors:
        lines.append("")
        lines.append("## Current Errors")
        lines.extend(f"- {item}" for item in compressed.current_errors)
    if compressed.latest_code:
        lines.append("")
        lines.append("## Latest Code")
        for item in compressed.latest_code[:5]:
            label = item.path or "snippet"
            lines.append(f"{label}:")
            lines.append(item.content[:500])
            lines.append("")

    lines.extend(["", "Continue from this summarized context."])
    return Message(
        id=_generate_message_id("msg_"),
        role="user",
        content="\n".join(lines).strip(),
        timestamp=session.updated_at,
    )


def _append_opencode_text_part(
    part_rows: list[tuple[str, str, int, int, str]],
    message_id: str,
    created: int,
    text: str,
    *,
    synthetic: bool = False,
    metadata: dict | None = None,
) -> None:
    if not text.strip():
        return
    data = {"type": "text", "text": text.strip()}
    if synthetic:
        data["synthetic"] = True
    if metadata:
        data["metadata"] = metadata
    part_rows.append((
        _generate_message_id("prt_"),
        message_id,
        created,
        created,
        json.dumps(data, ensure_ascii=False),
    ))


def _messages_for_injection(session: UniversalSession) -> list[Message]:
    if session.compressed:
        return [_compressed_summary_message(session)]
    return [msg for msg in session.messages if msg.role in ("user", "assistant")]


def _raise_if_context_too_large(
    messages: list[Message],
    provider_id: str,
    model_id: str,
) -> None:
    token_budget = _max_input_tokens_for_model(provider_id, model_id)
    token_count = _messages_tokens(messages)
    if token_count <= token_budget:
        return

    raise RuntimeError(
        "\n".join([
            "OpenCode injection stopped before writing because this session is too large for the selected model.",
            f"Target model: {provider_id}/{model_id}",
            f"Estimated input: ~{token_count:,} tokens; safe budget: ~{token_budget:,} tokens.",
            "",
            "Use one of these instead:",
            "  aimem load <session-id> --to opencode --compress --inject",
            "  aimem load <session-id> --to opencode --chunk",
            "  aimem load <session-id> --to opencode --inject --opencode-model provider/model",
            "  Or select a larger-context OpenCode model in the TUI, then inject again.",
        ])
    )


def _pick_model_info(session: UniversalSession, db_path: Path) -> tuple[str, str]:
    # 1) Prefer provider/model captured from source messages.
    for msg in reversed(session.messages):
        metadata = msg.metadata or {}
        provider = metadata.get("provider_id") or metadata.get("providerID")
        model_id = metadata.get("model_id") or metadata.get("modelID")
        if isinstance(provider, str) and isinstance(model_id, str):
            normalized = _normalize_provider_model(provider, model_id)
            if normalized:
                return normalized

    # 2) Parse explicit "<provider>/<model>" or "<provider>:<model>" metadata model.
    metadata_model = (session.metadata.model or "").strip()
    parsed = _parse_provider_model(metadata_model)
    if parsed:
        return parsed

    # 3) Only reuse a plain model id when the source session was already OpenCode.
    # A Codex/Gemini/Qwen source model like "gpt-5.4" is not necessarily configured
    # under OpenCode and can trigger ProviderModelNotFoundError.
    source_agent = (session.metadata.source_agent or session.source or "").lower()
    if source_agent == "opencode":
        normalized_plain = _normalize_provider_model("opencode", metadata_model)
        if normalized_plain:
            return normalized_plain

    # 4) Fallback to the latest valid provider/model found in OpenCode DB.
    recent = _latest_db_model_info(db_path)
    if recent:
        return recent

    # 5) Last-resort default.
    return "opencode", "minimax-m2.5-free"


class OpenCodeAdapter:
    name = "opencode"
    description = "OpenCode CLI"

    def __init__(self):
        self.db_path = _get_opencode_db()

    def is_available(self) -> bool:
        return self.db_path.exists()

    def list_models(self) -> list[dict]:
        choices: list[dict] = []
        seen: set[str] = set()

        try:
            result = _run_opencode(["models"])
        except (OSError, subprocess.SubprocessError):
            result = None

        if result is not None and result.returncode == 0:
            output = "\n".join(part for part in (result.stdout, result.stderr) if part)
            for provider_id, model_id in _models_from_text(output):
                _add_model_choice(choices, seen, provider_id, model_id, "opencode models")

        for provider_id, model_id in _recent_db_model_infos(self.db_path):
            _add_model_choice(choices, seen, provider_id, model_id, "recent OpenCode sessions")

        fallback = _model_choice("opencode", "minimax-m2.5-free", source="default")
        if fallback and fallback["value"].lower() not in seen:
            choices.append(fallback)

        return choices

    def injection_context_status(self, session: UniversalSession, model: str | None = None) -> dict:
        override = _model_info_from_override(model)
        provider_id, model_id = override or _pick_model_info(session, self.db_path)
        messages = _messages_for_injection(session)
        estimated_tokens = _messages_tokens(messages)
        budget = _max_input_tokens_for_model(provider_id, model_id)
        return {
            "provider_id": provider_id,
            "model_id": model_id,
            "estimated_tokens": estimated_tokens,
            "budget": budget,
            "will_fit": estimated_tokens <= budget,
            "compressed": bool(session.compressed),
        }

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

    def inject(self, session: UniversalSession, model: str | None = None) -> Path:
        if not self.is_available():
            raise RuntimeError("OpenCode CLI is not installed.")

        cwd = session.metadata.project_path or os.getcwd()
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        new_session_id = _generate_session_id()
        override = _model_info_from_override(model)
        provider_id, model_id = override or _pick_model_info(session, self.db_path)
        inject_messages = _messages_for_injection(session)
        _raise_if_context_too_large(inject_messages, provider_id, model_id)
        title = session.note or f"Transferred from {session.metadata.source_agent}"
        slug = _safe_slug(title)
        message_rows: list[tuple[str, int, int, str]] = []
        part_rows: list[tuple[str, str, int, int, str]] = []
        previous_id: str | None = None
        import_id_batch = uuid.uuid4().hex[:16]

        # Keep the imported transcript safely before "now". OpenCode orders the
        # chat by message timestamps; if an imported transcript extends into the
        # near future, a prompt typed right after opening the session can be
        # inserted in the middle and never become the active turn.
        import_step_ms = 10
        import_gap_ms = 5000
        import_end_ms = now_ms - import_gap_ms
        current_time = import_end_ms - ((len(inject_messages) - 1) * import_step_ms)
        for index, msg in enumerate(inject_messages):
            created = current_time
            updated = created + 1
            current_time += import_step_ms
            message_id = _generate_import_message_id(import_id_batch, index)
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
            _append_opencode_text_part(
                part_rows,
                message_id,
                created,
                msg.content or "",
                synthetic=bool(session.compressed),
                metadata={"aimem_context": True} if session.compressed else None,
            )

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
