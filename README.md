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

### Transfer from Claude to OpenCode (Recommended)
```bash
# Save current Claude session
aimem-cli save --from claude

# Inject directly into OpenCode
aimem-cli load <session-id> --to opencode --inject

# Open the session in OpenCode
opencode -s <session-id-from-output>
```

### Transfer to Markdown (for any AI)
```bash
aimem-cli save --from claude
aimem-cli load <session-id> --to markdown
# Content copied to clipboard - paste anywhere
```

---

## 📖 All Commands

### `aimem-cli init`
Initialize config file at `~/.aimem/config.json`.

```bash
aimem-cli init
aimem-cli init --force    # Overwrite existing config
```

---

### `aimem-cli save --from <agent>`
Save a session from an agent to AiMem storage.

```bash
# From Claude
aimem-cli save --from claude
aimem-cli save --from claude --session-id <id>

# From Gemini
aimem-cli save --from gemini

# From Qwen
aimem-cli save --from qwen

# From OpenCode
aimem-cli save --from opencode

# From Codex
aimem-cli save --from codex

# From Aider
aimem-cli save --from aider

# From Continue.dev
aimem-cli save --from continue

# From Clipboard
aimem-cli save --from clipboard

# With LLM compression (requires API key)
aimem-cli save --from claude --compress
```

---

### `aimem-cli load <session-id> --to <format>`
Load a saved session to target format.

```bash
# To Markdown (copy to clipboard)
aimem-cli load <session-id> --to markdown

# To Claude (markdown format)
aimem-cli load <session-id> --to claude

# To Gemini
aimem-cli load <session-id> --to gemini

# To Qwen
aimem-cli load <session-id> --to qwen

# To Prompt (for API calls)
aimem-cli load <session-id> --to prompt

# To OpenCode
aimem-cli load <session-id> --to opencode

# To Codex
aimem-cli load <session-id> --to codex

# To Continue.dev
aimem-cli load <session-id> --to continue
```

---

### `aimem-cli load <session-id> --to <agent> --inject`
**Inject directly into agent storage** - no copy-paste needed!

```bash
# Inject into OpenCode (RECOMMENDED)
aimem-cli load <session-id> --to opencode --inject
opencode -s <session-id>

# Inject into Claude
aimem-cli load <session-id> --to claude --inject
claude --resume

# Inject into Gemini
aimem-cli load <session-id> --to gemini --inject

# Inject into Qwen
aimem-cli load <session-id> --to qwen --inject

# Inject into Codex
aimem-cli load <session-id> --to codex --inject
```

---

### `aimem-cli list`
List all saved sessions.

```bash
# List all saved sessions
aimem-cli list

# List sessions from specific agent
aimem-cli list --from claude
aimem-cli list --from gemini
aimem-cli list --from qwen

# List available agents
aimem-cli list --agents
```

---

### `aimem-cli merge <session-id-1> <session-id-2>`
Merge multiple sessions into one.

```bash
# Simple merge (concatenate)
aimem-cli merge sess-abc sess-def

# Smart merge (deduplicate, combine goals, merge todos)
aimem-cli merge sess-abc sess-def --smart

# Smart merge with target format
aimem-cli merge sess-abc sess-def --smart --to gemini
```

---

### `aimem-cli config`
View or update configuration.

```bash
# Show current config
aimem-cli config

# Set config values
aimem-cli config set compression.enabled true
aimem-cli config set compression.api_key YOUR_API_KEY
aimem-cli config set compression.provider groq
aimem-cli config set output.format markdown
aimem-cli config set output.clipboard_auto true
```

---

### `aimem-cli delete <session-id>`
Delete a saved session.

```bash
aimem-cli delete <session-id>
```

---

### Analyze context before loading

Check if a session fits in target model's context limit.

```bash
# Analyze if session fits in Qwen's 32K context
aimem-cli load <session-id> --to qwen --analyze

# Output example:
# ⚠️ Session EXCEEDS Qwen limit (50K tokens vs 32K limit)
# 💡 Try: aimem load <session-id> --to qwen --chunk
```

---

### Chunk large sessions

Automatically split session into smaller chunks if too large for target.

```bash
# Auto-chunk for Qwen (32K limit)
aimem-cli load <session-id> --to qwen --chunk

# Output:
# 📦 CHUNK 1/2 (25K tokens)
# [content of chunk 1]
# ─────────────────────
# 📦 CHUNK 2/2 (25K tokens)
# [content of chunk 2]
```

---

### Compress session with LLM

Reduce session size using LLM compression (requires API key).

```bash
# Compress on save
aimem-cli save --from claude --compress

# Compress on load
aimem-cli load <session-id> --compress

# Result: ~95% size reduction
# Output: {
#   "current_goal": "Fix authentication bug",
#   "latest_code": [{"path": "auth.py", "content": "..."}],
#   "current_errors": ["TypeError: undefined"],
#   "key_decisions": ["Used JWT instead of session"],
#   "todo_list": ["Write tests", "Deploy to staging"]
# }
```

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
| `prompt` | API calls | ❌ |

---

## ⚙️ Configuration

Config file: `~/.aimem/config.json`

```bash
# Show config
aimem-cli config

# Enable LLM compression (opt-in)
aimem-cli config set compression.enabled true
aimem-cli config set compression.api_key YOUR_GROQ_KEY
aimem-cli config set compression.provider groq

# Auto-copy to clipboard
aimem-cli config set output.clipboard_auto true
```

### Config Options

| Option | Default | Description |
|--------|---------|-------------|
| `compression.enabled` | `false` | Enable LLM compression |
| `compression.provider` | `"groq"` | Compression provider (groq, gemini) |
| `compression.api_key` | `""` | API key for compression |
| `output.format` | `"markdown"` | Default output format |
| `output.clipboard_auto` | `true` | Auto-copy to clipboard |
| `storage.path` | `"~/.aimem/sessions"` | Session storage path |

---

## 📝 Examples

### Example 1: Transfer Claude session to OpenCode
```bash
$ aimem-cli save --from claude
[i] Found 5 Claude sessions. Select one:
  [1] 2026-04-20 | Fix authentication bug
  [2] 2026-04-19 | Add user login feature
  [3] 2026-04-18 | Research API design
Enter number (default=1): 1
[OK] Saved session: claude-abc123

$ aimem-cli load claude-abc123 --to opencode --inject
[OK] Injected into OpenCode
    Session ID: ses_xyz789
Resume with: opencode -s ses_xyz789

$ opencode -s ses_xyz789
# Continue with full context in OpenCode!
```

### Example 2: Transfer to any AI via Markdown
```bash
$ aimem-cli save --from claude
[OK] Saved session: claude-abc123

$ aimem-cli load claude-abc123 --to markdown
[OK] Content copied to clipboard!

# Paste into any AI: Gemini, ChatGPT, Qwen, etc.
```

### Example 3: Merge multiple sessions
```bash
$ aimem-cli merge claude-abc claude-def claude-ghi
[i] Merging 3 sessions...
[OK] Merged session: merged-xyz123
    Total messages: 156

$ aimem-cli load merged-xyz123 --to gemini --inject
```

---

## 🏗️ Architecture

```
aimem-cli/
├── aimem/
│   ├── cli.py                 # CLI interface
│   ├── models.py              # UniversalSession model
│   ├── storage.py             # File storage
│   ├── compression.py         # LLM compression
│   ├── context_manager.py     # Context management
│   └── adapters/
│       ├── claude.py          # Claude Code adapter
│       ├── gemini.py          # Gemini CLI adapter
│       ├── qwen.py             # Qwen CLI adapter
│       ├── opencode.py         # OpenCode adapter
│       ├── codex.py            # Codex adapter
│       ├── aider.py            # Aider adapter
│       ├── continue_dev.py     # Continue.dev adapter
│       ├── clipboard.py        # Clipboard adapter
│       └── output/             # Output formatters
│           ├── __init__.py
│           ├── markdown.py
│           ├── claude.py
│           ├── gemini.py
│           ├── qwen.py
│           ├── prompt.py
│           ├── continue.py
│           ├── codex.py
│           └── opencode.py
```

---

## 📦 Requirements

- Python 3.10+
- `pyperclip>=1.8.0` (clipboard support)
- `ulid-py>=1.1.0` (session ID generation)

---

## License

MIT