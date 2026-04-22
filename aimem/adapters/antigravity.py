import os
import sys
import json
import sqlite3
from pathlib import Path
from typing import List, Optional

from ..models import UniversalSession, Message, SessionMetadata

class AntigravityAdapter:
    """Adapter for Antigravity AI Editor."""
    
    @property
    def name(self) -> str:
        return "antigravity"
        
    def is_available(self) -> bool:
        if os.name == "nt":
            appdata = os.environ.get("APPDATA", "")
            return (Path(appdata) / "Antigravity").exists()
        else:
            return (Path.home() / ".config" / "Antigravity").exists() or (Path.home() / "Library" / "Application Support" / "Antigravity").exists()
            
    def _get_base_path(self) -> Path:
        if os.name == "nt":
            appdata = os.environ.get("APPDATA", "")
            return Path(appdata) / "Antigravity" / "User"
        elif sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "Antigravity" / "User"
        else:
            return Path.home() / ".config" / "Antigravity" / "User"

    def list_sessions(self) -> List[dict]:
        # TODO: Reverse engineer Antigravity's workspaceStorage/state.vscdb
        return []

    def export(self, session_id: str) -> UniversalSession:
        raise NotImplementedError("Antigravity export is currently under research (reverse engineering storage).")

    def inject(self, session: UniversalSession) -> Path:
        raise NotImplementedError("Antigravity inject is currently under research (reverse engineering storage).")
