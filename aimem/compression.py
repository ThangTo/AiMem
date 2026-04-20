"""
LLM Compression Engine - Nén session thành structured summary.
Dùng Groq hoặc Gemini Flash (fast + cheap).
"""

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Literal
import json

from .models import UniversalSession, CompressedSession, ContextItem


# ─────────────────────────────────────────────────────────────
# Compression Prompt
# ─────────────────────────────────────────────────────────────

COMPRESSION_SYSTEM_PROMPT = """You are an AI session summarizer. Your job is to extract the essential information from a conversation session.

Extract and return ONLY a JSON object with these fields (no additional text):

{
  "current_goal": "What the user is currently trying to accomplish. Be specific. If unclear, use 'Unclear from conversation.'",
  "latest_code": [{"path": "file path or 'snippet' if no file", "content": "most relevant code (max 500 chars)", "language": "language or 'plaintext'"}],
  "current_errors": ["exact error messages found in the conversation"],
  "key_decisions": ["architectural or implementation decisions made during this session"],
  "todo_list": ["pending tasks or next steps mentioned"]
}

Rules:
- latest_code: Only include the MOST relevant snippets (max 5). Focus on recently modified files.
- current_errors: Copy error messages EXACTLY as they appear. Empty array if no errors.
- key_decisions: Only include meaningful decisions (not minor code changes). Max 10.
- todo_list: Extract from explicit todo mentions or 'next steps'. Empty if nothing found.
- Language: Vietnamese if the conversation is in Vietnamese, English otherwise.
- If a field has no information, use empty array "" for arrays, "N/A" for current_goal.
"""


COMPRESSION_USER_PROMPT = """Compress this conversation session into the structured JSON format.

Session source: {source}
Project: {project}
Model: {model}

---

CONVERSATION:
{conversation_text}

---

Return only the JSON object. No markdown, no code blocks, just raw JSON."""


# ─────────────────────────────────────────────────────────────
# Compression Engine
# ─────────────────────────────────────────────────────────────

class CompressionEngine:
    """
    Nén session bằng LLM (Groq/Gemini Flash).
    Đây là OPT-IN — không bắt buộc.
    """

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        compression = self.config.get("compression", {})

        self.enabled = compression.get("enabled", False)
        self.provider = compression.get("provider", "groq")
        self.api_key = compression.get("api_key")
        self.model = compression.get("model", "llama-3.1-8b-instant")

    def is_configured(self) -> bool:
        """Kiểm tra đã config API key chưa."""
        return bool(self.api_key)

    def compress(self, session: UniversalSession) -> CompressedSession | None:
        """
        Nén session thành CompressedSession.
        Trả về None nếu compression không được bật hoặc không có API key.
        """
        if not self.enabled:
            return None

        if not self.is_configured():
            return None

        # Build conversation text
        conversation_text = self._build_conversation_text(session)
        if len(conversation_text) < 200:
            # Too short to compress meaningfully
            return None

        try:
            if self.provider == "groq":
                result = self._call_groq(conversation_text, session)
            elif self.provider == "gemini":
                result = self._call_gemini(conversation_text, session)
            else:
                return None

            return result
        except Exception as e:
            print(f"[AiMem] Compression failed: {e}")
            return None

    def _build_conversation_text(self, session: UniversalSession) -> str:
        """Build conversation text from messages."""
        lines = []
        lines.append(f"[Source: {session.source.upper()}]")

        if session.metadata.project_path:
            lines.append(f"[Project: {session.metadata.project_path}]")

        lines.append("")

        for msg in session.messages:
            role = msg.role.upper()
            content = msg.content

            # Truncate very long messages
            if len(content) > 2000:
                content = content[:2000] + "\n... (truncated)"

            lines.append(f"**{role}:** {content}")
            lines.append("")

        return "\n".join(lines)

    def _call_groq(self, conversation_text: str, session: UniversalSession) -> CompressedSession:
        """Gọi Groq API để compress."""
        import urllib.request
        import urllib.error

        system_prompt = COMPRESSION_SYSTEM_PROMPT

        # Adapt system prompt to conversation language
        # Check if conversation is in Vietnamese
        vietnamese_chars = sum(1 for c in conversation_text if '\u4e00' <= c <= '\u9fff' or 'đ' in conversation_text.lower())
        if vietnamese_chars > 50:
            # Likely Vietnamese conversation
            system_prompt = system_prompt.replace("Language: Vietnamese", "Ngôn ngữ: Tiếng Việt")

        user_prompt = COMPRESSION_USER_PROMPT.format(
            source=session.source,
            project=session.metadata.project_path or "N/A",
            model=session.metadata.model or "N/A",
            conversation_text=conversation_text,
        )

        payload = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 2048,
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))

        content = result["choices"][0]["message"]["content"]

        # Parse JSON
        # Strip markdown code blocks if present
        content = content.strip()
        if content.startswith("```"):
            # Remove ```json or ``` at start/end
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines)

        compressed = json.loads(content)

        # Convert to ContextItem for latest_code
        latest_code = []
        for snippet in compressed.get("latest_code", []):
            latest_code.append(ContextItem(
                type="snippet",
                path=snippet.get("path"),
                content=snippet.get("content", ""),
                language=snippet.get("language"),
            ))

        return CompressedSession(
            current_goal=compressed.get("current_goal", "N/A"),
            latest_code=latest_code,
            current_errors=compressed.get("current_errors", []),
            key_decisions=compressed.get("key_decisions", []),
            todo_list=compressed.get("todo_list", []),
            summary_token_count=len(content) // 4,
            compressed_at=datetime.now(timezone.utc).isoformat(),
        )

    def _call_gemini(self, conversation_text: str, session: UniversalSession) -> CompressedSession:
        """Gọi Gemini API để compress."""
        import urllib.request
        import urllib.error

        # Use Gemini Flash 2.0 via REST API
        model_map = {
            "gemini-2.0-flash": "gemini-2.0-flash-exp",
            "gemini-1.5-flash": "gemini-1.5-flash",
            "gemini-1.5-pro": "gemini-1.5-pro",
        }
        gemini_model = model_map.get(self.model, "gemini-2.0-flash-exp")

        system_prompt = COMPRESSION_SYSTEM_PROMPT
        user_prompt = COMPRESSION_USER_PROMPT.format(
            source=session.source,
            project=session.metadata.project_path or "N/A",
            model=session.metadata.model or "N/A",
            conversation_text=conversation_text,
        )

        payload = json.dumps({
            "contents": [{
                "role": "user",
                "parts": [{"text": f"{system_prompt}\n\n{user_prompt}"}]
            }],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 2048,
            }
        }).encode("utf-8")

        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={self.api_key}"

        req = urllib.request.Request(
            api_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))

        content = result["candidates"][0]["content"]["parts"][0]["text"]

        # Parse JSON
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines)

        compressed = json.loads(content)

        latest_code = []
        for snippet in compressed.get("latest_code", []):
            latest_code.append(ContextItem(
                type="snippet",
                path=snippet.get("path"),
                content=snippet.get("content", ""),
                language=snippet.get("language"),
            ))

        return CompressedSession(
            current_goal=compressed.get("current_goal", "N/A"),
            latest_code=latest_code,
            current_errors=compressed.get("current_errors", []),
            key_decisions=compressed.get("key_decisions", []),
            todo_list=compressed.get("todo_list", []),
            summary_token_count=len(content) // 4,
            compressed_at=datetime.now(timezone.utc).isoformat(),
        )

    def estimate_savings(self, session: UniversalSession) -> tuple[int, int, float]:
        """
        Ước tính savings nếu compress.
        Returns: (original_tokens, compressed_tokens_estimate, compression_ratio)
        """
        original = session.estimate_tokens()

        # Rough estimate: compressed ~5-10% of original
        # depends on session length and complexity
        if original < 1000:
            compressed = original
            ratio = 1.0
        elif original < 10000:
            compressed = int(original * 0.08)
            ratio = 0.08
        else:
            compressed = int(original * 0.03)
            ratio = 0.03

        return original, compressed, ratio