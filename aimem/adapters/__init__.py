"""Adapters for various AI agents."""

from .claude import ClaudeAdapter
from .qwen import QwenAdapter
from .gemini import GeminiAdapter
from .clipboard import ClipboardAdapter

__all__ = [
    "ClaudeAdapter",
    "QwenAdapter",
    "GeminiAdapter",
    "ClipboardAdapter",
]