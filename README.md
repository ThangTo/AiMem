# 🧠 AiMem — AI Memory Switcher

> Transfer context seamlessly between AI agents (Claude, Gemini, Qwen, OpenCode, Codex...)

When Claude hits rate-limits or you need to switch to another AI, AiMem helps you continue without losing your train of thought.

---

## 🚀 Install

```bash
pip install aimem-cli
```

Or from source:

```bash
git clone https://github.com/ThangTo/AiMem.git
cd AiMem
pip install -e .
```

---

## ⚡ Quick Start

### Save a session from Claude:
```bash
aimem-cli save --from claude
```

### Load into another agent:
```bash
# Load as Markdown (copy to clipboard)
aimem-cli load <session-id> --to markdown

# Inject directly into OpenCode
aimem-cli load <session-id> --to opencode --inject
opencode -s <session-id-from-output>
```

---

## 📖 Usage Examples

### 1. Transfer from Claude to OpenCode (Recommended)
```bash
# Save Claude session
aimem-cli save --from claude

# Inject directly into OpenCode
aimem-cli load claude-xxxxx --to opencode --inject

# Open the session in OpenCode
opencode -s ses_xxxxx
```

### 2. Transfer from Claude to Gemini
```bash
# Save Claude session
aimem-cli save --from claude

# Load as Gemini format (auto-copied to clipboard)
aimem-cli load claude-xxxxx --to gemini

# Paste into Gemini CLI
gemini "paste the context here"
```

### 3. Transfer to Claude
```bash
# Load session into Claude (inject directly)
aimem-cli load <session-id> --to claude --inject

# Resume in Claude
claude --resume
```

---

## 📋 Commands

| Command | Description |
|---------|-------------|
| `aimem-cli save --from <agent>` | Save session from an agent |
| `aimem-cli load <id> --to <format>` | Load session to target format |
| `aimem-cli load <id> --to <agent> --inject` | Inject directly into agent storage |
| `aimem-cli list` | List saved sessions |
| `aimem-cli list <agent>` | List sessions from specific agent |
| `aimem-cli delete <id>` | Delete a saved session |

---

## 🔧 Supported Agents

### Source (`--from`)

| Agent | Storage Location | Inject? |
|-------|-----------------|---------|
| `claude` | `~/.claude/projects/*/*.jsonl` | ✅ |
| `gemini` | `~/.gemini/tmp/*/chats/*.json` | ✅ |
| `qwen` | `~/.qwen/tmp/*/logs.json` | ✅ |
| `opencode` | `~/.opencode/sessions/*.json` | ✅ |
| `codex` | `~/.codex/sessions/*.jsonl` | ✅ |
| `aider` | `~/.aider.chat.history.md` | ❌ |
| `continue` | `~/.continue/sessions.db` | ❌ |
| `clipboard` | System clipboard | ❌ |

### Target (`--to`)

| Format | Best for | Inject? |
|--------|---------|---------|
| `markdown` | Paste anywhere | ❌ |
| `claude` | Claude Code CLI | ✅ |
| `gemini` | Gemini CLI | ✅ |
| `qwen` | Qwen CLI | ✅ |
| `opencode` | OpenCode CLI | ✅ |
| `codex` | Codex CLI | ✅ |
| `prompt` | Custom injection | ❌ |

---

## ⚙️ Configuration

Config file: `~/.aimem/config.json`

```bash
# Show config
aimem-cli config

# Enable LLM compression (opt-in)
aimem-cli config set compression.enabled true
aimem-cli config set compression.api_key YOUR_GROQ_KEY

# Auto-copy to clipboard
aimem-cli config set output.clipboard_auto true
```

---

## 🏗️ Architecture

```
aimem-cli/
├── adapters/           # Read from different agents
│   ├── claude.py      # Claude Code
│   ├── gemini.py      # Gemini CLI
│   ├── opencode.py    # OpenCode
│   └── ...
├── storage.py         # Save/load sessions
├── compression.py     # LLM compression (opt-in)
└── cli.py             # Command-line interface
```

---

## 📝 Examples

### Save from Claude
```bash
$ aimem-cli save --from claude
[i] Found 5 Claude sessions. Select one:
  [1] 2026-04-20 | Fix bug in auth module
  [2] 2026-04-19 | Add user login feature
  [3] 2026-04-18 | Research API design
Enter number (default=1): 1
[OK] Saved session: claude-abc123
```

### Load to OpenCode with inject
```bash
$ aimem-cli load claude-abc123 --to opencode --inject
[OK] Injected into OpenCode
Resume with: opencode -s ses_xyz789
```

---

## License

MIT
