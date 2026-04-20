# Contributing to AiMem

Thank you for your interest in contributing!

## Quick Start

```bash
# Clone the repo
git clone https://github.com/ThangTo/AiMem.git
cd AiMem

# Install in development mode
pip install -e .

# Run tests
python -m pytest
```

## Project Structure

```
aimem/
├── cli.py              # CLI commands
├── models.py           # Data models
├── storage.py          # Session storage
├── compression.py     # LLM compression
├── context_manager.py # Context analysis, chunking
└── adapters/
    ├── claude.py      # Claude adapter
    ├── gemini.py      # Gemini adapter
    ├── qwen.py        # Qwen adapter
    ├── opencode.py    # OpenCode adapter
    ├── codex.py       # Codex adapter
    ├── aider.py       # Aider adapter
    ├── continue_dev.py # Continue.dev adapter
    ├── clipboard.py   # Clipboard adapter
    └── output/        # Output formatters
```

## Adding a New Adapter

1. Create `adapters/<name>.py`
2. Implement `list_sessions()` and `export_session(session_id)`
3. Register in `adapters/__init__.py`
4. Add CLI options in `cli.py`

Example:

```python
from . import BaseAdapter

class MyAdapter(BaseAdapter):
    name = "myagent"
    storage_path = "~/.myagent/sessions"

    def list_sessions(self):
        # Return list of sessions
        pass

    def export_session(self, session_id):
        # Return UniversalSession
        pass
```

## Code Style

- Follow PEP 8
- Use type hints where possible
- Add docstrings for public functions

## Submitting Changes

1. Fork the repo
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## Issues

- Report bugs with clear reproduction steps
- Feature requests welcome!

## License

By contributing, you agree that your contributions will be licensed under MIT License.
