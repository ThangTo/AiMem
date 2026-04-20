"""
AiMem CLI - Command line interface.
Usage: aimem <command> [options]
"""

import argparse
import sys
import os
import json
from pathlib import Path

# ─────────────────────────────────────────────────────────────
# Adapter imports
# ─────────────────────────────────────────────────────────────

from .adapters.claude import ClaudeAdapter
from .adapters.qwen import QwenAdapter
from .adapters.gemini import GeminiAdapter
from .adapters.aider import AiderAdapter
from .adapters.codex import CodexAdapter
from .adapters.opencode import OpenCodeAdapter
from .adapters.clipboard import ClipboardAdapter
from .adapters.output import MarkdownOutput, ClaudeOutput, GeminiOutput, QwenOutput, PromptOutput, ContinueOutput, CodexOutput, OpenCodeOutput
from .storage import FileStorage, load_config, save_config, _get_config_path, DEFAULT_CONFIG
from .models import UniversalSession
from .compression import CompressionEngine
from .context_manager import (
    get_load_advice, print_load_advice, chunk_session,
    merge_sessions, auto_trim, AGENT_LIMITS,
)


# ─────────────────────────────────────────────────────────────
# Colors & Formatting
# ─────────────────────────────────────────────────────────────

try:
    from termcolor import colored
except ImportError:
    def colored(text: str, color: str = "") -> str:
        return text


def _ansi(text: str) -> str:
    """Strip ANSI codes for non-TTY output."""
    import sys
    if not hasattr(sys.stdout, 'isatty') or not sys.stdout.isatty():
        # Remove emoji/ansi when piped
        import re
        text = re.sub(r'\x1b\[[0-9;]*m', '', text)
        text = re.sub(r'[\U0001F300-\U0001F9FF]', '', text)  # emoji
    return text


def success(msg: str) -> str:
    try:
        from termcolor import colored
        return _ansi(colored(f"[OK] {msg}", "green"))
    except Exception:
        return _ansi(f"[OK] {msg}")


def info(msg: str) -> str:
    try:
        from termcolor import colored
        return _ansi(colored(f"[i] {msg}", "cyan"))
    except Exception:
        return _ansi(f"[i] {msg}")


def error(msg: str) -> str:
    try:
        from termcolor import colored
        return _ansi(colored(f"[X] {msg}", "red"))
    except Exception:
        return _ansi(f"[X] {msg}")


def warn(msg: str) -> str:
    try:
        from termcolor import colored
        return _ansi(colored(f"[!] {msg}", "yellow"))
    except Exception:
        return _ansi(f"[!] {msg}")


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _format_timestamp(ts: str) -> str:
    """Format ISO timestamp to human-readable."""
    if not ts:
        return "unknown"
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        now = datetime.now()
        diff = now - dt
        if diff.total_seconds() < 60:
            return "just now"
        elif diff.total_seconds() < 3600:
            return f"{int(diff.total_seconds() // 60)}m ago"
        elif diff.total_seconds() < 86400:
            return f"{int(diff.total_seconds() // 3600)}h ago"
        else:
            return dt.strftime("%b %d, %H:%M")
    except Exception:
        return ts[:16]


def _print_session_list(sessions: list[dict], label: str = "Sessions"):
    """Pretty print session list."""
    print(f"\n{label}:")
    print("─" * 60)
    if not sessions:
        print("  (none found)")
        return

    for i, sess in enumerate(sessions, 1):
        ts = _format_timestamp(sess.get("timestamp", ""))
        title = sess.get("title", "No title")[:45]
        src = sess.get("source", "?").upper()
        msgs = sess.get("total_messages", 0)

        print(f"  [{i}] {src} | {ts} | {msgs} msgs")
        print(f"      {title}")
        print()


def _get_output_formatter(format: str):
    """Get output formatter by name."""
    formatters = {
        "markdown": MarkdownOutput,
        "claude": ClaudeOutput,
        "gemini": GeminiOutput,
        "qwen": QwenOutput,
        "prompt": PromptOutput,
        "continue": ContinueOutput,
        "codex": CodexOutput,
    }
    fmt = formatters.get(format, MarkdownOutput)
    return fmt()


# ─────────────────────────────────────────────────────────────
# COMMANDS
# ─────────────────────────────────────────────────────────────

def cmd_init(args):
    """Initialize AiMem config."""
    config_path = _get_config_path()

    if config_path.exists():
        print(warn(f"Config already exists at: {config_path}"))
        if not args.force:
            print("  Use --force to overwrite.")
            return

    config_path.parent.mkdir(parents=True, exist_ok=True)
    save_config(DEFAULT_CONFIG)

    print(success(f"Initialized AiMem at: {config_path}"))
    print()
    print("Config saved:")
    print(json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False))
    print()
    print("Next steps:")
    print("  aimem save --from claude    # Save current Claude session")
    print("  aimem load --to gemini      # Load into Gemini CLI")
    print()


def cmd_save(args):
    """Save a session to AiMem storage."""
    source = args.from_agent or args.source

    if source == "clipboard" or args.clipboard:
        adapter = ClipboardAdapter()
        if not adapter.is_available():
            print(error("Clipboard not available. Install pyperclip: pip install pyperclip"))
            return
        session = adapter.export()
    elif source == "claude":
        adapter = ClaudeAdapter()
        if not adapter.is_available():
            print(error("Claude Code not found. Is it installed?"))
            return
        session_id = args.session_id
        if not session_id:
            sessions = adapter.list_sessions()
            if not sessions:
                print(error("No Claude sessions found."))
                return
            if len(sessions) == 1:
                session_id = sessions[0]["session_id"]
            else:
                print(info(f"Found {len(sessions)} Claude sessions. Select one:"))
                for i, s in enumerate(sessions[:10], 1):
                    ts = _format_timestamp(s.get("timestamp", ""))
                    print(f"  [{i}] {ts} | {s.get('title', '(no title)')[:50]}")
                try:
                    choice = input("  Enter number (default=1): ").strip()
                    idx = int(choice) - 1 if choice else 0
                    session_id = sessions[max(0, min(idx, len(sessions)-1))]["session_id"]
                except (ValueError, EOFError):
                    session_id = sessions[0]["session_id"]
        session = adapter.export(session_id=session_id)
    elif source == "qwen":
        adapter = QwenAdapter()
        if not adapter.is_available():
            print(error("Qwen CLI not found. Is it installed?"))
            return
        session_id = args.session_id
        if not session_id:
            sessions = adapter.list_sessions()
            if not sessions:
                print(error("No Qwen sessions found."))
                return
            if len(sessions) == 1:
                session_id = sessions[0]["session_id"]
            else:
                print(info(f"Found {len(sessions)} Qwen sessions. Select one:"))
                for i, s in enumerate(sessions[:10], 1):
                    ts = _format_timestamp(s.get("timestamp", ""))
                    print(f"  [{i}] {ts} | {s.get('title', '(no title)')[:50]}")
                try:
                    choice = input("  Enter number (default=1): ").strip()
                    idx = int(choice) - 1 if choice else 0
                    session_id = sessions[max(0, min(idx, len(sessions)-1))]["session_id"]
                except (ValueError, EOFError):
                    session_id = sessions[0]["session_id"]
        session = adapter.export(session_id=session_id)
    elif source == "gemini":
        adapter = GeminiAdapter()
        if not adapter.is_available():
            print(error("Gemini CLI not found. Is it installed?"))
            return
        session_id = args.session_id
        if not session_id:
            sessions = adapter.list_sessions()
            if not sessions:
                print(error("No Gemini sessions found."))
                return
            if len(sessions) == 1:
                session_id = sessions[0]["session_id"]
            else:
                print(info(f"Found {len(sessions)} Gemini sessions. Select one:"))
                for i, s in enumerate(sessions[:10], 1):
                    ts = _format_timestamp(s.get("timestamp", ""))
                    print(f"  [{i}] {ts} | {s.get('title', '(no title)')[:50]}")
                try:
                    choice = input("  Enter number (default=1): ").strip()
                    idx = int(choice) - 1 if choice else 0
                    session_id = sessions[max(0, min(idx, len(sessions)-1))]["session_id"]
                except (ValueError, EOFError):
                    session_id = sessions[0]["session_id"]
        session = adapter.export(session_id=session_id)
    elif source == "aider":
        adapter = AiderAdapter()
        if not adapter.is_available():
            print(error("Aider history not found. Is Aider installed?"))
            return
        session = adapter.export()
    elif source == "codex":
        adapter = CodexAdapter()
        if not adapter.is_available():
            print(error("Codex CLI not found. Is it installed?"))
            return
        session_id = args.session_id
        if not session_id:
            sessions = adapter.list_sessions()
            if not sessions:
                print(error("No Codex sessions found."))
                return
            if len(sessions) == 1:
                session_id = sessions[0]["session_id"]
            else:
                print(info(f"Found {len(sessions)} Codex sessions. Select one:"))
                for i, s in enumerate(sessions[:10], 1):
                    ts = _format_timestamp(s.get("timestamp", ""))
                    print(f"  [{i}] {ts} | {s.get('title', '(no title)')[:50]}")
                try:
                    choice = input("  Enter number (default=1): ").strip()
                    idx = int(choice) - 1 if choice else 0
                    session_id = sessions[max(0, min(idx, len(sessions)-1))]["session_id"]
                except (ValueError, EOFError):
                    session_id = sessions[0]["session_id"]
        session = adapter.export(session_id=session_id)
    elif source == "continue":
        from .adapters.continue_dev import ContinueAdapter
        adapter = ContinueAdapter()
        if not adapter.is_available():
            print(error("Continue.dev not found. Is it installed?"))
            return
        session = adapter.export(session_id=args.session_id)
    elif source == "opencode":
        adapter = OpenCodeAdapter()
        if not adapter.is_available():
            print(error("OpenCode CLI not found. Is it installed?"))
            return
        session_id = args.session_id
        if not session_id:
            sessions = adapter.list_sessions()
            if not sessions:
                print(error("No OpenCode sessions found."))
                return
            if len(sessions) == 1:
                session_id = sessions[0]["session_id"]
            else:
                print(info(f"Found {len(sessions)} OpenCode sessions. Select one:"))
                for i, s in enumerate(sessions[:10], 1):
                    ts = _format_timestamp(s.get("timestamp", ""))
                    print(f"  [{i}] {ts} | {s.get('title', '(no title)')[:50]}")
                try:
                    choice = input("  Enter number (default=1): ").strip()
                    idx = int(choice) - 1 if choice else 0
                    session_id = sessions[max(0, min(idx, len(sessions)-1))]["session_id"]
                except (ValueError, EOFError):
                    session_id = sessions[0]["session_id"]
        session = adapter.export(session_id=session_id)
    else:
        # Auto-detect
        adapters = [ClaudeAdapter(), QwenAdapter(), GeminiAdapter(), CodexAdapter(), OpenCodeAdapter()]
        for a in adapters:
            if a.is_available():
                try:
                    session = a.export(session_id=args.session_id)
                    source = a.name
                    break
                except Exception:
                    continue
        else:
            # Fallback to clipboard
            print(info("No CLI sessions found. Falling back to clipboard..."))
            adapter = ClipboardAdapter()
            session = adapter.export()

    # Save to file storage
    path = FileStorage.save(session)
    print(success(f"Saved session: {session.id}"))
    print(f"  Source: {session.source}")
    print(f"  Messages: {len(session.messages)}")
    print(f"  Tokens (est): ~{session.estimate_tokens():,}")
    print(f"  Location: {path}")

    # Auto-trim on save (smart cleanup before saving)
    if source in ("claude", "qwen", "gemini"):
        trim_result = auto_trim(session, target=source)
        if trim_result.dropped_items:
            unique_drops = list(dict.fromkeys(trim_result.dropped_items))
            print(info(f"Auto-trimmed: {trim_result.original_count - trim_result.trimmed_count} "
                     f"messages removed ({trim_result.original_tokens - trim_result.trimmed_tokens:,} tokens saved)"))
            print(f"  Dropped: {', '.join(unique_drops[:5])}")

    # Compression (opt-in via --compress flag OR compression.enabled in config)
    should_compress = args.compress or load_config().get("compression", {}).get("enabled", False)

    if should_compress:
        config = load_config()
        engine = CompressionEngine(config)

        if not engine.is_configured():
            print(warn("Compression requires API key. Set with:"))
            print("  aimem config set compression.enabled true")
            print("  aimem config set compression.api_key YOUR_KEY")
            print("  aimem config set compression.provider groq")
        else:
            print(info("Compressing session..."))
            original_tokens = session.estimate_tokens()
            session.compressed = engine.compress(session)

            if session.compressed:
                # Re-save with compressed data
                path = FileStorage.save(session)
                compressed_tokens = session.compressed.summary_token_count
                ratio = compressed_tokens / max(original_tokens, 1)

                print(success(f"Compressed: {original_tokens:,} tokens -> {compressed_tokens:,} tokens"))
                print(f"  Reduction: {ratio * 100:.1f}% of original")
                print(f"  Goal: {session.compressed.current_goal[:60]}...")
                if session.compressed.current_errors:
                    print(f"  Errors: {len(session.compressed.current_errors)} found")
                if session.compressed.todo_list:
                    print(f"  Todos: {len(session.compressed.todo_list)} pending")
            else:
                print(warn("Compression returned no result. Session saved without compression."))

    if args.clipboard_auto or load_config().get("output", {}).get("clipboard_auto"):
        config = load_config()
        fmt = getattr(args, "format", None) or config.get("output", {}).get("format", "markdown")
        formatted = _get_output_formatter(fmt).transform(session)
        try:
            import pyperclip
            pyperclip.copy(formatted)
            print(f"\n[*] Copied to clipboard as {fmt}.")
        except ImportError:
            pass


def cmd_load(args):
    """Load a session and output for target agent."""
    target = args.to_agent or args.target or "clipboard"
    session_id = args.session_id or args.id

    if not session_id:
        print(error("Session ID required. Use 'aimem list' to see available sessions."))
        return

    # Load from file storage
    try:
        session = FileStorage.load(session_id)
    except FileNotFoundError:
        print(error(f"Session not found: {session_id}"))
        print("  Use 'aimem list' to see available sessions.")
        return

    # Context analysis before load
    if args.analyze:
        advice = get_load_advice(session, target)
        print_load_advice(advice)

    # Smart chunking if session too large
    if args.chunk:
        advice = get_load_advice(session, target)
        if not advice.will_fit:
            result = chunk_session(session, target)
            if result.chunks:
                for i, chunk in enumerate(result.chunks, 1):
                    print(f"\n{'='*60}")
                    print(f"📦 CHUNK {i}/{len(result.chunks)} "
                          f"({result.chunk_token_counts[i-1]:,} tokens, "
                          f"{result.messages_per_chunk[i-1]} messages)")
                    print("=" * 60)
                    print(chunk)
                return
        else:
            print(info(f"Session fits in {advice.target_model} — no chunking needed."))

    # Compression on load (opt-in via --compress flag OR compression.enabled in config)
    if args.compress or load_config().get("compression", {}).get("enabled", False):
        config = load_config()
        engine = CompressionEngine(config)

        if not engine.is_configured():
            print(warn("Compression requires API key. Set with:"))
            print("  aimem config set compression.enabled true")
            print("  aimem config set compression.api_key YOUR_KEY")
            print("  aimem config set compression.provider groq")
        else:
            print(info("Compressing session..."))
            original_tokens = session.estimate_tokens()
            session.compressed = engine.compress(session)

            if session.compressed:
                compressed_tokens = session.compressed.summary_token_count
                ratio = compressed_tokens / max(original_tokens, 1)
                print(success(f"Compressed: {original_tokens:,} tokens -> {compressed_tokens:,} tokens"))

                if session.compressed.current_goal:
                    print(f"  Goal: {session.compressed.current_goal[:60]}...")

    # Inject directly into target agent storage
    if args.inject:
        inject_targets = {
            "claude": ClaudeAdapter,
            "gemini": GeminiAdapter,
            "qwen": QwenAdapter,
            "codex": CodexAdapter,
            "opencode": OpenCodeAdapter,
        }

        if target not in inject_targets:
            print(error(f"--inject only supports: {', '.join(inject_targets.keys())}"))
            print("  For other formats, use: aimem load <id> --to <format>")
            return

        adapter_cls = inject_targets[target]
        adapter = adapter_cls()

        if not adapter.is_available():
            print(error(f"{target.capitalize()} CLI/storage not found. Is it installed?"))
            return

        print(info(f"Injecting session into {target} storage..."))
        try:
            injected_path = adapter.inject(session)
            print(success(f"Injected into {target}!"))
            print(f"  Path: {injected_path}")
            print(f"  Messages: {len(session.messages)}")
            print(f"  Tokens: ~{session.estimate_tokens():,}")
            print(f"\nYou can now open {target} and continue from this session.")
            return
        except Exception as e:
            print(error(f"Failed to inject: {e}"))
            if os.environ.get("AIMEM_DEBUG"):
                import traceback
                traceback.print_exc()
            return

    # Get formatter - --to takes priority over --format
    format = args.to_agent or args.target or args.format or load_config().get("output", {}).get("format", "markdown")
    formatter = _get_output_formatter(format)

    # Transform
    output = formatter.transform(session)

    # Output
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(success(f"Written to: {args.output}"))
    else:
        print(output)

    # Auto-copy to clipboard
    if args.copy or (load_config().get("output", {}).get("clipboard_auto") and not args.output):
        try:
            import pyperclip
            pyperclip.copy(output)
            print(f"\n* Copied to clipboard (format: {format})")
        except ImportError:
            pass

    # Context warning on load
    advice = get_load_advice(session, target)
    if advice.compression_recommended:
        print(warn(f"Session may be large for {advice.target_model}. "
                   f"Consider using: aimem load {session_id} --to {target} --compress"))
    if not advice.will_fit:
        print(warn(f"Session EXCEEDS {advice.target_model} context limit."))

    # Print summary
    print(f"\n[Session Summary]")
    print(f"  ID: {session.id}")
    print(f"  Source: {session.source}")
    print(f"  Messages: {len(session.messages)}")
    print(f"  ~{session.estimate_tokens():,} tokens")
    print(f"  Formatted for: {target}")


def cmd_list(args):
    """List all saved sessions."""
    sessions = FileStorage.list()

    if not sessions:
        print(info("No saved sessions. Run 'aimem save' first."))
        print()
        print("You can also check available agent sessions:")
        print("  aimem list --agents")
        return

    print(f"\n* Saved Sessions ({len(sessions)} total)")
    print("=" * 60)

    for sess in sessions:
        ts = _format_timestamp(sess.created_at)
        token_est = sess.estimate_tokens()
        src = sess.source.upper()
        msg_count = len(sess.messages)
        goal = sess.compressed.current_goal if sess.compressed else ""

        print(f"\n  {sess.id}")
        print(f"    Source: {src} | Messages: {msg_count} | ~{token_est:,} tokens | {ts}")
        if goal:
            print(f"    Goal: {goal[:50]}...")
        if sess.note:
            print(f"    Note: {sess.note}")


def cmd_merge(args):
    """Merge multiple sessions into one."""
    session_ids = args.session_ids

    if not session_ids:
        print(error("Provide session IDs to merge. Example: aimem merge sess1 sess2"))
        print("Use 'aimem list' to see available sessions.")
        return

    if len(session_ids) < 2:
        print(error("Need at least 2 session IDs to merge."))
        return

    # Load all sessions
    sessions = []
    errors = []
    for sid in session_ids:
        try:
            sess = FileStorage.load(sid)
            sessions.append(sess)
        except FileNotFoundError:
            errors.append(sid)

    if errors:
        print(warn(f"Could not load: {', '.join(errors)}"))

    if len(sessions) < 2:
        print(error("Need at least 2 valid sessions to merge."))
        return

    # Merge
    method = "smart_merge" if args.smart else "append"
    print(info(f"Merging {len(sessions)} sessions ({method})..."))

    result = merge_sessions(sessions, method=method, target=args.to_agent)

    # Save merged session
    path = FileStorage.save(result.session)

    # Auto-trim if target specified
    if args.to_agent:
        trim_result = auto_trim(result.session, target=args.to_agent)
        if trim_result.dropped_items:
            FileStorage.save(result.session)  # Re-save with trimmed content
            print(info(f"Auto-trimmed for {args.to_agent}: "
                      f"{trim_result.original_count - trim_result.trimmed_count} msgs removed"))

    # Print summary
    print(success(f"Merged {result.source_count} sessions into: {result.session.id}"))
    print(f"  Original sessions: {', '.join(result.original_sessions)}")
    print(f"  Total messages: {result.session.metadata.token_count // 4:,} tokens (est)")
    print(f"  Total messages: {len(result.session.messages)}")
    print(f"  Location: {path}")
    print(f"\nLoad with: aimem load {result.session.id} --to {args.to_agent or 'markdown'}")


def cmd_list_agents(args):
    """List available agent sessions."""
    print("\n* Checking available agents...")
    print()

    # Claude
    claude = ClaudeAdapter()
    print(f"  Claude Code: {'[OK] Available' if claude.is_available() else '[X] Not found'}")
    if claude.is_available():
        sessions = claude.list_sessions()[:3]
        all_sessions = claude.list_sessions()
        print(f"    Sessions found: {len(all_sessions)}")
        for s in sessions:
            title = s.get("title", "")
            print(f"    - {s['session_id'][:8]}... ({_format_timestamp(s['timestamp'])}) | {title[:40]}")

    print()

    # Qwen
    qwen = QwenAdapter()
    print(f"  Qwen CLI: {'[OK] Available' if qwen.is_available() else '[X] Not found'}")
    if qwen.is_available():
        sessions = qwen.list_sessions()[:3]
        all_sessions = qwen.list_sessions()
        print(f"    Sessions found: {len(all_sessions)}")
        for s in sessions:
            title = s.get("title", "")
            print(f"    - {s['session_id'][:8]}... ({_format_timestamp(s['timestamp'])}) | {title[:40]}")

    print()

    # Gemini
    gemini = GeminiAdapter()
    print(f"  Gemini CLI: {'[OK] Available' if gemini.is_available() else '[X] Not found'}")
    if gemini.is_available():
        sessions = gemini.list_sessions()[:3]
        all_sessions = gemini.list_sessions()
        print(f"    Sessions found: {len(all_sessions)}")
        for s in sessions:
            title = s.get("title", "")
            print(f"    - {s['session_id'][:8]}... ({_format_timestamp(s['timestamp'])}) | {title[:40]}")

    print()

    # Aider
    aider = AiderAdapter()
    print(f"  Aider: {'[OK] Available' if aider.is_available() else '[X] Not found'}")
    if aider.is_available():
        sessions = aider.list_sessions()[:3]
        all_sessions = aider.list_sessions()
        print(f"    Sessions found: {len(all_sessions)}")
        for s in sessions[:3]:
            title = s.get("title", "")
            print(f"    - {s['session_id']} | {title[:40]}")

    print()

    # Continue.dev
    from .adapters.continue_dev import ContinueAdapter
    cont = ContinueAdapter()
    print(f"  Continue.dev: {'[OK] Available' if cont.is_available() else '[X] Not found'}")
    if cont.is_available():
        sessions = cont.list_sessions()[:3]
        all_sessions = cont.list_sessions()
        print(f"    Sessions found: {len(all_sessions)}")
        for s in sessions[:3]:
            title = s.get("title", "")
            print(f"    - {s['session_id'][:8]}... | {title[:40]}")

    print()

    # Clipboard
    clip = ClipboardAdapter()
    print(f"  Clipboard: {'[OK] Available' if clip.is_available() else '[!]  Install pyperclip'}")

    print()

    # OpenCode
    opencode = OpenCodeAdapter()
    print(f"  OpenCode: {'[OK] Available' if opencode.is_available() else '[X] Not found'}")
    if opencode.is_available():
        sessions = opencode.list_sessions()[:3]
        all_sessions = opencode.list_sessions()
        print(f"    Sessions found: {len(all_sessions)}")
        for s in sessions:
            title = s.get("title", "")
            print(f"    - {s['session_id'][:8]}... ({_format_timestamp(s['timestamp'])}) | {title[:40]}")

    print()


def cmd_config(args):
    """Show or update config."""
    if args.set:
        # Support: "key=value" or "key" "value"
        # argparse REMMAINDER captures all args after 'config' including the word 'set'
        raw_args = list(args.set)

        # Strip leading "set" if present
        if raw_args and raw_args[0] == "set":
            raw_args = raw_args[1:]

        if not raw_args:
            print(error("Invalid format. Use: aimem config set key=value"))
            return

        if len(raw_args) == 1:
            if "=" in raw_args[0]:
                key, value = raw_args[0].split("=", 1)
            else:
                print(error("Invalid format. Use: aimem config set key=value"))
                return
        else:
            key = raw_args[0]
            value = " ".join(raw_args[1:])

        config = load_config()

        # Navigate nested keys
        keys = key.split(".")
        current = config
        for k in keys[:-1]:
            if k not in current:
                current[k] = {}
            current = current[k]

        # Parse value
        if value.lower() in ("true", "false"):
            value = value.lower() == "true"
        elif value.isdigit():
            value = int(value)
        elif value.lower() == "null":
            value = None

        current[keys[-1]] = value
        save_config(config)
        print(success(f"Set {key} = {value}"))
        return

    # Show config
    config = load_config()
    print(json.dumps(config, indent=2, ensure_ascii=False))


def cmd_delete(args):
    """Delete a saved session."""
    session_id = args.session_id or args.id

    if not session_id:
        print(error("Session ID required."))
        return

    if FileStorage.delete(session_id):
        print(success(f"Deleted: {session_id}"))
    else:
        print(error(f"Session not found: {session_id}"))


# ─────────────────────────────────────────────────────────────
# Main CLI
# ─────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(
        prog="aimem",
        description="AiMem - AI Memory Switcher. Save, compress, and transfer context between AI agents.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  aimem init                          Initialize config
  aimem save --from claude            Save Claude session (interactive select)
  aimem save --from qwen              Save Qwen CLI session
  aimem save --from gemini            Save Gemini CLI session
  aimem save --from aider             Save Aider chat history
  aimem save --from continue          Save Continue.dev session
  aimem save --from clipboard         Save clipboard content
  aimem load sess-abc123 --to gemini  Load session as Gemini format
  aimem load sess-abc123 --to gemini --analyze  Show context analysis before loading
  aimem load sess-abc123 --to gemini --chunk     Split into chunks if too large
  aimem merge sess1 sess2 --to gemini  Merge 2 sessions
  aimem merge sess1 sess2 --smart      Smart merge (dedupe + merge)
  aimem list                          List saved sessions
  aimem list --agents                 List available agent sessions
  aimem config set compression.enabled true
  aimem config set compression.api_key YOUR_KEY

Repository: https://github.com/aimem/aimem
        """
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = subparsers.add_parser("init", help="Initialize AiMem config")
    p_init.add_argument("--force", action="store_true", help="Overwrite existing config")
    p_init.set_defaults(func=cmd_init)

    # save
    p_save = subparsers.add_parser("save", help="Save session from an agent")
    p_save.add_argument("--from", dest="from_agent", choices=["claude", "gemini", "qwen", "aider", "continue", "codex", "opencode", "clipboard"],
                       help="Source agent")
    p_save.add_argument("--source", dest="source", help="Alias for --from")
    p_save.add_argument("--session-id", help="Specific session ID to export")
    p_save.add_argument("--clipboard", action="store_true", help="Save from clipboard")
    p_save.add_argument("--compress", action="store_true", help="LLM compress (requires API key)")
    p_save.add_argument("--clipboard-auto", action="store_true", help="Auto-copy to clipboard")
    p_save.set_defaults(func=cmd_save)

    # load
    p_load = subparsers.add_parser("load", help="Load session for target agent")
    p_load.add_argument("session_id", nargs="?", help="Session ID to load")
    p_load.add_argument("--id", help="Alias for session_id")
    p_load.add_argument("--to", dest="to_agent", choices=["claude", "gemini", "qwen", "codex", "opencode", "markdown", "continue", "prompt"],
                       help="Target agent format")
    p_load.add_argument("--target", help="Alias for --to")
    p_load.add_argument("--format", "-f", choices=["markdown", "claude", "gemini", "qwen", "codex", "opencode", "prompt", "continue"],
                       help="Output format (default: markdown)")
    p_load.add_argument("--output", "-o", help="Write to file instead of stdout")
    p_load.add_argument("--copy", action="store_true", help="Copy output to clipboard")
    p_load.add_argument("--analyze", action="store_true",
                       help="Show context analysis (token count, warnings, suggestions)")
    p_load.add_argument("--chunk", action="store_true",
                       help="Split into chunks if session exceeds target context limit")
    p_load.add_argument("--compress", action="store_true",
                       help="LLM compress before output (requires API key)")
    p_load.add_argument("--inject", action="store_true",
                       help="Inject directly into target agent storage (claude, gemini, qwen, codex, opencode)")
    p_load.set_defaults(func=cmd_load)

    # merge
    p_merge = subparsers.add_parser("merge", help="Merge multiple sessions into one")
    p_merge.add_argument("session_ids", nargs="+", help="Session IDs to merge")
    p_merge.add_argument("--smart", action="store_true",
                         help="Smart merge: deduplicate, merge goals, combine todos")
    p_merge.add_argument("--to", dest="to_agent",
                         choices=["claude", "gemini", "qwen", "markdown", "continue"],
                         help="Target agent (for auto-trim sizing)")
    p_merge.set_defaults(func=cmd_merge)

    # list
    p_list = subparsers.add_parser("list", help="List saved sessions")
    p_list.add_argument("--agents", action="store_true", help="List agent sessions instead")
    p_list.set_defaults(func=lambda a: cmd_list_agents(a) if a.agents else cmd_list(a))

    # config
    p_config = subparsers.add_parser("config", help="Show/update config")
    p_config.add_argument("set", nargs=argparse.REMAINDER, help="Set key=value")
    p_config.set_defaults(func=cmd_config)

    # delete
    p_del = subparsers.add_parser("delete", help="Delete a saved session")
    p_del.add_argument("session_id", nargs="?", help="Session ID to delete")
    p_del.add_argument("--id", help="Alias for session_id")
    p_del.set_defaults(func=cmd_delete)

    # Parse
    args = parser.parse_args(argv)

    # Run
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nAborted.")
    except Exception as e:
        print(error(f"Error: {e}"))
        if os.environ.get("AIMEM_DEBUG"):
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()