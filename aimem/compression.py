"""
LLM Compression Engine - Nén session thành structured summary.
Dùng Groq hoặc Gemini Flash (fast + cheap).
"""

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Literal
import json

from .models import UniversalSession, CompressedSession, ContextItem


MAX_COMPRESSION_INPUT_CHARS = 120_000
MAX_COMPRESS_MESSAGE_CHARS = 1_500
RECENT_MESSAGE_KEEP = 120
EARLY_MESSAGE_KEEP = 8

DEFAULT_COMPRESSION_MODELS = {
    "gemini": "gemini-3-flash-preview",
    "groq": "meta-llama/llama-4-scout-17b-16e-instruct",
}

KNOWN_FREE_COMPRESSION_MODELS = {
    "gemini": [
        {
            "id": "gemini-3-flash-preview",
            "label": "Gemini 3 Flash Preview",
            "note": "Free tier in Gemini API per Gemini 3 docs; preview, 1M input context.",
        },
        {
            "id": "gemini-2.5-flash-lite",
            "label": "Gemini 2.5 Flash-Lite",
            "note": "Free tier, 1M input context, fastest/cheapest Gemini 2.5 text model.",
        },
        {
            "id": "gemini-2.5-flash",
            "label": "Gemini 2.5 Flash",
            "note": "Free tier, 1M input context, stronger default quality.",
        },
        {
            "id": "gemini-2.0-flash-lite",
            "label": "Gemini 2.0 Flash-Lite",
            "note": "Legacy/deprecated fallback; prefer Gemini 2.5 Flash-Lite.",
        },
        {
            "id": "gemini-2.0-flash",
            "label": "Gemini 2.0 Flash",
            "note": "Legacy/deprecated fallback; prefer Gemini 2.5 Flash.",
        },
        {
            "id": "gemini-2.5-pro",
            "label": "Gemini 2.5 Pro",
            "note": "Free tier with tighter request limits; strongest quality.",
        },
        {
            "id": "gemma-3-27b-it",
            "label": "Gemma 3 27B IT",
            "note": "Hosted Gemma via Gemini API; free limits are much tighter, not ideal for long compression.",
        },
    ],
    "groq": [
        {
            "id": "groq/compound",
            "label": "Groq Compound",
            "note": "Free plan listed by Groq, agentic system, 70k free TPM.",
        },
        {
            "id": "groq/compound-mini",
            "label": "Groq Compound Mini",
            "note": "Free plan listed by Groq, agentic system, 70k free TPM.",
        },
        {
            "id": "meta-llama/llama-4-scout-17b-16e-instruct",
            "label": "Llama 4 Scout 17B 16E",
            "note": "Free plan listed by Groq, 131k context, higher free TPM than older Llama 3.1.",
        },
        {
            "id": "llama-3.1-8b-instant",
            "label": "Llama 3.1 8B Instant",
            "note": "Free plan listed by Groq, 131k context, low free TPM.",
        },
        {
            "id": "llama-3.3-70b-versatile",
            "label": "Llama 3.3 70B Versatile",
            "note": "Free plan listed by Groq, 131k context, low free TPM.",
        },
        {
            "id": "openai/gpt-oss-20b",
            "label": "GPT-OSS 20B",
            "note": "Free plan listed by Groq, 131k context.",
        },
        {
            "id": "openai/gpt-oss-120b",
            "label": "GPT-OSS 120B",
            "note": "Free plan listed by Groq, 131k context.",
        },
        {
            "id": "qwen/qwen3-32b",
            "label": "Qwen3 32B",
            "note": "Free plan listed by Groq, 131k context, low free TPM.",
        },
        {
            "id": "moonshotai/kimi-k2-instruct",
            "label": "Kimi K2 Instruct",
            "note": "Free plan listed by Groq.",
        },
        {
            "id": "moonshotai/kimi-k2-instruct-0905",
            "label": "Kimi K2 Instruct 0905",
            "note": "Free plan listed by Groq.",
        },
        {
            "id": "allam-2-7b",
            "label": "Allam 2 7B",
            "note": "Free plan listed by Groq.",
        },
    ],
}


def get_default_compression_model(provider: str) -> str:
    return DEFAULT_COMPRESSION_MODELS.get(provider.lower(), "gemini-2.5-flash-lite")


def get_known_compression_models(provider: str) -> list[dict]:
    provider_key = provider.lower()
    return [
        {**model, "provider": provider_key, "source": "known free/default list"}
        for model in KNOWN_FREE_COMPRESSION_MODELS.get(provider_key, [])
    ]


def _is_good_compression_model_name(model_id: str) -> bool:
    lowered = model_id.lower()
    blocked = ("embedding", "imagen", "image", "veo", "tts", "audio", "live", "whisper", "guard", "orpheus")
    return not any(item in lowered for item in blocked)


def list_compression_models(provider: str, api_key: str | None = None) -> list[dict]:
    provider_key = provider.lower()
    if provider_key == "gemini" and api_key:
        models = _list_gemini_models(api_key)
        if models:
            return models
    if provider_key == "groq" and api_key:
        models = _list_groq_models(api_key)
        if models:
            return models
    return get_known_compression_models(provider_key)


def _list_gemini_models(api_key: str) -> list[dict]:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}",
        headers={"Content-Type": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.HTTPError, json.JSONDecodeError):
        return []

    results: list[dict] = []
    seen: set[str] = set()
    for item in payload.get("models", []):
        if not isinstance(item, dict):
            continue
        methods = item.get("supportedGenerationMethods") or []
        if "generateContent" not in methods:
            continue
        model_id = str(item.get("name", "")).split("/")[-1]
        if not model_id or not _is_good_compression_model_name(model_id):
            continue
        key = model_id.lower()
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "provider": "gemini",
            "id": model_id,
            "label": item.get("displayName") or model_id,
            "note": "Available for generateContent with this API key.",
            "source": "Gemini API listModels",
        })
    return results


def _list_groq_models(api_key: str) -> list[dict]:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/models",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.HTTPError, json.JSONDecodeError):
        return []

    results: list[dict] = []
    seen: set[str] = set()
    for item in payload.get("data", []):
        if not isinstance(item, dict):
            continue
        model_id = str(item.get("id", ""))
        if not model_id or not _is_good_compression_model_name(model_id):
            continue
        key = model_id.lower()
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "provider": "groq",
            "id": model_id,
            "label": model_id,
            "note": "Available from Groq models endpoint for this API key.",
            "source": "Groq Models API",
        })
    return results


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
- latest_code.content must be a short JSON-safe string. Escape quotes and newlines, or summarize instead of copying raw code.
- current_errors: Copy error messages EXACTLY as they appear. Empty array if no errors.
- key_decisions: Only include meaningful decisions (not minor code changes). Max 10.
- todo_list: Extract from explicit todo mentions or 'next steps'. Empty if nothing found.
- Language: Vietnamese if the conversation is in Vietnamese, English otherwise.
- If a field has no information, use empty array "" for arrays, "N/A" for current_goal.
- The response must be valid JSON. Do not include markdown fences, comments, or trailing commas.
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
        self.provider = (compression.get("provider", "groq") or "groq").lower()
        self.api_key = compression.get("api_key")
        self.model = compression.get("model") or get_default_compression_model(self.provider)

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
                print(
                    f"[AiMem] Prepared compression input: {len(conversation_text):,} chars "
                    f"from {len(session.messages):,} messages"
                )
                print("[AiMem] Calling Groq compression API...")
                result = self._call_groq(conversation_text, session)
            elif self.provider == "gemini":
                print(
                    f"[AiMem] Prepared compression input: {len(conversation_text):,} chars "
                    f"from {len(session.messages):,} messages"
                )
                print("[AiMem] Calling Gemini compression API...")
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

        selected_messages = self._select_messages_for_compression(session)
        omitted = len(session.messages) - len(selected_messages)
        if omitted > 0:
            lines.append(
                f"[Compression note: {omitted:,} older messages omitted to fit the summarizer context.]"
            )
            lines.append("")

        for msg in selected_messages:
            role = msg.role.upper()
            content = msg.content

            # Truncate very long messages
            if len(content) > MAX_COMPRESS_MESSAGE_CHARS:
                content = content[:MAX_COMPRESS_MESSAGE_CHARS] + "\n... (truncated)"

            lines.append(f"**{role}:** {content}")
            lines.append("")

        return "\n".join(lines)

    def _select_messages_for_compression(self, session: UniversalSession) -> list:
        messages = list(session.messages)
        if not messages:
            return []

        selected = []
        seen_keys = set()
        for msg in [*messages[:EARLY_MESSAGE_KEEP], *messages[-RECENT_MESSAGE_KEEP:]]:
            key = msg.id or id(msg)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            selected.append(msg)

        while selected and self._selected_chars(selected) > MAX_COMPRESSION_INPUT_CHARS:
            if len(selected) <= EARLY_MESSAGE_KEEP + 1:
                break
            selected.pop(EARLY_MESSAGE_KEEP)

        return selected

    def _selected_chars(self, messages: list) -> int:
        return sum(
            min(len(msg.content or ""), MAX_COMPRESS_MESSAGE_CHARS) + 32
            for msg in messages
        )

    def _call_groq(self, conversation_text: str, session: UniversalSession) -> CompressedSession:
        """Gọi Groq API để compress."""
        import urllib.request
        import urllib.error

        system_prompt = COMPRESSION_SYSTEM_PROMPT

        # Adapt system prompt to conversation language
        # Check if conversation is in Vietnamese
        lower_text = conversation_text.lower()
        vietnamese_markers = "ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ"
        vietnamese_chars = sum(
            1
            for c in lower_text
            if c in vietnamese_markers or "\u4e00" <= c <= "\u9fff"
        )
        if vietnamese_chars > 50:
            # Likely Vietnamese conversation
            system_prompt = system_prompt.replace("Language: Vietnamese", "Ngôn ngữ: Tiếng Việt")

        user_prompt = COMPRESSION_USER_PROMPT.format(
            source=session.source,
            project=session.metadata.project_path or "N/A",
            model=session.metadata.model or "N/A",
            conversation_text=conversation_text,
        )

        groq_model = self.model
        if groq_model.startswith("gemini-"):
            groq_model = get_default_compression_model("groq")

        payload_data = {
            "model": groq_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 2048,
            "response_format": {"type": "json_object"},
        }
        payload = json.dumps(payload_data).encode("utf-8")

        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code == 400 and "response_format" in body.lower():
                payload_data.pop("response_format", None)
                retry_req = urllib.request.Request(
                    "https://api.groq.com/openai/v1/chat/completions",
                    data=json.dumps(payload_data).encode("utf-8"),
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    method="POST"
                )
                with urllib.request.urlopen(retry_req, timeout=30) as response:
                    result = json.loads(response.read().decode("utf-8"))
            elif exc.code == 403 and "1010" in body:
                raise RuntimeError(
                    "Groq API returned HTTP 403 error 1010. "
                    "Groq/Cloudflare blocked the request before summarization; "
                    "switch compression.provider to gemini, rotate/check the Groq key, "
                    "or retry from a different network/VPN."
                ) from exc
            else:
                raise RuntimeError(f"Groq API returned HTTP {exc.code}: {body[:800]}") from exc

        content = result["choices"][0]["message"]["content"]
        return self._compressed_from_content(content)

    def _call_gemini(self, conversation_text: str, session: UniversalSession) -> CompressedSession:
        """Gọi Gemini API để compress."""
        gemini_model = (self.model or "").strip()
        if gemini_model.startswith("models/"):
            gemini_model = gemini_model.split("/", 1)[1]
        legacy_map = {
            "gemini-2.0-flash-exp": "gemini-2.0-flash",
            "gemini-1.5-flash": "gemini-2.5-flash-lite",
            "gemini-1.5-flash-8b": "gemini-2.5-flash-lite",
            "gemini-1.5-pro": "gemini-2.5-flash",
        }
        gemini_model = legacy_map.get(gemini_model, gemini_model)
        if not gemini_model.startswith(("gemini-", "gemma-")):
            gemini_model = get_default_compression_model("gemini")

        system_prompt = COMPRESSION_SYSTEM_PROMPT
        user_prompt = COMPRESSION_USER_PROMPT.format(
            source=session.source,
            project=session.metadata.project_path or "N/A",
            model=session.metadata.model or "N/A",
            conversation_text=conversation_text,
        )

        try:
            content = self._call_gemini_sdk(gemini_model, system_prompt, user_prompt)
            return self._compressed_from_content(content)
        except ImportError:
            pass

        import urllib.request
        import urllib.error

        payload = json.dumps({
            "contents": [{
                "role": "user",
                "parts": [{"text": f"{system_prompt}\n\n{user_prompt}"}]
            }],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 2048,
                "responseMimeType": "application/json",
            }
        }).encode("utf-8")

        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{gemini_model}:generateContent?key={self.api_key}"

        req = urllib.request.Request(
            api_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Gemini API returned HTTP {exc.code}: {body[:800]}") from exc

        content = result["candidates"][0]["content"]["parts"][0]["text"]
        return self._compressed_from_content(content)

    def _call_gemini_sdk(self, gemini_model: str, system_prompt: str, user_prompt: str) -> str:
        """Call Gemini using the official google-genai Client.models.generate_content shape."""
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key)
        config_kwargs = {
            "temperature": 0.1,
            "max_output_tokens": 2048,
            "response_mime_type": "application/json",
        }
        try:
            config = types.GenerateContentConfig(**config_kwargs)
        except TypeError:
            config = types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=2048,
            )
        response = client.models.generate_content(
            model=gemini_model,
            contents=f"{system_prompt}\n\n{user_prompt}",
            config=config,
        )
        content = getattr(response, "text", None)
        if not content:
            raise RuntimeError("Gemini SDK returned an empty response.")
        return content

    def _compressed_from_content(self, content: str) -> CompressedSession:
        cleaned = self._strip_json_markdown(content)
        try:
            compressed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            extracted = self._extract_json_object(cleaned)
            if extracted and extracted != cleaned:
                try:
                    compressed = json.loads(extracted)
                    cleaned = extracted
                except json.JSONDecodeError:
                    return self._fallback_compressed_from_text(content, exc)
            else:
                return self._fallback_compressed_from_text(content, exc)

        latest_code = []
        for snippet in compressed.get("latest_code", []):
            if not isinstance(snippet, dict):
                continue
            latest_code.append(ContextItem(
                type="snippet",
                path=snippet.get("path"),
                content=str(snippet.get("content", ""))[:500],
                language=snippet.get("language"),
            ))

        return CompressedSession(
            current_goal=str(compressed.get("current_goal", "N/A")),
            latest_code=latest_code,
            current_errors=self._string_list(compressed.get("current_errors", [])),
            key_decisions=self._string_list(compressed.get("key_decisions", [])),
            todo_list=self._string_list(compressed.get("todo_list", [])),
            summary_token_count=len(cleaned) // 4,
            compressed_at=datetime.now(timezone.utc).isoformat(),
        )

    def _strip_json_markdown(self, content: str) -> str:
        cleaned = (content or "").strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        return cleaned

    def _extract_json_object(self, text: str) -> str | None:
        start = text.find("{")
        if start == -1:
            return None

        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[start:index + 1]
        return None

    def _string_list(self, value) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item)[:1000] for item in value if item is not None]

    def _fallback_compressed_from_text(self, content: str, exc: json.JSONDecodeError) -> CompressedSession:
        cleaned = self._strip_json_markdown(content)
        snippet = cleaned[:1500] if cleaned else "Compression model returned malformed JSON."
        return CompressedSession(
            current_goal="Compression completed but the model returned malformed JSON; preserved raw summary text.",
            latest_code=[],
            current_errors=[f"Compression JSON parse warning: {exc.msg} at line {exc.lineno} column {exc.colno}"],
            key_decisions=[snippet],
            todo_list=[],
            summary_token_count=max(1, len(snippet) // 4),
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
