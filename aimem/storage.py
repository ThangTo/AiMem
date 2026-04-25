"""
Storage - File-based session storage.
Default: ~/.aimem/sessions/
Optional Redis: ~/.aimem/config.json → redis.enabled = true
"""

from pathlib import Path
from typing import Literal
import json
import os

from .models import UniversalSession


# ─────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────

def _get_aimem_base() -> Path:
    home = Path(os.path.expanduser("~"))
    return home / ".aimem"


def _get_sessions_dir() -> Path:
    d = _get_aimem_base() / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_config_path() -> Path:
    return _get_aimem_base() / "config.json"


# ─────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "version": "1",
    "storage": {
        "type": "file",  # "file" | "redis"
        "redis": {
            "enabled": False,
            "host": "localhost",
            "port": 6379,
            "password": None,
            "ttl": 3600,
        }
    },
    "compression": {
        "enabled": False,
        "provider": "groq",  # "groq" | "gemini"
        "api_key": None,
        "model": "meta-llama/llama-4-scout-17b-16e-instruct",
    },
    "adapters": {
        "claude": {"enabled": True, "auto_detect": True},
        "gemini": {"enabled": True, "auto_detect": True},
        "qwen": {"enabled": True, "auto_detect": True},
        "clipboard": {"enabled": True},
    },
    "output": {
        "format": "markdown",  # "markdown" | "json" | "prompt"
        "clipboard_auto": True,
    },
}


def load_config() -> dict:
    """Load config from file, return defaults if not exists."""
    path = _get_config_path()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # Merge with defaults
            result = DEFAULT_CONFIG.copy()
            _deep_merge(result, cfg)
            # Remove any stale keys not in DEFAULT_CONFIG schema
            for key in list(result.keys()):
                if key not in DEFAULT_CONFIG:
                    del result[key]
            return result
        except (json.JSONDecodeError, OSError):
            pass
    return DEFAULT_CONFIG.copy()


def save_config(config: dict) -> None:
    """Save config to file."""
    path = _get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


# ─────────────────────────────────────────────────────────────
# File Storage
# ─────────────────────────────────────────────────────────────

class FileStorage:
    """File-based storage — không cần server gì cả."""

    @staticmethod
    def save(session: UniversalSession) -> Path:
        """Lưu session ra file JSON."""
        sessions_dir = _get_sessions_dir()
        filename = f"{session.id}.json"
        path = sessions_dir / filename

        with open(path, "w", encoding="utf-8") as f:
            f.write(session.to_json(indent=2))

        return path

    @staticmethod
    def load(session_id: str) -> UniversalSession:
        """Đọc session từ file JSON."""
        sessions_dir = _get_sessions_dir()
        path = sessions_dir / f"{session_id}.json"

        if not path.exists():
            # Try with different patterns
            for pattern in (f"{session_id}.json", f"sess-{session_id}.json",
                            f"claude-{session_id}.json", f"qwen-{session_id}.json",
                            f"clip-{session_id}.json"):
                p = sessions_dir / pattern
                if p.exists():
                    path = p
                    break
            else:
                raise FileNotFoundError(f"Session not found: {session_id}")

        with open(path, "r", encoding="utf-8") as f:
            return UniversalSession.from_json(f.read())

    @staticmethod
    def list() -> list[UniversalSession]:
        """List all saved sessions."""
        sessions_dir = _get_sessions_dir()
        results = []

        for json_file in sorted(sessions_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    results.append(UniversalSession.from_json(f.read()))
            except Exception:
                continue

        return results

    @staticmethod
    def delete(session_id: str) -> bool:
        """Xóa session."""
        sessions_dir = _get_sessions_dir()
        for pattern in (f"{session_id}.json", f"sess-{session_id}.json"):
            path = sessions_dir / pattern
            if path.exists():
                path.unlink()
                return True
        return False

    @staticmethod
    def exists(session_id: str) -> bool:
        """Kiểm tra session có tồn tại không."""
        sessions_dir = _get_sessions_dir()
        for pattern in (f"{session_id}.json", f"sess-{session_id}.json",
                        f"claude-{session_id}.json", f"qwen-{session_id}.json",
                        f"clip-{session_id}.json"):
            if (sessions_dir / pattern).exists():
                return True
        return False


# ─────────────────────────────────────────────────────────────
# Redis Cache (Optional)
# ─────────────────────────────────────────────────────────────

class RedisCache:
    """
    Optional Redis backend — opt-in via config.
    Dùng khi user muốn cache có TTL thay vì lưu vĩnh viễn.
    """

    def __init__(self, config: dict | None = None):
        self.enabled = False
        self._client = None

        if config:
            cfg = config.get("storage", {}).get("redis", {})
            self.enabled = cfg.get("enabled", False)

        if self.enabled:
            try:
                import redis
                cfg = config.get("storage", {}).get("redis", {})
                self._client = redis.Redis(
                    host=cfg.get("host", "localhost"),
                    port=cfg.get("port", 6379),
                    password=cfg.get("password"),
                    decode_responses=True,
                )
                # Test connection
                self._client.ping()
            except Exception as e:
                print(f"[AiMem] Redis connection failed: {e}. Falling back to file storage.")
                self.enabled = False

    def cache_compressed(self, session_id: str, compressed_data: dict, ttl: int = 3600) -> None:
        """Lưu compressed session vào Redis với TTL."""
        if not self.enabled:
            return
        key = f"aimem:compressed:{session_id}"
        self._client.setex(key, ttl, json.dumps(compressed_data))

    def get_compressed(self, session_id: str) -> dict | None:
        """Đọc compressed session từ Redis."""
        if not self.enabled:
            return None
        key = f"aimem:compressed:{session_id}"
        data = self._client.get(key)
        if data:
            return json.loads(data)
        return None

    def clear_expired(self) -> int:
        """Xóa các key đã hết hạn."""
        if not self.enabled:
            return 0
        keys = self._client.keys("aimem:compressed:*")
        if keys:
            return self._client.delete(*keys)
        return 0
