import os
import json
import sqlite3
import uuid
import time
import urllib.parse
from pathlib import Path
from typing import List, Optional
from datetime import datetime, timezone

from ..models import UniversalSession, Message, SessionMetadata

class CursorAdapter:
    """Adapter for Cursor AI Editor."""
    
    @property
    def name(self) -> str:
        return "cursor"
        
    def is_available(self) -> bool:
        db_path = self._get_db_path()
        return db_path is not None and db_path.exists()
            
    def _get_db_path(self) -> Optional[Path]:
        if os.name == "nt":
            appdata = os.environ.get("APPDATA", "")
            return Path(appdata) / "Cursor" / "User" / "globalStorage" / "state.vscdb"
        elif sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / "Cursor" / "User" / "globalStorage" / "state.vscdb"
        else:
            return Path.home() / ".config" / "Cursor" / "User" / "globalStorage" / "state.vscdb"

    def _get_workspace_db_path(self, project_path: str) -> Optional[Path]:
        if not project_path:
            return None
            
        if os.name == "nt":
            appdata = os.environ.get("APPDATA", "")
            ws_storage = Path(appdata) / "Cursor" / "User" / "workspaceStorage"
        elif sys.platform == "darwin":
            ws_storage = Path.home() / "Library" / "Application Support" / "Cursor" / "User" / "workspaceStorage"
        else:
            ws_storage = Path.home() / ".config" / "Cursor" / "User" / "workspaceStorage"
            
        if not ws_storage.exists():
            return None
            
        target_posix = Path(project_path).resolve().as_posix().lower()
        
        for ws_dir in ws_storage.glob("*"):
            ws_json = ws_dir / "workspace.json"
            if ws_json.exists():
                try:
                    with open(ws_json, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        folder_uri = data.get("folder", "")
                        folder_unquoted = urllib.parse.unquote(folder_uri).lower()
                        if target_posix in folder_unquoted:
                            db_path = ws_dir / "state.vscdb"
                            if db_path.exists():
                                return db_path
                except Exception:
                    pass
        return None

    def list_sessions(self) -> List[dict]:
        db_path = self._get_db_path()
        if not db_path or not db_path.exists():
            return []

        sessions = []
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            
            # Find all composers
            c.execute("SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%'")
            for key, val in c.fetchall():
                try:
                    data = json.loads(val)
                    composer_id = data.get("composerId")
                    if not composer_id:
                        continue
                        
                    headers = data.get("fullConversationHeadersOnly", [])
                    if not headers:
                        continue
                        
                    # Get the first user bubble to extract title
                    first_bubble_id = headers[0].get("bubbleId")
                    c.execute("SELECT value FROM cursorDiskKV WHERE key = ?", (f"bubbleId:{composer_id}:{first_bubble_id}",))
                    bubble_row = c.fetchone()
                    
                    title = f"Cursor Composer {composer_id[:8]}"
                    if bubble_row:
                        b_data = json.loads(bubble_row[0])
                        text = b_data.get("text") or b_data.get("richText") or ""
                        if text:
                            title = text[:50] + "..." if len(text) > 50 else text

                    sessions.append({
                        "session_id": composer_id,
                        "title": title,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "total_messages": len(headers),
                        "source": "cursor"
                    })
                except Exception:
                    continue
                    
        except Exception as e:
            print(f"Error listing Cursor sessions: {e}")
        finally:
            if 'conn' in locals():
                conn.close()
                
        return sessions

    def export(self, session_id: str) -> UniversalSession:
        db_path = self._get_db_path()
        if not db_path or not db_path.exists():
            raise FileNotFoundError("Cursor global storage DB not found.")

        conn = sqlite3.connect(db_path)
        try:
            c = conn.cursor()
            c.execute("SELECT value FROM cursorDiskKV WHERE key = ?", (f"composerData:{session_id}",))
            row = c.fetchone()
            if not row:
                raise ValueError(f"Cursor composer session {session_id} not found.")
                
            composer_data = json.loads(row[0])
            headers = composer_data.get("fullConversationHeadersOnly", [])
            
            messages = []
            for header in headers:
                b_id = header.get("bubbleId")
                c.execute("SELECT value FROM cursorDiskKV WHERE key = ?", (f"bubbleId:{session_id}:{b_id}",))
                b_row = c.fetchone()
                if b_row:
                    b_data = json.loads(b_row[0])
                    role = "user" if b_data.get("type") == 1 else "assistant"
                    text = b_data.get("text") or b_data.get("richText") or ""
                    if text:
                        messages.append(Message(role=role, content=text))
                        
            if not messages:
                raise ValueError(f"No messages found for Cursor session {session_id}.")

            ts = datetime.now(timezone.utc).isoformat()
            metadata = SessionMetadata(
                source_agent="cursor",
                token_count=sum(len(m.content) // 4 for m in messages),
                project_path=""
            )

            return UniversalSession(
                id=f"cursor-{session_id[:8]}",
                source="cursor",
                messages=messages,
                metadata=metadata,
                created_at=ts,
                updated_at=ts,
                tags=["cursor"]
            )
        finally:
            conn.close()

    def inject(self, session: UniversalSession) -> Path:
        db_path = self._get_db_path()
        if not db_path or not db_path.exists():
            raise FileNotFoundError("Cursor global storage DB not found.")

        composer_id = str(uuid.uuid4())
        
        headers = []
        bubbles_to_insert = []
        conversation_map = {}
        
        for msg in session.messages:
            bubble_id = str(uuid.uuid4())
            msg_type = 1 if msg.role == "user" else 2
            
            headers.append({
                "bubbleId": bubble_id,
                "type": msg_type
            })

            conversation_map[bubble_id] = {
                "bubbleId": bubble_id,
                "type": msg_type,
                "checkpoints": []
            }
            
            bubble_data = {
              "_v": 3,
              "type": msg_type,
              "approximateLintErrors": [],
              "lints": [],
              "codebaseContextChunks": [],
              "commits": [],
              "pullRequests": [],
              "attachedCodeChunks": [],
              "assistantSuggestedDiffs": [],
              "gitDiffs": [],
              "interpreterResults": [],
              "images": [],
              "attachedFolders": [],
              "attachedFoldersNew": [],
              "bubbleId": bubble_id,
              "userResponsesToSuggestedCodeBlocks": [],
              "suggestedCodeBlocks": [],
              "diffsForCompressingFiles": [],
              "relevantFiles": [],
              "toolResults": [],
              "notepads": [],
              "capabilities": [],
              "capabilityStatuses": {},
              "multiFileLinterErrors": [],
              "diffHistories": [],
              "recentLocationsHistory": [],
              "recentlyViewedFiles": [],
              "isAgentic": False,
              "fileDiffTrajectories": [],
              "existedSubsequentTerminalCommand": False,
              "existedPreviousTerminalCommand": False,
              "docsReferences": [],
              "webReferences": [],
              "aiWebSearchResults": [],
              "requestId": str(uuid.uuid4()),
              "attachedFoldersListDirResults": [],
              "humanChanges": [],
              "attachedHumanChanges": False,
              "summarizedComposers": [],
              "cursorRules": [],
              "contextPieces": [],
              "editTrailContexts": [],
              "allThinkingBlocks": [],
              "diffsSinceLastApply": [],
              "deletedFiles": [],
              "supportedTools": [],
              "tokenCount": {"tokens": 0, "totalTokens": 0},
              "attachedFileCodeChunksMetadataOnly": [],
              "consoleLogs": [],
              "uiElementPicked": [],
              "isRefunded": False,
              "knowledgeItems": [],
              "documentationSelections": [],
              "externalLinks": [],
              "useWeb": False,
              "projectLayouts": [],
              "unifiedMode": 1 if msg_type == 1 else 2,
              "capabilityContexts": [],
              "todos": [],
              "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
              "isQuickSearchQuery": False,
              "mcpDescriptors": [],
              "workspaceUris": [],
              "conversationState": "",
              "text": msg.content,
              "modelInfo": {"model": "gpt-4"},
              "isNudge": False,
              "skipRendering": False,
              "isPlanExecution": False,
              "editToolSupportsSearchAndReplace": True,
              "workspaceProjectDir": "",
              "context": {},
              "checkpointId": str(uuid.uuid4()),
              "toolFormerData": {}
            }
            
            if msg_type == 1:
                # User bubbles need valid Lexical JSON in richText
                lexical_json = {
                    "root": {
                        "children": [
                            {
                                "children": [
                                    {
                                        "detail": 0,
                                        "format": 0,
                                        "mode": "normal",
                                        "style": "",
                                        "text": msg.content,
                                        "type": "text",
                                        "version": 1
                                    }
                                ],
                                "direction": "ltr",
                                "format": "",
                                "indent": 0,
                                "type": "paragraph",
                                "version": 1
                            }
                        ],
                        "direction": "ltr",
                        "format": "",
                        "indent": 0,
                        "type": "root",
                        "version": 1
                    }
                }
                bubble_data["richText"] = json.dumps(lexical_json)
            else:
                # Assistant bubbles shouldn't have richText, but might have codeBlocks
                bubble_data["codeBlocks"] = []
                
            bubbles_to_insert.append((f"bubbleId:{composer_id}:{bubble_id}", json.dumps(bubble_data)))

        composer_data = {
          "_v": 10,
          "composerId": composer_id,
          "richText": "",
          "hasLoaded": True,
          "text": "",
          "fullConversationHeadersOnly": headers,
          "conversationMap": {},
          "status": "completed",
          "context": {
              "composers": [], "quotes": [], "selectedCommits": [], "selectedPullRequests": [],
              "selectedImages": [], "folderSelections": [], "fileSelections": [], "selections": [],
              "terminalSelections": [], "selectedDocs": [], "externalLinks": [], "cursorRules": [],
              "cursorCommands": [], "uiElementSelections": [], "consoleLogs": [], "ideEditorsState": True,
              "mentions": { "composers": {}, "quotes": {}, "selectedCommits": {}, "selectedPullRequests": {}, "gitDiff": [], "gitDiffFromBranchToMain": [], "selectedImages": {}, "useWeb": [], "folderSelections": {}, "fileSelections": {}, "terminalFiles": {}, "selections": {}, "terminalSelections": {} }
          }
        }

        conn = sqlite3.connect(db_path)
        try:
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO cursorDiskKV (key, value) VALUES (?, ?)", 
                     (f"composerData:{composer_id}", json.dumps(composer_data)))
                     
            c.executemany("INSERT OR REPLACE INTO cursorDiskKV (key, value) VALUES (?, ?)", bubbles_to_insert)
            conn.commit()
        finally:
            conn.close()

        project_path = session.metadata.project_path or os.getcwd()
        ws_db = self._get_workspace_db_path(project_path)
        
        if ws_db:
            try:
                ws_conn = sqlite3.connect(ws_db)
                ws_c = ws_conn.cursor()
                ws_c.execute("SELECT value FROM ItemTable WHERE key = 'composer.composerData'")
                row = ws_c.fetchone()
                
                title = session.messages[0].content[:50] + "..." if session.messages else f"AiMem Injected {composer_id[:8]}"
                
                new_composer_entry = {
                    "type": "head",
                    "composerId": composer_id,
                    "name": title,
                    "lastUpdatedAt": int(time.time() * 1000),
                    "createdAt": int(time.time() * 1000),
                    "unifiedMode": "agent",
                    "forceMode": "edit",
                    "hasUnreadMessages": False,
                    "contextUsagePercent": 0,
                    "totalLinesAdded": 0,
                    "totalLinesRemoved": 0,
                    "filesChangedCount": 0,
                    "subtitle": "Injected by AiMem",
                    "isArchived": False,
                    "isDraft": False,
                    "isWorktree": False,
                    "isSpec": False,
                    "isBestOfNSubcomposer": False,
                    "numSubComposers": 0,
                    "referencedPlans": [],
                    "createdOnBranch": "main",
                    "committedToBranch": "main",
                    "hasBlockingPendingActions": False
                }
                
                if row:
                    ws_data = json.loads(row[0])
                    all_composers = ws_data.get("allComposers", [])
                    all_composers.insert(0, new_composer_entry)
                    ws_data["allComposers"] = all_composers
                    # Force focus on the new session
                    ws_data["selectedComposerIds"] = [composer_id]
                    ws_data["lastFocusedComposerIds"] = [composer_id]
                else:
                    ws_data = {
                        "allComposers": [new_composer_entry],
                        "selectedComposerIds": [composer_id],
                        "lastFocusedComposerIds": [composer_id],
                        "hasMigratedComposerData": True,
                        "hasMigratedMultipleComposers": True
                    }
                    
                ws_c.execute("INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)", 
                            ("composer.composerData", json.dumps(ws_data)))
                ws_conn.commit()
                ws_conn.close()
                print(f"[i] Updated Cursor workspace history: {ws_db.parent.name}")
            except Exception as e:
                print(f"Warning: Could not update workspace composer history: {e}")
        else:
            print(f"[!] Warning: Could not find Cursor workspace database for path: {project_path}")
            print("    Try opening the folder in Cursor first, then run inject.")

        # Return a fake path representing the composer ID so CLI can use it
        return Path(composer_id)