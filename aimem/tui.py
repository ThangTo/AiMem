import sys
import argparse
from pathlib import Path
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

console = Console()

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
    api_key = config.get("compression", {}).get("api_key", "")
    if not api_key:
        console.print("[yellow]Compression requires an API Key to use an LLM for summarizing context.[/yellow]")
        setup = questionary.confirm("Do you want to set up an API Key now?").ask()
        if setup:
            provider = questionary.select("Select Provider:", choices=["groq", "gemini"], default="groq").ask()
            if not provider: return False
            key = questionary.password(f"Enter {provider.capitalize()} API Key:").ask()
            if not key: return False
            
            cli.main(["config", "set", "compression.enabled=true"])
            cli.main(["config", "set", f"compression.provider={provider}"])
            cli.main(["config", "set", f"compression.api_key={key}"])
            console.print("[green]API Key configured successfully![/green]")
            return True
        return False
    return True

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
        
        config = load_config()
        comp_enabled = config.get("compression", {}).get("enabled", False)
        
        compress = False
        if comp_enabled:
            compress = questionary.confirm("Compress before injecting?").ask()
            if compress:
                if not check_compression_config():
                    console.print("[yellow]Compression disabled.[/yellow]")
                    compress = False
                    
        args = ["load", session_id, "--to", target, "--inject"]
        if compress:
            args.append("--compress")
            
        result = cli.main(args)
        
        if result and isinstance(result, dict) and "injected_session_id" in result:
            target_agent = result["target"]
            new_id = result["injected_session_id"]
            proj_path = result.get("project_path", "")
            
            if questionary.confirm(f"Do you want to open/resume this session now in {target_agent.capitalize()}?").ask():
                import subprocess
                import os
                
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
                        if os.name == "nt":
                            cmd = f"Write-Host 'Codex CLI requires the prompt in the command.' -ForegroundColor Yellow; Write-Host 'To resume, type:' -ForegroundColor Cyan; Write-Host 'codex exec resume {new_id} ''Your prompt here''' -ForegroundColor Green"
                        else:
                            cmd = f"echo 'Codex CLI requires the prompt in the command.'; echo 'To resume, type:'; echo 'codex exec resume {new_id} \"Your prompt here\"'"
                    elif choice == "📝 In VS Code Extension":
                        console.print("[green]Launching VS Code... Open the Codex extension sidebar to view the session![/green]")
                        import os
                        if os.name == "nt":
                            try:
                                if proj_path:
                                    # Use os.system with code command to let CMD resolve code.cmd and handle IPC correctly
                                    os.system(f'code "{proj_path}"')
                                else:
                                    os.system('code')
                            except Exception as e:
                                console.print(f"[red]Failed to launch VS Code: {e}[/red]")
                        else:
                            import shutil
                            import subprocess
                            code_exe = shutil.which("code") or "code"
                            try:
                                if proj_path:
                                    subprocess.Popen([code_exe, proj_path])
                                else:
                                    subprocess.Popen([code_exe])
                            except Exception as e:
                                console.print(f"[red]Failed to launch VS Code: {e}[/red]")
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
                        import shutil
                        import subprocess
                        # Use Windows Terminal if available, else fallback to powershell
                        has_wt = shutil.which("wt")
                        
                        if has_wt:
                            if proj_path:
                                subprocess.Popen(f'wt -d "{proj_path}" powershell -NoExit -Command "{cmd}"', shell=True)
                            else:
                                subprocess.Popen(f'wt powershell -NoExit -Command "{cmd}"', shell=True)
                        else:
                            # Fallback to standard PowerShell in a new window
                            if proj_path:
                                safe_path = proj_path.replace("'", "''")
                                ps_cmd = f"Set-Location -LiteralPath '{safe_path}'; {cmd}"
                                # Use start "" to prevent cmd from treating the first quoted string as window title
                                subprocess.Popen(f'start "" powershell -NoExit -Command "{ps_cmd}"', shell=True)
                            else:
                                subprocess.Popen(f'start "" powershell -NoExit -Command "{cmd}"', shell=True)
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
        if compress: args.append("--compress")
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
        cli.main(["load", session_id, "--to", target, "--chunk"])

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
            new_key = questionary.password("Enter new API Key:").ask()
            if new_key is not None:
                cli.main(["config", "set", f"compression.api_key={new_key}"])
                if new_key: cli.main(["config", "set", "compression.enabled=true"])
                console.print("[green]API Key updated successfully![/green]")
        elif choice == "provider":
            new_prov = questionary.select("Select Provider:", choices=["groq", "gemini"]).ask()
            if new_prov:
                cli.main(["config", "set", f"compression.provider={new_prov}"])
                console.print(f"[green]Provider updated to {new_prov.capitalize()}![/green]")
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
