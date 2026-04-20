# 🧠 AiMem — AI Memory Switcher

> Save, compress, and transfer context seamlessly between AI agents.
> When Claude hits rate-limits or you're mid-flow, AiMem bridges the gap — **without losing your train of thought**.

```
Agent A (Claude)  ──▶  Read Session  ──▶  Universal Format  ──▶  Save  ──▶  Agent B (Gemini)
  (JSONL)              (.jsonl)             (JSON)              (~/.aimem/)     (Markdown/Prompt)
```

**Zero server. Zero Redis. Works offline. LLM compression is opt-in.**

---

## Install

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

## Quick Start

```bash
# 1. Save current Claude session
aimem save --from claude

# 2. Load into Gemini (auto-copied to clipboard)
aimem load sess-abc123 --to gemini

# That's it. Paste into Gemini CLI.
```

---

## Commands

```
aimem init                          Initialize config (~/.aimem/config.json)
aimem save --from claude            Save session (interactive if multiple)
aimem save --from clipboard         Save from system clipboard
aimem save --from qwen              Save from Qwen CLI
aimem save --from gemini            Save from Gemini CLI
aimem save --from aider             Save from Aider chat history
aimem save --from continue          Save from Continue.dev
aimem load <id> --to gemini          Load session as target format
aimem list                           List saved sessions
aimem list --agents                  Check which agents are available
aimem config                         Show current config
aimem config set key=value           Update config
aimem delete <id>                    Delete a saved session
```

### Source agents (`--from`)

| Agent | Storage | Inject? |
|-------|---------|---------|
| `claude` | `~/.claude/projects/*/*.jsonl` | ✅ |
| `gemini` | `~/.gemini/tmp/*/chats/*.json` | ✅ |
| `qwen` | `~/.qwen/tmp/*/logs.json` | ✅ |
| `opencode` | `~/.opencode/sessions/*.json` | ✅ |
| `codex` | `~/.codex/sessions/*.jsonl` | ✅ |
| `aider` | `~/.aider.chat.history.md` | ❌ |
| `continue` | `~/.continue/sessions.db` | ❌ |
| `clipboard` | System clipboard | ❌ |

### Target formats (`--to`)

| Format | Best for | Inject? |
|--------|---------|---------|
| `markdown` | Paste into any web UI or tool | ❌ |
| `claude` | Claude Code CLI | ✅ |
| `gemini` | Gemini CLI | ✅ |
| `qwen` | Qwen CLI | ✅ |
| `opencode` | OpenCode CLI | ✅ |
| `codex` | Codex CLI | ✅ |
| `continue` | Continue.dev (VS Code) | ❌ |
| `prompt` | API calls / custom injection | ❌ |

### Auto-Inject (NEW!)

Inject directly into target agent storage — no copy-paste needed:

```bash
# Inject into Gemini (appears in session list)
aimem load claude-62d520bb --to gemini --inject
gemini --resume latest

# Inject into OpenCode
aimem load claude-62d520bb --to opencode --inject
opencode -s ses_xxx

# Inject into Claude
aimem load claude-62d520bb --to claude --inject
claude --resume
```

---

## Configuration

Config: `~/.aimem/config.json`

```bash
# Show config
aimem config

# Enable LLM compression (opt-in)
aimem config set compression.enabled true
aimem config set compression.api_key YOUR_GROQ_KEY

# Switch compression provider
aimem config set compression.provider groq
aimem config set compression.provider gemini

# Change output format
aimem config set output.format markdown
aimem config set output.clipboard_auto true

# Enable Redis cache (optional)
aimem config set storage.redis.enabled true
aimem config set storage.redis.host localhost
aimem config set storage.redis.ttl 3600
```

---

## Architecture

```
aimem/
├── aimem/
│   ├── __init__.py
│   ├── cli.py              # CLI interface + all commands
│   ├── models.py           # UniversalSession, Message, CompressedSession
│   ├── storage.py          # FileStorage (default) + RedisCache (opt-in)
│   ├── compression.py      # LLM Compression Engine (Groq / Gemini)
│   └── adapters/
│       ├── claude.py       # Read ~/.claude/projects/*/*.jsonl
│       ├── qwen.py          # Read ~/.qwen/tmp/*/logs.json (gzip)
│       ├── gemini.py        # Read ~/.config/gemini/ (JSON/JSONL)
│       ├── aider.py         # Read ~/.aider.chat.history.md
│       ├── continue_dev.py  # Read ~/.continue/sessions.db (SQLite)
│       ├── clipboard.py     # Read system clipboard
│       └── output/
│           └── __init__.py  # Markdown, Claude, Gemini, Qwen, Continue, Prompt
└── aimem_main.py           # Entry point (run without install)
```

### Universal Session Format

Every agent's session is converted to this neutral JSON format:

```json
{
  "id": "claude-62d520bb",
  "source": "claude",
  "messages": [
    {"id": "...", "role": "user", "content": "...", "timestamp": "..."},
    {"id": "...", "role": "assistant", "content": "...", "timestamp": "..."}
  ],
  "context_items": [],
  "compressed": {
    "current_goal": "Build context transfer tool",
    "latest_code": [{"path": "cli.py", "content": "...", "language": "python"}],
    "current_errors": ["Error: undefined is not a function"],
    "key_decisions": ["Use file-based storage over Redis"],
    "todo_list": ["Write Continue.dev adapter", "Add compression"]
  },
  "metadata": {
    "source_agent": "claude",
    "original_session_id": "62d520bb",
    "project_path": "D:\\Project\\AiMem",
    "model": "claude-sonnet-4-6"
  },
  "created_at": "2026-04-18T08:11:00Z"
}
```

### LLM Compression (Opt-in)

When `--compress` is used (or `compression.enabled` is true in config):

```
Input: ~114k tokens (Claude session) + Groq API call
                          ↓
Output: ~2k tokens (compressed summary)
                          ↓
Save to ~/.aimem/sessions/ as JSON
```

Providers:
- **Groq** `llama-3.1-8b-instant` — Fast + Cheap (~$0.001/session)
- **Gemini** `gemini-2.0-flash-exp` — Google's fast model

Requires `compression.api_key` to be set.

---

## Workflow Example

```bash
# You're coding in Claude, session hits limit
$ aimem save --from claude
[i] Found 78 Claude sessions. Select one:
  [1] 2026-04-18T08:11 | Tôi muốn tạo một tool giúp chuyển context...
  [2] 2026-04-17T14:46 | Research how different AI CLI agents...
Enter number (default=1): 1
[OK] Saved session: claude-62d520bb

# Switch to Gemini, paste context
$ aimem load claude-62d520bb --to gemini
## Previous Context

Continuing from previous session:

Project: `D:\Project\AiMem`
**Goal:** Build AiMem - context transfer tool

**Key Decisions:**
- File-based storage (no Redis dependency)
- Python-first for AI/ML ecosystem
- Opt-in compression (not required)

**Todo:**
- [ ] Write Continue.dev adapter
- [ ] Add session interactive selection

---
**Continue from here.**

# Copied to clipboard automatically
```

---

## Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1 | ✅ DONE | MVP — Claude, Qwen, Gemini, Clipboard, Aider, Continue adapters |
| Phase 2 | ⚠️ PARTIAL | LLM Compression — Groq works, Gemini blocked (API issue) |
| Phase 3 | ✅ DONE | Output adapters for all agents |
| Phase 4 | 🔜 NEXT | Smart chunking + context window management |
| Phase 5 | 📋 PLANNED | VS Code Extension |
| Phase 6 | 📋 PLANNED | GUI (optional TUI mode) |

---

## Design Decisions

### Why File-Based by Default?

| Approach | Setup Time | Portability | User Friction |
|----------|-----------|-------------|---------------|
| Redis | 5-10 min | Low (server-dependent) | High |
| File (AiMem) | 0 min (works immediately) | High (copy config file) | Low |

**AiMem saves sessions as plain JSON in `~/.aimem/sessions/`** — no server, no daemon, no Redis. Transfer a session from your laptop to a server with one `aimem load` + `aimem save`.

### Why Python?

- Python is pre-installed on most developer machines
- Native ecosystem for AI/ML tools (LLM APIs, SQLite parsing, etc.)
- Easy to extend with `pip install aimem`
- Native packaging via `pyproject.toml`

### Why LLM Compression is Opt-in?

- Not every user has an API key
- Raw transfer works fine for most cases
- Compression adds latency (1-3s per save)
- Non-deterministic — may lose nuance

---

## License

MIT