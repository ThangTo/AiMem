# AiMem - AI Memory Switcher

<img src="assets/poster.png" alt="AiMem - Transfer context between AI agents" width="100%">

[![PyPI](https://img.shields.io/pypi/v/aimem-cli?color=blue)](https://pypi.org/project/aimem-cli/)
[![Python](https://img.shields.io/pypi/pyversions/aimem-cli)](https://pypi.org/project/aimem-cli/)
[![License](https://img.shields.io/pypi/l/aimem-cli)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/ThangTo/AiMem)](https://github.com/ThangTo/AiMem/stargazers)

AiMem helps you save, inspect, compress, and transfer conversation context between AI coding agents. When one agent hits a token limit, rate limit, or you simply want to switch tools, AiMem lets the next agent continue with the context you already built.

## Install

```bash
pip install aimem-cli
```

From source:

```bash
git clone https://github.com/ThangTo/AiMem.git
cd AiMem
pip install -e .
```

Run the interactive TUI:

```bash
aimem-cli
```

## What Is New In 0.2.8

- Fixed OpenCode injection so imported messages no longer block the next real prompt from calling the LLM.
- Fixed OpenCode message timestamps so new chats are not inserted between older imported messages.
- Restored TUI resume flow after injection, including opening `opencode -s <session-id>` in a new terminal.
- Fixed Codex CLI injection by writing complete base instructions and visible transcript events.
- Improved Codex VS Code extension launch through the correct deep link flow.
- Added `--no-compress` so compression is only used when explicitly requested or enabled.
- Added regression tests for OpenCode injection ordering, model selection, and context budgeting.

## Core Features

- Interactive TUI with session selection, analysis, chunking, compression, injection, and resume actions.
- Save sessions from Claude, Gemini, Qwen, OpenCode, Codex, Cursor, Aider, Continue.dev, or clipboard.
- Load sessions as Markdown, Claude, Gemini, Qwen, OpenCode, Codex, Cursor, Continue.dev, or prompt format.
- Inject directly into supported agent storage, then resume in the target tool.
- Analyze context size against the target model before loading.
- Chunk large sessions while preserving all messages.
- Optional LLM compression with explicit `--compress` and `--no-compress` controls.
- Merge multiple sessions into a single context package.

## Quick Start

### Interactive Mode

```bash
aimem-cli
```

Use the TUI to:

- Pick a source session.
- Analyze, chunk, compress, copy, or inject it.
- Open the injected target session directly when supported.

### Transfer Claude To OpenCode

```bash
aimem-cli save --from claude
aimem-cli load <session-id> --to opencode --inject
opencode -s <opencode-session-id>
```

In the TUI, after injection you can choose to open the OpenCode session immediately in a new terminal.

### Transfer To Codex

```bash
aimem-cli save --from claude
aimem-cli load <session-id> --to codex --inject
codex resume <codex-session-id>
```

The TUI also supports opening the injected Codex session in the terminal or in the VS Code extension.

### Transfer Through Markdown

```bash
aimem-cli save --from claude
aimem-cli load <session-id> --to markdown --copy
```

Paste the generated context into any AI assistant.

## Commands

### Initialize Config

```bash
aimem-cli init
aimem-cli init --force
```

### Save A Session

```bash
aimem-cli save --from claude
aimem-cli save --from gemini
aimem-cli save --from qwen
aimem-cli save --from opencode
aimem-cli save --from codex
aimem-cli save --from cursor
aimem-cli save --from aider
aimem-cli save --from continue
aimem-cli save --from clipboard
```

Save a specific session when the adapter supports it:

```bash
aimem-cli save --from opencode --session-id <session-id>
```

### Load Or Convert A Session

```bash
aimem-cli load <session-id> --to markdown
aimem-cli load <session-id> --to claude
aimem-cli load <session-id> --to gemini
aimem-cli load <session-id> --to qwen
aimem-cli load <session-id> --to opencode
aimem-cli load <session-id> --to codex
aimem-cli load <session-id> --to cursor
aimem-cli load <session-id> --to continue
aimem-cli load <session-id> --to prompt
```

### Inject Into Target Storage

```bash
aimem-cli load <session-id> --to claude --inject
aimem-cli load <session-id> --to gemini --inject
aimem-cli load <session-id> --to qwen --inject
aimem-cli load <session-id> --to opencode --inject
aimem-cli load <session-id> --to codex --inject
aimem-cli load <session-id> --to cursor --inject
```

OpenCode model override:

```bash
aimem-cli load <session-id> --to opencode --inject --opencode-model google/gemma-4-31b-it
```

### Analyze, Chunk, Compress

```bash
aimem-cli load <session-id> --to opencode --analyze
aimem-cli load <session-id> --to opencode --chunk
aimem-cli load <session-id> --to opencode --compress --inject
aimem-cli load <session-id> --to opencode --no-compress --inject
```

### Merge Sessions

```bash
aimem-cli merge <session-a> <session-b>
aimem-cli merge <session-a> <session-b> --smart
aimem-cli merge <session-a> <session-b> --smart --to gemini
```

### Config

```bash
aimem-cli config
aimem-cli config set compression.enabled true
aimem-cli config set compression.enabled false
aimem-cli config set compression.api_key YOUR_API_KEY
aimem-cli config set compression.provider groq
aimem-cli config set output.clipboard_auto true
```

### Delete

```bash
aimem-cli delete <session-id>
```

## Supported Agents

### Sources

| Agent | Notes |
| --- | --- |
| Claude | Reads Claude Code JSONL project sessions |
| Gemini | Reads Gemini CLI chat sessions |
| Qwen | Reads Qwen CLI logs |
| OpenCode | Reads OpenCode database/export sessions |
| Codex | Reads Codex rollout sessions |
| Cursor | Reads Cursor composer data |
| Aider | Reads `.aider.chat.history.md` |
| Continue.dev | Reads Continue session database |
| Clipboard | Saves current clipboard content |

### Injection Targets

| Target | Resume Command |
| --- | --- |
| Claude | `claude --resume` |
| Gemini | `gemini --resume` |
| Qwen | `qwen --resume` |
| OpenCode | `opencode -s <session-id>` |
| Codex CLI | `codex resume <session-id>` |
| Codex VS Code | Opens `vscode://openai.chatgpt/local/<session-id>` |
| Cursor | Opens the target project/session in Cursor |

## Configuration

Config file:

```text
~/.aimem/config.json
```

Important options:

| Option | Default | Description |
| --- | --- | --- |
| `compression.enabled` | `false` | Enable automatic LLM compression |
| `compression.provider` | `groq` | Compression provider |
| `compression.api_key` | empty | API key for compression |
| `output.format` | `markdown` | Default output format |
| `output.clipboard_auto` | `true` | Auto-copy generated output |
| `storage.path` | `~/.aimem/sessions` | Saved session directory |

## Development

```bash
pip install -e ".[dev]"
python -m pytest
python -m build
```

Project layout:

```text
aimem/
  cli.py
  tui.py
  models.py
  storage.py
  compression.py
  context_manager.py
  adapters/
    claude.py
    gemini.py
    qwen.py
    opencode.py
    codex.py
    cursor.py
    aider.py
    continue_dev.py
```

## License

MIT License. See [LICENSE](LICENSE).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
