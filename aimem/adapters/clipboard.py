"""
Clipboard Adapter - Đọc context từ system clipboard.
Dùng khi user copy text từ web UI hoặc bất kỳ nguồn nào.
"""

from ..models import UniversalSession, Message, SessionMetadata
import uuid


class ClipboardAdapter:
    """Adapter để đọc nội dung từ system clipboard."""

    name = "clipboard"
    description = "System Clipboard (copy/paste)"

    def is_available(self) -> bool:
        """Clipboard luôn available nếu có pyperclip."""
        try:
            import pyperclip  # noqa: F401
            return True
        except ImportError:
            return False

    def read(self) -> str:
        """Đọc text từ clipboard."""
        try:
            import pyperclip
            return pyperclip.paste()
        except ImportError:
            # Fallback: đọc qua subprocess
            try:
                import subprocess
                if __import__("platform").system() == "Windows":
                    result = subprocess.run(
                        ["powershell", "-Command", "Get-Clipboard"],
                        capture_output=True, text=True, timeout=2
                    )
                    return result.stdout
                else:
                    result = subprocess.run(
                        ["xclip", "-selection", "clipboard", "-o"],
                        capture_output=True, text=True, timeout=2
                    )
                    return result.stdout
            except Exception:
                raise RuntimeError(
                    "Clipboard requires 'pyperclip' package. "
                    "Install with: pip install pyperclip"
                )

    def export(self) -> UniversalSession:
        """
        Export clipboard content as a UniversalSession.
        """
        text = self.read()

        if not text or not text.strip():
            raise ValueError("Clipboard is empty.")

        # Split into lines for analysis
        lines = text.strip().split("\n")

        # Detect if it's a chat log format
        is_chat = False
        messages = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Simple chat format detection
            lower = line.lower()
            if any(prefix in lower for prefix in ["user:", "assistant:", "human:", "ai:", "you:", "claude:", "gemini:"]):
                is_chat = True

                if line.lower().startswith("user:") or line.lower().startswith("human:") or line.lower().startswith("you:"):
                    content = line.split(":", 1)[1].strip() if ":" in line else line
                    messages.append(Message(
                        id=str(uuid.uuid4()),
                        role="user",
                        content=content,
                        timestamp="",
                    ))
                elif any(line.lower().startswith(p) for p in ["assistant:", "ai:", "gemini:", "claude:", "bot:"]):
                    content = line.split(":", 1)[1].strip() if ":" in line else line
                    messages.append(Message(
                        id=str(uuid.uuid4()),
                        role="assistant",
                        content=content,
                        timestamp="",
                    ))

        if not is_chat or not messages:
            # Treat entire clipboard as one user message
            messages = [Message(
                id=str(uuid.uuid4()),
                role="user",
                content=text.strip(),
                timestamp="",
            )]

        return UniversalSession(
            id=f"clip-{uuid.uuid4().hex[:8]}",
            source="clipboard",
            messages=messages,
            metadata=SessionMetadata(
                source_agent="clipboard",
                token_count=len(text) // 4,
            ),
            tags=["clipboard"],
        )
