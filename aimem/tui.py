import sys
import os
import time
import shutil
import base64
import argparse
import subprocess
import json
from pathlib import Path
from copy import deepcopy
from urllib.parse import quote
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
import questionary

from . import cli
from .storage import FileStorage, load_config, save_config
from .adapters.claude import ClaudeAdapter
from .adapters.qwen import QwenAdapter
from .adapters.gemini import GeminiAdapter
from .adapters.codex import CodexAdapter
from .adapters.opencode import OpenCodeAdapter
from .adapters.aider import AiderAdapter
from .adapters.clipboard import ClipboardAdapter
from .adapters.cursor import CursorAdapter
from .adapters.antigravity import AntigravityAdapter
from .context_manager import get_load_advice, chunk_session
from .compression import get_default_compression_model, list_compression_models
from .models import UniversalSession

console = Console()

def _escape_powershell_literal(value: str) -> str:
    return value.replace("'", "''")

def _launch_windows_terminal(command: str, project_path: str = "") -> None:
    lines = ["$ErrorActionPreference = 'Stop'"]
    start_dir = project_path if project_path and Path(project_path).exists() else ""
    if start_dir:
        safe_path = _escape_powershell_literal(start_dir)
        lines.append(f"Set-Location -LiteralPath '{safe_path}'")
    lines.append(command)

    encoded = base64.b64encode("\n".join(lines).encode("utf-16le")).decode("ascii")
    wt = shutil.which("wt")
    if wt:
        args = [wt]
        if start_dir:
            args.extend(["-d", start_dir])
        args.extend(["powershell", "-NoExit", "-EncodedCommand", encoded])
        subprocess.Popen(args)
        return

    create_new_console = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010)
    subprocess.Popen(
        ["powershell", "-NoExit", "-EncodedCommand", encoded],
        creationflags=create_new_console,
    )

def _find_vscode_launcher() -> str | None:
    localappdata = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", "")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", "")
    candidates = [
        os.environ.get("AIMEM_VSCODE_PATH"),
        str(Path(localappdata) / "Programs" / "Microsoft VS Code" / "bin" / "code.cmd"),
        str(Path(program_files) / "Microsoft VS Code" / "bin" / "code.cmd"),
        str(Path(program_files_x86) / "Microsoft VS Code" / "bin" / "code.cmd"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    for name in ("code.cmd", "code.exe", "code"):
        found = shutil.which(name)
        if found and "cursor" not in found.lower():
            return found
    return None

def _same_path(left: str, right: str) -> bool:
    try:
        return Path(left).resolve() == Path(right).resolve()
    except Exception:
        return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))

def _open_vscode_deep_link(code_exe: str, uri: str) -> None:
    # Do not pass vscode:// links as normal file args; VS Code will open them
    # as text editors like "vscode:/openai.chatgpt/..." instead of routing them
    # to the Codex extension URI handler.
    if os.name == "nt" and hasattr(os, "startfile"):
        os.startfile(uri)
        return
    subprocess.Popen([code_exe, "--open-url", uri])

def _open_codex_vscode_session(project_path: str, session_id: str) -> None:
    code_exe = _find_vscode_launcher()
    if not code_exe:
        raise FileNotFoundError("Visual Studio Code launcher not found.")

    project_dir = project_path if project_path and Path(project_path).exists() else ""
    use_new_window = bool(project_dir) and not _same_path(project_dir, os.getcwd())
    route_uri = f"vscode://openai.chatgpt/local/{quote(session_id)}"
    if use_new_window:
        subprocess.Popen([code_exe, "--new-window", project_dir])
        time.sleep(1.5)
        _open_vscode_deep_link(code_exe, route_uri)
        return

    # The Codex extension registers an onUri route handler at openai.chatgpt.
    # Same-folder sessions can reuse the current VS Code window safely.
    try:
        _open_vscode_deep_link(code_exe, route_uri)
        return
    except Exception:
        pass

    subprocess.Popen([code_exe, "--open-url", route_uri])

def _read_codex_model_from_rollout(injected_path: str) -> str:
    if not injected_path:
        return ""
    path = Path(injected_path)
    if not path.exists():
        return ""
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[:20]:
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("type") == "session_meta":
                payload = entry.get("payload", {})
                model = payload.get("model", "")
                return model if isinstance(model, str) else ""
    except Exception:
        return ""
    return ""

def _codex_terminal_command(session_id: str, injected_path: str = "") -> str:
    base = f"codex resume {session_id}"
    if os.name != "nt":
        return base

    model = _read_codex_model_from_rollout(injected_path)
    if not model:
        return base

    safe_model = _escape_powershell_literal(model)
    return (
        f"& codex resume {session_id}; "
        "if ($LASTEXITCODE -ne 0) { "
        "Write-Host 'Codex resume failed; retrying with the injected session model.' -ForegroundColor Yellow; "
        f"& codex -m '{safe_model}' resume {session_id} "
        "}"
    )

def clear_screen():
    print("\033[H\033[J", end="")

def print_header():
    clear_screen()
    title = Text("AiMem CLI - Memory Switcher", style="bold cyan", justify="center")
    subtitle = Text("Save, compress, and transfer context between AI agents", style="italic blue", justify="center")
    console.print(Panel(Text.assemble(title, "\n", subtitle), border_style="cyan", expand=False))
    print()

def get_available_agents(for_save=True):
    agents = []
    if ClaudeAdapter().is_available(): agents.append("claude")
    if GeminiAdapter().is_available(): agents.append("gemini")
    if QwenAdapter().is_available(): agents.append("qwen")
    if OpenCodeAdapter().is_available(): agents.append("opencode")
    if CodexAdapter().is_available(): agents.append("codex")
    if CursorAdapter().is_available(): agents.append("cursor")
    if AntigravityAdapter().is_available(): agents.append("antigravity")
    if for_save and AiderAdapter().is_available(): agents.append("aider")
    if for_save: agents.append("clipboard")
    return agents

def get_saved_sessions():
    sessions = FileStorage.list()
    choices = []
    for s in sessions:
        src = s.source.upper()
        msg_count = len(s.messages)
        ts = cli._format_timestamp(s.created_at)
        title = f"[{src}] {ts} ({msg_count} msgs)"
        if s.compressed and s.compressed.current_goal:
            title += f" - {s.compressed.current_goal[:40]}..."
        choices.append(questionary.Choice(title=title, value=s.id))
    return choices

def check_compression_config():
    config = load_config()
    compression = config.setdefault("compression", {})
    api_key = compression.get("api_key") or ""
    if not api_key:
        console.print("[yellow]Compression requires an API Key to use an LLM for summarizing context.[/yellow]")
        return configure_compression_config(force=True)
    provider = compression.get("provider") or "groq"
    if not compression.get("model"):
        compression["model"] = get_default_compression_model(provider)
        save_config(config)
    return True

def select_compression_model(provider: str, api_key: str | None, current_model: str | None = None) -> str | None:
    provider = provider.lower()
    console.print(f"[cyan]Loading {provider.capitalize()} compression models...[/cyan]")
    models = list_compression_models(provider, api_key)
    if not models:
        default_model = get_default_compression_model(provider)
        console.print(f"[yellow]Could not list models. Using default: {default_model}[/yellow]")
        return default_model

    choices = []
    default_value = current_model or get_default_compression_model(provider)
    seen = set()
    for model in models:
        model_id = model["id"]
        seen.add(model_id)
        label = model.get("label") or model_id
        note = model.get("note") or model.get("source") or ""
        title = f"{model_id} - {label}"
        if note:
            title += f" ({note})"
        choices.append(questionary.Choice(title, model_id))

    if default_value and default_value not in seen:
        choices.insert(0, questionary.Choice(f"{default_value} (current/custom)", default_value))
    choices.append(questionary.Separator())
    choices.append(questionary.Choice("Enter custom model ID", "custom"))
    choices.append(questionary.Choice("Back", "back"))

    selected = questionary.select(
        "Select compression model:",
        choices=choices,
        default=default_value if default_value in [choice.value for choice in choices if hasattr(choice, "value")] else None,
    ).ask()
    if not selected or selected == "back":
        return None
    if selected == "custom":
        custom = questionary.text("Enter model ID:", default=default_value).ask()
        return custom.strip() if custom else None
    return selected

def configure_compression_model(force: bool = False) -> bool:
    config = load_config()
    compression = config.setdefault("compression", {})
    provider = (compression.get("provider") or "groq").lower()
    api_key = compression.get("api_key") or ""
    if not api_key:
        return configure_compression_config(force=True)
    if not force and compression.get("model"):
        return True

    selected_model = select_compression_model(provider, api_key, compression.get("model"))
    if not selected_model:
        return False
    compression["model"] = selected_model
    save_config(config)
    console.print(f"[green]Compression model set to {selected_model}.[/green]")
    return True

def configure_compression_config(force: bool = False) -> bool:
    config = load_config()
    compression = config.setdefault("compression", {})
    current_provider = compression.get("provider") or "groq"
    current_key = compression.get("api_key") or ""

    if current_key and not force:
        if not compression.get("model"):
            compression["model"] = get_default_compression_model(current_provider)
            save_config(config)
        return True

    if current_key:
        masked = f"{current_key[:4]}...{current_key[-4:]}" if len(current_key) > 8 else "configured"
        console.print(f"[cyan]Current compression provider:[/cyan] {current_provider} ({masked})")

    setup = questionary.confirm("Do you want to set up or change the compression API key now?").ask()
    if not setup:
        return False

    provider = questionary.select(
        "Select compression provider:",
        choices=["gemini", "groq"],
        default=current_provider if current_provider in {"groq", "gemini"} else "gemini",
    ).ask()
    if not provider:
        return False

    prompt = f"Enter {provider.capitalize()} API Key"
    if current_key and provider == current_provider:
        prompt += " (leave blank to keep current)"
    prompt += ":"
    key = questionary.password(prompt).ask()
    if key is None:
        return False
    if not key and provider == current_provider and current_key:
        key = current_key
    if not key:
        console.print("[yellow]API key was not changed.[/yellow]")
        return False

    compression["provider"] = provider
    compression["api_key"] = key

    current_model = compression.get("model") if provider == current_provider else None
    if provider == "gemini" and current_model and not current_model.startswith(("gemini-", "gemma-")):
        current_model = None
    elif provider == "groq" and current_model and current_model.startswith(("gemini-", "gemma-")):
        current_model = None

    selected_model = select_compression_model(
        provider,
        key,
        current_model or get_default_compression_model(provider),
    )
    compression["model"] = selected_model or get_default_compression_model(provider)

    save_config(config)
    console.print(
        f"[green]Compression configured for {provider.capitalize()} "
        f"with {compression['model']}.[/green]"
    )
    return True

def recover_after_compression_failure(session_id: str, target: str) -> str | None:
    choices = [
        questionary.Choice("Change compression model and retry", "compression_model"),
        questionary.Choice("Change compression provider/API key/model and retry", "provider"),
        questionary.Choice("Chunk / show split parts instead", "chunk"),
    ]
    if target == "opencode":
        choices.append(questionary.Choice("Change OpenCode model", "model"))
    choices.append(questionary.Choice("Back", "back"))

    choice = questionary.select(
        "Compression failed or injection was cancelled. What do you want to do?",
        choices=choices,
    ).ask()

    if choice == "compression_model":
        return "retry" if configure_compression_model(force=True) else None
    if choice == "provider":
        return "retry" if configure_compression_config(force=True) else None
    if choice == "chunk":
        show_chunk_menu(session_id, target)
        return "done"
    if choice == "model":
        model = select_opencode_model()
        if not model:
            return None
        session = FileStorage.load(session_id)
        status = OpenCodeAdapter().injection_context_status(session, model=model)
        if status["will_fit"]:
            return f"model:{model}"
        console.print("[yellow]That OpenCode model is still too small for the raw session.[/yellow]")
        console.print(
            f"  Model: {status['provider_id']}/{status['model_id']} | "
            f"Input: ~{status['estimated_tokens']:,} tokens | "
            f"Budget: ~{status['budget']:,} tokens"
        )
        return None
    return None

def select_opencode_model() -> str | None:
    adapter = OpenCodeAdapter()
    console.print("[cyan]Loading OpenCode models from this machine...[/cyan]")
    models = adapter.list_models()
    if not models:
        console.print("[yellow]No OpenCode models found locally.[/yellow]")
        return None

    choices = []
    for model in models:
        source = model.get("source", "opencode")
        label = model.get("label") or model.get("value")
        choices.append(questionary.Choice(f"{label} ({source})", model["value"]))
    choices.append(questionary.Separator())
    choices.append(questionary.Choice("Back", "back"))

    selected = questionary.select("Select OpenCode model:", choices=choices).ask()
    if not selected or selected == "back":
        return None
    return selected

def _select_chunk_index(result, prompt: str) -> int | None:
    choices = []
    for index, token_count in enumerate(result.chunk_token_counts, 1):
        messages = result.messages_per_chunk[index - 1]
        choices.append(questionary.Choice(
            f"Chunk {index}/{len(result.chunks)} - ~{token_count:,} tokens, {messages} messages",
            index - 1,
        ))
    choices.append(questionary.Separator())
    choices.append(questionary.Choice("Back", "back"))

    selected = questionary.select(prompt, choices=choices).ask()
    if selected is None or selected == "back":
        return None
    return int(selected)

def _copy_to_clipboard(text: str) -> bool:
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except Exception as exc:
        console.print(f"[red]Could not copy to clipboard: {exc}[/red]")
        return False

def _chunk_as_session(
    session: UniversalSession,
    messages,
    index: int,
    total: int,
    target: str,
) -> UniversalSession:
    chunked = deepcopy(session)
    chunked.id = f"{session.id}-chunk-{index + 1:02d}"
    chunked.messages = list(messages)
    chunked.compressed = None
    chunked.tags = list(dict.fromkeys([*session.tags, "chunked", f"chunk-{index + 1}-of-{total}"]))
    chunked.note = f"{session.note or 'AiMem chunk'} (chunk {index + 1}/{total} for {target})"
    return chunked

def _inject_chunk_session(chunked: UniversalSession, target: str, opencode_model: str | None = None) -> dict | None:
    inject_targets = {
        "claude": ClaudeAdapter,
        "gemini": GeminiAdapter,
        "qwen": QwenAdapter,
        "codex": CodexAdapter,
        "opencode": OpenCodeAdapter,
        "cursor": CursorAdapter,
    }
    adapter_cls = inject_targets.get(target)
    if not adapter_cls:
        console.print(f"[yellow]Direct inject is not supported for {target} chunks.[/yellow]")
        return None

    adapter = adapter_cls()
    if not adapter.is_available():
        console.print(f"[red]{target.capitalize()} storage is not available.[/red]")
        return None

    if target == "opencode":
        injected_path = adapter.inject(chunked, model=opencode_model)
    else:
        injected_path = adapter.inject(chunked)

    injected_id = cli._extract_injected_session_id(target, injected_path)
    console.print(f"[green]Injected chunk into {target}: {injected_id}[/green]")
    return {
        "target": target,
        "injected_session_id": injected_id,
        "project_path": chunked.metadata.project_path,
    }

def show_chunk_menu(session_id: str, target: str, opencode_model: str | None = None) -> None:
    try:
        session = FileStorage.load(session_id)
    except FileNotFoundError:
        console.print(f"[red]Session not found: {session_id}[/red]")
        return

    model_for_context = opencode_model
    if target == "opencode" and not model_for_context:
        status = OpenCodeAdapter().injection_context_status(session)
        model_for_context = f"{status['provider_id']}/{status['model_id']}"

    advice = get_load_advice(session, target, model=model_for_context if target == "opencode" else None)
    result = chunk_session(session, target, model=model_for_context if target == "opencode" else None)

    if not result.chunks:
        console.print("[yellow]No chunk content was generated.[/yellow]")
        return

    while True:
        console.print()
        console.print(Panel(
            "\n".join([
                f"Target: {target}",
                f"Model/context profile: {advice.target_model}",
                f"Original: ~{result.original_tokens:,} tokens, {len(session.messages)} messages",
                f"Chunks: {len(result.chunks)}",
                f"Budget per chunk: ~{advice.limit.recommended_input:,} tokens",
                f"Dropped messages: {result.dropped_messages}",
            ]),
            title="AiMem Chunk Result",
            border_style="cyan",
        ))

        choices = [
            questionary.Choice("Preview a chunk", "preview"),
            questionary.Choice("Copy a chunk to clipboard", "copy_one"),
            questionary.Choice("Copy all chunks to clipboard", "copy_all"),
            questionary.Choice("Save chunks as AiMem sessions", "save"),
        ]
        if target in {"claude", "gemini", "qwen", "codex", "opencode", "cursor"}:
            choices.append(questionary.Choice("Inject one chunk into target agent", "inject_one"))
        choices.extend([
            questionary.Separator(),
            questionary.Choice("Back", "back"),
        ])

        action = questionary.select("What do you want to do with these chunks?", choices=choices).ask()
        if not action or action == "back":
            return

        if action == "preview":
            index = _select_chunk_index(result, "Select chunk to preview:")
            if index is None:
                continue
            preview = result.chunks[index]
            if len(preview) > 8_000:
                preview = preview[:8_000] + "\n\n[... preview truncated in TUI ...]"
            console.print(Panel(preview, title=f"Chunk {index + 1}/{len(result.chunks)}", border_style="blue"))
            questionary.press_any_key_to_continue("Press any key to continue...").ask()

        elif action == "copy_one":
            index = _select_chunk_index(result, "Select chunk to copy:")
            if index is not None and _copy_to_clipboard(result.chunks[index]):
                console.print(f"[green]Copied chunk {index + 1}/{len(result.chunks)} to clipboard.[/green]")

        elif action == "copy_all":
            joined = "\n\n".join(
                f"===== AIMEM CHUNK {index}/{len(result.chunks)} =====\n{chunk}"
                for index, chunk in enumerate(result.chunks, 1)
            )
            if _copy_to_clipboard(joined):
                console.print("[green]Copied all chunks to clipboard.[/green]")

        elif action == "save":
            saved_ids = []
            for index, messages in enumerate(result.chunk_messages):
                chunked = _chunk_as_session(session, messages, index, len(result.chunks), target)
                FileStorage.save(chunked)
                saved_ids.append(chunked.id)
            console.print(f"[green]Saved {len(saved_ids)} chunk session(s).[/green]")
            console.print(", ".join(saved_ids))

        elif action == "inject_one":
            index = _select_chunk_index(result, "Select chunk to inject:")
            if index is None:
                continue
            chunked = _chunk_as_session(
                session,
                result.chunk_messages[index],
                index,
                len(result.chunks),
                target,
            )
            _inject_chunk_session(chunked, target, opencode_model=model_for_context if target == "opencode" else None)

def choose_oversize_action(session_id: str, target: str) -> str | None:
    try:
        session = FileStorage.load(session_id)
    except FileNotFoundError:
        console.print(f"[red]Session not found: {session_id}[/red]")
        return None

    if session.compressed:
        return "inject"

    if target == "opencode":
        adapter = OpenCodeAdapter()
        selected_model: str | None = None

        while True:
            status = adapter.injection_context_status(session, model=selected_model)
            if status["will_fit"]:
                if selected_model:
                    console.print(
                        f"[green]Selected OpenCode model fits:[/green] "
                        f"{status['provider_id']}/{status['model_id']}"
                    )
                    return f"model:{selected_model}"
                return "inject"

            console.print("[yellow]This session is too large for the selected OpenCode model.[/yellow]")
            console.print(
                f"  Model: {status['provider_id']}/{status['model_id']} | "
                f"Input: ~{status['estimated_tokens']:,} tokens | "
                f"Budget: ~{status['budget']:,} tokens"
            )

            choice = questionary.select(
                "Choose how to continue:",
                choices=[
                    questionary.Choice("Change OpenCode model", "model"),
                    questionary.Choice("Change compression model and inject", "compression_model"),
                    questionary.Choice("Compress and inject", "compress"),
                    questionary.Choice("Chunk / show split parts", "chunk"),
                    questionary.Choice("Back", "back"),
                ],
            ).ask()

            if choice == "model":
                new_model = select_opencode_model()
                if new_model:
                    selected_model = new_model
                continue
            if choice == "compression_model":
                return "compress" if configure_compression_model(force=True) else None
            if choice == "chunk":
                return f"chunk:{selected_model}" if selected_model else "chunk"
            return choice
    else:
        advice = get_load_advice(session, target)
        if advice.will_fit:
            return "inject"

        console.print("[yellow]This session is too large for the target agent.[/yellow]")
        console.print(
            f"  Target: {advice.target_model} | "
            f"Input: ~{advice.session_tokens:,} tokens | "
            f"Recommended: ~{advice.limit.recommended_input:,} tokens"
        )

    choice = questionary.select(
        "Choose how to continue:",
        choices=[
            questionary.Choice("Change compression model and inject", "compression_model"),
            questionary.Choice("Compress and inject", "compress"),
            questionary.Choice("Chunk / show split parts", "chunk"),
            questionary.Choice("Back", "back"),
        ],
    ).ask()
    if choice == "compression_model":
        return "compress" if configure_compression_model(force=True) else None
    return choice

def menu_save():
    agents = get_available_agents(for_save=True)
    if not agents:
        console.print("[red]No agents found![/red]")
        return

    choices = [questionary.Choice(a.capitalize(), a) for a in agents]
    choices.append(questionary.Separator())
    choices.append(questionary.Choice("🔙 Back to Main Menu", "back"))

    source = questionary.select(
        "Select source agent to save from:",
        choices=choices
    ).ask()

    if not source or source == "back": return

    config = load_config()
    comp_enabled = config.get("compression", {}).get("enabled", False)
    
    compress = False
    if comp_enabled:
        compress = questionary.confirm("Compress this session to save tokens?").ask()
        if compress:
            if not check_compression_config():
                console.print("[yellow]Compression disabled.[/yellow]")
                compress = False

    # Build args and run
    args = ["save", "--from", source]
    if compress:
        args.append("--compress")
    elif comp_enabled:
        args.append("--no-compress")
    cli.main(args)

def menu_load():
    sessions = get_saved_sessions()
    if not sessions:
        console.print("[yellow]No saved sessions found. Run 'Save Session' first.[/yellow]")
        return

    sessions.append(questionary.Separator())
    sessions.append(questionary.Choice("🔙 Back to Main Menu", "back"))

    session_id = questionary.select(
        "Select a session to load:",
        choices=sessions
    ).ask()

    if not session_id or session_id == "back": return

    action = questionary.select(
        "What do you want to do with this session?",
        choices=[
            questionary.Choice("💉 Inject directly into another Agent", "inject"),
            questionary.Choice("📋 Copy to clipboard (Markdown)", "clipboard"),
            questionary.Choice("📊 Analyze context size", "analyze"),
            questionary.Choice("✂️  Chunk (Split into parts)", "chunk"),
            questionary.Separator(),
            questionary.Choice("🔙 Back to Main Menu", "back"),
        ]
    ).ask()

    if not action or action == "back": return

    if action == "inject":
        agents = get_available_agents(for_save=False)
        choices = [questionary.Choice(a.capitalize(), a) for a in agents]
        choices.append(questionary.Separator())
        choices.append(questionary.Choice("🔙 Back to Main Menu", "back"))
        
        target = questionary.select("Select target agent:", choices=choices).ask()
        if not target or target == "back": return

        oversize_action = choose_oversize_action(session_id, target)
        if not oversize_action or oversize_action == "back":
            return
        opencode_model = None
        if oversize_action.startswith("model:"):
            opencode_model = oversize_action.split(":", 1)[1]
            oversize_action = "inject"
        chunk_model = None
        if oversize_action.startswith("chunk:"):
            chunk_model = oversize_action.split(":", 1)[1]
            oversize_action = "chunk"
        if oversize_action == "chunk":
            show_chunk_menu(session_id, target, opencode_model=chunk_model)
            return
        
        config = load_config()
        comp_enabled = config.get("compression", {}).get("enabled", False)
        
        compress = oversize_action == "compress"
        if compress:
            if not check_compression_config():
                console.print("[yellow]Compression disabled.[/yellow]")
                return
        elif comp_enabled and not opencode_model:
            compress = questionary.confirm("Compress before injecting?").ask()
            if compress:
                if not check_compression_config():
                    console.print("[yellow]Compression disabled.[/yellow]")
                    compress = False
                    
        while True:
            args = ["load", session_id, "--to", target, "--inject"]
            if opencode_model:
                args.extend(["--opencode-model", opencode_model])
            if compress:
                args.append("--compress")
            elif comp_enabled:
                args.append("--no-compress")

            result = cli.main(args, return_result=True)
            if result and isinstance(result, dict) and "injected_session_id" in result:
                break

            if not compress:
                return

            recovery = recover_after_compression_failure(session_id, target)
            if recovery == "retry":
                compress = True
                continue
            if recovery and recovery.startswith("model:"):
                opencode_model = recovery.split(":", 1)[1]
                compress = False
                continue
            return
        
        if result and isinstance(result, dict) and "injected_session_id" in result:
            target_agent = result["target"]
            new_id = result["injected_session_id"]
            proj_path = result.get("project_path", "")
            injected_path = result.get("injected_path", "")
            
            if questionary.confirm(f"Do you want to open/resume this session now in {target_agent.capitalize()}?").ask():
                # Build the command based on target
                cmd = ""
                if target_agent == "opencode":
                    cmd = f"opencode -s {new_id}"
                elif target_agent == "claude":
                    cmd = f"claude --resume {new_id}"
                elif target_agent == "gemini":
                    cmd = f"gemini --resume {new_id}"
                elif target_agent == "qwen":
                    cmd = f"qwen --resume {new_id}"
                elif target_agent == "codex":
                    choice = questionary.select(
                        "How do you want to resume this Codex session?",
                        choices=["💻 In Terminal (CLI)", "📝 In VS Code Extension"]
                    ).ask()
                    
                    if choice == "💻 In Terminal (CLI)":
                        cmd = _codex_terminal_command(new_id, injected_path)
                    elif choice == "📝 In VS Code Extension":
                        console.print("[green]Launching VS Code Codex session...[/green]")
                        try:
                            _open_codex_vscode_session(proj_path, new_id)
                        except Exception as e:
                            console.print(f"[red]Failed to launch VS Code Codex session: {e}[/red]")
                        cmd = ""
                elif target_agent == "cursor":
                    # Launch Cursor IDE directly since it's a GUI app, not a CLI
                    console.print("[green]Launching Cursor IDE... Check your Composer history![/green]")
                    import shutil
                    if os.name == "nt":
                        cursor_exe = shutil.which("cursor.cmd") or shutil.which("cursor.exe") or "cursor"
                        try:
                            CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)
                            if proj_path:
                                subprocess.Popen([cursor_exe, proj_path], shell=False, creationflags=CREATE_NO_WINDOW)
                            else:
                                subprocess.Popen([cursor_exe], shell=False, creationflags=CREATE_NO_WINDOW)
                        except Exception as e:
                            console.print(f"[red]Failed to launch Cursor: {e}[/red]")
                    else:
                        import subprocess
                        cursor_exe = shutil.which("cursor") or "cursor"
                        try:
                            if proj_path:
                                subprocess.Popen([cursor_exe, proj_path])
                            else:
                                subprocess.Popen([cursor_exe])
                        except Exception as e:
                            console.print(f"[red]Failed to launch Cursor: {e}[/red]")
                    # Leave cmd empty so it doesn't open a powershell terminal
                    cmd = ""
                
                if cmd:
                    if os.name == "nt":
                        _launch_windows_terminal(cmd, proj_path)
                    else:
                        console.print(f"[yellow]Auto-opening is currently supported best on Windows. Please run:[/yellow] {cmd}")
    elif action == "clipboard":
        config = load_config()
        comp_enabled = config.get("compression", {}).get("enabled", False)
        
        compress = False
        if comp_enabled:
            compress = questionary.confirm("Compress before copying?").ask()
            if compress:
                if not check_compression_config():
                    console.print("[yellow]Compression disabled.[/yellow]")
                    compress = False

        args = ["load", session_id, "--to", "markdown", "--copy"]
        if compress:
            args.append("--compress")
        elif comp_enabled:
            args.append("--no-compress")
        cli.main(args)
    elif action == "analyze":
        agents = get_available_agents(for_save=False)
        choices = [questionary.Choice(a.capitalize(), a) for a in agents]
        choices.append(questionary.Separator())
        choices.append(questionary.Choice("🔙 Back to Main Menu", "back"))
        target = questionary.select("Select target agent to analyze for:", choices=choices).ask()
        if not target or target == "back": return
        cli.main(["load", session_id, "--to", target, "--analyze"])
    elif action == "chunk":
        agents = get_available_agents(for_save=False)
        choices = [questionary.Choice(a.capitalize(), a) for a in agents]
        choices.append(questionary.Separator())
        choices.append(questionary.Choice("🔙 Back to Main Menu", "back"))
        target = questionary.select("Select target agent to chunk for:", choices=choices).ask()
        if not target or target == "back": return
        opencode_model = select_opencode_model() if target == "opencode" else None
        show_chunk_menu(session_id, target, opencode_model=opencode_model)

def menu_list():
    choice = questionary.select(
        "What do you want to list?",
        choices=[
            questionary.Choice("Saved AiMem Sessions", "saved"),
            questionary.Choice("Available Agent Sessions (Local)", "agents"),
            questionary.Separator(),
            questionary.Choice("🔙 Back to Main Menu", "back"),
        ]
    ).ask()

    if not choice or choice == "back": return

    if choice == "saved":
        cli.main(["list"])
    elif choice == "agents":
        cli.main(["list", "--agents"])

def menu_merge():
    sessions = get_saved_sessions()
    if not sessions or len(sessions) < 2:
        console.print("[yellow]Need at least 2 saved sessions to merge.[/yellow]")
        return
        
    selected_sessions = questionary.checkbox(
        "Select sessions to merge (Space to select, Enter to confirm):",
        choices=sessions
    ).ask()

    if not selected_sessions or len(selected_sessions) < 2:
        console.print("[yellow]Merge cancelled or not enough sessions selected.[/yellow]")
        return
        
    smart = questionary.confirm("Use Smart Merge (deduplicate, combine goals/todos)?").ask()
    
    agents = get_available_agents(for_save=False) + ["markdown"]
    choices = [questionary.Choice(a.capitalize(), a) for a in agents]
    target = questionary.select("Select target format for sizing/formatting:", choices=choices).ask()
    
    args = ["merge"] + selected_sessions
    if smart:
        args.append("--smart")
    if target:
        args.extend(["--to", target])
        
    cli.main(args)

def menu_delete():
    sessions = get_saved_sessions()
    if not sessions:
        console.print("[yellow]No saved sessions to delete.[/yellow]")
        return

    selected_sessions = questionary.checkbox(
        "Select sessions to delete (Space to select, Enter to confirm):",
        choices=sessions
    ).ask()

    if not selected_sessions:
        return
    
    confirm = questionary.confirm(f"Are you sure you want to delete {len(selected_sessions)} session(s)?").ask()
    if confirm:
        for session_id in selected_sessions:
            cli.main(["delete", session_id])

def menu_settings():
    while True:
        config = load_config()
        
        comp_config = config.get("compression", {})
        provider = comp_config.get("provider") or "groq"
        api_key = comp_config.get("api_key") or ""
        comp_model = comp_config.get("model") or get_default_compression_model(provider)
        comp_enabled = comp_config.get("enabled") or False
        
        out_config = config.get("output", {})
        out_format = out_config.get("format") or "markdown"
        clipboard_auto = out_config.get("clipboard_auto") or False
        
        store_config = config.get("storage", {})
        store_path = store_config.get("path") or "~/.aimem/sessions"
        
        masked_key = f"{api_key[:4]}...{api_key[-4:]}" if api_key and len(api_key) > 8 else (api_key if api_key else "Not set")
        
        choice = questionary.select(
            "⚙️ Settings:",
            choices=[
                questionary.Choice(f"[{'On' if comp_enabled else 'Off'}] Enable Compression", "comp_enabled"),
                questionary.Choice(f"🔑 API Key: {masked_key}", "api_key"),
                questionary.Choice(f"🧠 Provider: {provider.capitalize()}", "provider"),
                questionary.Choice(f"Compression Model: {comp_model}", "comp_model"),
                questionary.Separator(),
                questionary.Choice(f"[{'On' if clipboard_auto else 'Off'}] Auto-copy to Clipboard", "clipboard_auto"),
                questionary.Choice(f"📄 Default Output Format: {out_format}", "out_format"),
                questionary.Separator(),
                questionary.Choice(f"📁 Storage Path: {store_path}", "store_path"),
                questionary.Separator(),
                questionary.Choice("🔙 Back to Main Menu", "back"),
            ]
        ).ask()
        
        if not choice or choice == "back":
            break
            
        if choice == "api_key":
            configure_compression_config(force=True)
        elif choice == "provider":
            configure_compression_config(force=True)
        elif choice == "comp_model":
            configure_compression_model(force=True)
        elif choice == "comp_enabled":
            new_val = not comp_enabled
            cli.main(["config", "set", f"compression.enabled={str(new_val).lower()}"])
            console.print(f"[green]Compression auto-run is now {'ON' if new_val else 'OFF'}.[/green]")
        elif choice == "clipboard_auto":
            new_val = not clipboard_auto
            cli.main(["config", "set", f"output.clipboard_auto={str(new_val).lower()}"])
            console.print(f"[green]Auto-copy to clipboard is now {'ON' if new_val else 'OFF'}.[/green]")
        elif choice == "out_format":
            formats = ["markdown", "claude", "gemini", "qwen", "codex", "opencode", "prompt", "continue"]
            new_fmt = questionary.select("Select Default Output Format:", choices=formats, default=out_format).ask()
            if new_fmt:
                cli.main(["config", "set", f"output.format={new_fmt}"])
                console.print(f"[green]Default output format updated to {new_fmt}![/green]")
        elif choice == "store_path":
            new_path = questionary.text("Enter new storage path:", default=store_path).ask()
            if new_path:
                cli.main(["config", "set", f"storage.path={new_path}"])
                console.print(f"[green]Storage path updated to {new_path}![/green]")

def run_tui():
    while True:
        print_header()
        
        action = questionary.select(
            "What would you like to do?",
            choices=[
                questionary.Choice("💾 Save Session (Extract from Agent)", "save"),
                questionary.Choice("🔄 Load/Inject Session (Transfer to Agent)", "load"),
                questionary.Choice("🔀 Merge Sessions", "merge"),
                questionary.Choice("📋 List Sessions", "list"),
                questionary.Choice("🗑️  Delete Session", "delete"),
                questionary.Choice("⚙️  Settings", "settings"),
                questionary.Separator(),
                questionary.Choice("❌ Exit", "exit"),
            ]
        ).ask()

        if action == "exit" or not action:
            console.print("[dim]Goodbye![/dim]")
            break
        
        print()
        try:
            if action == "save":
                menu_save()
            elif action == "load":
                menu_load()
            elif action == "merge":
                menu_merge()
            elif action == "list":
                menu_list()
            elif action == "delete":
                menu_delete()
            elif action == "settings":
                menu_settings()
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
        
        print()
        questionary.press_any_key_to_continue("Press any key to return to main menu...").ask()
