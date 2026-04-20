# AiMem — Báo Cáo Sản Phẩm Hoàn Chỉnh

> **Version:** 0.2.0
> **Repository:** `https://github.com/ThangTo/AiMem`
> **PyPI:** `https://pypi.org/project/aimem-cli/`
> **Last Updated:** 2026-04-20

---

## I. Tổng Quan Sản Phẩm

### AiMem là gì?

**AiMem (AI Memory Switcher)** là một công cụ CLI giúp **lưu trữ, chuyển giao bối cảnh (context) liền mạch giữa các AI Agent** — Claude, Gemini, Qwen, OpenCode, Aider, Continue.dev, Codex và bất kỳ nguồn nào khác.

### Vấn đề nó giải quyết

```
Bạn đang code với Claude Code...
──────────────────────────────────────────
│ Claude: Đang sửa bug authentication...   │
│ Đến 11 giờ đêm — Claude hết token!       │
│ Hoặc bị rate-limit                      │
│ Bạn cần chuyển sang Gemini              │
│                                          │
│ LÀM SAO?                                │
│ → Copy toàn bộ chat? Mệt               │
│ → Nhắc lại từ đầu? Mất 30 phút          │
│ → Mất luồng suy nghĩ?                   │
──────────────────────────────────────────

AI MEM GIẢI QUYẾT: 3 GIÂY THÔI
──────────────────────────────────────────
$ aimem save --from claude
$ aimem load sess-abc --to gemini
# Paste vào Gemini — có nguyên context
```

### Kiến trúc cốt lõi

```
Claude (JSONL) ──▶ Adapter ──▶ UniversalSession ──▶ Storage ──▶ Adapter ──▶ Gemini (Markdown)
Qwen (JSON)      [.py]       [JSON định dạng]   [~/.aimem/]  [.py]       Claude, Qwen, v.v.
Aider (MD)                      ↑
Continue (SQLite)           Định dạng TRUNG GIAN
Clipboard                     cho TẤT CẢ agents
```

---

## II. Thành Quả Từng Phase

---

### ✅ Phase 1 — MVP: Core Adapters

**Thời gian:** Session đầu tiên
**Trạng thái:** Hoàn thành 100%

| Adapter | Đọc từ | Ghi cho | Sessions trên máy |
|---------|---------|---------|-------------------|
| **Claude** | `~/.claude/projects/*/*.jsonl` | Claude Code, Markdown | 79 sessions |
| **Qwen** | `~/.qwen/tmp/*/logs.json` | Qwen CLI, Markdown | 2 sessions |
| **Gemini** | `~/.gemini/tmp/*/chats/*.json` | Gemini CLI, Markdown | 6 sessions |
| **OpenCode** | `~/.opencode/sessions/*.json` | OpenCode CLI, Markdown | 8 sessions |
| **Codex** | `~/.codex/sessions/*.jsonl` | Codex CLI, Markdown | — |
| **Aider** | `~/.aider.chat.history.md` | Markdown | — |
| **Continue.dev** | `~/.continue/sessions.db` (SQLite) | Continue.dev | — |
| **Clipboard** | System clipboard | Bất kỳ đâu | Luôn sẵn sàng |

**Kết quả:** User có thể `save` từ Claude, Qwen, Gemini, OpenCode, Codex, Aider, Continue, hoặc clipboard. Tất cả được chuyển thành **UniversalSession** (JSON) — định dạng trung gian.

**Bugs đã fix trong Phase 1:**
- Config set command bị parse sai (`"set"` thừa trong config)
- Load config không sanitize stale keys
- Double return trong `cmd_config`
- Session interactive selection (tự động hỏi chọn khi nhiều sessions)

---

### ✅ Phase 2.5 — Auto-Inject (Mới!)

**Thời gian:** Session hiện tại
**Trạng thái:** Hoàn thành 100%

Tính năng `--inject` cho phép **ghi trực tiếp session vào storage của agent đích**, không cần copy-paste thủ công.

| Adapter | Inject? | Storage Path | Cách Resume |
|---------|---------|--------------|-------------|
| **Claude** | ✅ | `~/.claude/projects/{project}/{session}.jsonl` | `claude --resume` |
| **Gemini** | ✅ | `~/.gemini/tmp/{project}/chats/session-*.json` | `gemini --resume latest` |
| **Qwen** | ✅ | `~/.qwen/tmp/{hash}/logs.json` | `qwen --continue` |
| **Codex** | ✅ | `~/.codex/sessions/{date}/rollout-*.jsonl` | `codex --resume` |
| **OpenCode** | ✅ | Export JSON → `opencode import` | `opencode -s {session_id}` |
| **Aider** | ❌ | Markdown-based, không có storage | Paste thủ công |
| **Continue.dev** | ❌ | SQLite phức tạp | Paste thủ công |

**Cách sử dụng:**

```bash
# Inject vào Gemini (tự động xuất hiện trong session list)
aimem load claude-62d520bb --to gemini --inject
gemini --resume latest

# Inject vào Claude
aimem load gemini-xxx --to claude --inject
cd <project_path>
claude --resume

# Inject vào OpenCode (gọi opencode import)
aimem load claude-62d520bb --to opencode --inject
opencode -s ses_xxx
```

**Lưu ý kỹ thuật — OpenCode Schema:**

OpenCode có validation schema khác nhau cho `user` vs `assistant` messages:

| Field | User Message | Assistant Message |
|-------|--------------|-------------------|
| `model` | `{"providerID": "...", "modelID": "..."}` (nested) | Không có |
| `modelID` | Không có | `"glm-5:cloud"` (flat string) |
| `providerID` | Không có | `"ollama"` (flat string) |
| `summary` | `{"diffs": []}` (object) | Không có |
| `mode` | Không có | `"build"` |
| `path` | Không có | `{"cwd": "...", "root": "/"}` |
| `tokens` | Không có | Full token object |
| `finish` | Không có | `"stop"` |

---

### ⚠️ Phase 2 — LLM Compression

**Thời gian:** Đang triển khai
**Trạng thái:** Engine hoàn thành, đợi API key valid

| Thành phần | Trạng thái |
|------------|------------|
| CompressionEngine | ✅ Code hoàn chỉnh |
| Groq integration (`llama-3.1-8b-instant`) | ⚠️ 403 Forbidden (key hết hạn) |
| Gemini Flash integration | ✅ Code sẵn sàng |
| CompressedSession schema | ✅ |

**Cơ chế nén:**

```
Session gốc: ~21,480 tokens
                    ↓ LLM call (Groq/Gemini Flash)
Session nén: ~800-2,000 tokens
                    ↓ Giảm ~95% kích thước
Output: {
  "current_goal": "Fix authentication bug",
  "latest_code": [{"path": "auth.py", "content": "..."}],
  "current_errors": ["TypeError: undefined"],
  "key_decisions": ["Dùng JWT thay vì session"],
  "todo_list": ["Viết test", "Deploy staging"]
}
```

**Cách bật:**
```bash
aimem config set compression.enabled true
aimem config set compression.api_key YOUR_GROQ_KEY
aimem config set compression.provider groq
```

---

### ✅ Phase 3 — Output Adapters

**Thời gian:** Session hiện tại
**Trạng thái:** Hoàn thành 100%

| Format | Mục đích | Tự động copy | Inject? |
|--------|---------|-------------|---------|
| `markdown` | Dán vào web UI, Slack, docs | ✅ | ❌ |
| `claude` | Claude Code CLI | ✅ | ✅ |
| `gemini` | Gemini CLI | ✅ | ✅ |
| `qwen` | Qwen CLI | ✅ | ✅ |
| `codex` | Codex CLI | ✅ | ✅ |
| `opencode` | OpenCode CLI | ✅ | ✅ |
| `continue` | Continue.dev (VS Code) | ✅ | ❌ |
| `prompt` | API calls, custom injection | ✅ | ❌ |

**Noise Filtering tự động:**
- `[API Error]` system messages → skip
- HTML error pages (WeasyPrint, GTK) → skip
- pip/npm upgrade spam → skip hoặc collapse
- Exit code errors từ external tools → skip
- Long tool outputs (>4000 chars) → trim + ghi chú

---

### ✅ Phase 4 — Context Management

**Thời gian:** Session hiện tại
**Trạng thái:** Hoàn thành 100%

| Tính năng | Mô tả | Lệnh |
|-----------|--------|------|
| **Context Analysis** | Token count, warnings, model-specific advice | `--analyze` |
| **Smart Chunking** | Tự động chia session thành chunks nhỏ | `--chunk` |
| **Auto-trim on Save** | Loại bỏ API errors, duplicates, noise | Tự động |
| **Session Merge** | Gộp 2+ sessions (simple hoặc smart) | `merge` |

**Context Limits Database:**

| Model | Context Limit | Recommended |
|-------|-------------|-------------|
| Claude Sonnet 4.6 | 200,000 | 180,000 |
| Gemini 2.0 Flash | 1,000,000 | 800,000 |
| GPT-4o | 128,000 | 100,000 |
| Qwen 2.5 Coder 32B | 32,768 | 25,000 |
| Llama 3.1 8B (Groq) | 128,000 | 100,000 |

---

## III. Tổng Thể Sản Phẩm

```
╔══════════════════════════════════════════════════════════════╗
║                      AI MEM — FINAL BUILD                   ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  Files:            17 Python modules + README + pyproject.tom║
║  Adapters:         8 source adapters (Claude, Gemini, Qwen,   ║
║                    OpenCode, Codex, Aider, Continue, Clip)   ║
║  Output formats:    8 formatters + inject support           ║
║  Commands:          7 commands + --inject flag (NEW)         ║
║  Context limits:   12 models in database                    ║
║  Sessions found:    95+ (on user's machine)                  ║
║                                                              ║
║  Dependencies:      pyperclip (optional, 1 dep)             ║
║  Storage:           File-based (no server needed)            ║
║  Compression:       Optional LLM compression                 ║
║  Redis:             Optional cache (opt-in)                 ║
║                                                              ║
╠══════════════════════════════════════════════════════════════╣
║  Phase 1: ✅ MVP Adapters      │  Phase 2: ⚠️ Compression   ║
║  Phase 2.5: ✅ Auto-Inject (NEW)│  Phase 3: ✅ Output Formats║
║  Phase 4: ✅ Context Mgmt       │  Phase 5: 📋 VS Code Ext  ║
╚══════════════════════════════════════════════════════════════╝
```
╔══════════════════════════════════════════════════════════════╗
║                      AI MEM — FINAL BUILD                   ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  Files:            14 Python modules + README + pyproject.toml║
║  Adapters:         6 source adapters                        ║
║  Output formats:    6 formatters                            ║
║  Commands:          7 commands                               ║
║  Context limits:   12 models in database                    ║
║  Sessions found:    86+ (on user's machine)                  ║
║                                                              ║
║  Dependencies:      pyperclip (optional, 1 dep)             ║
║  Storage:           File-based (no server needed)            ║
║  Compression:       Optional LLM compression                 ║
║  Redis:             Optional cache (opt-in)                 ║
║                                                              ║
╠══════════════════════════════════════════════════════════════╣
║  Phase 1: ✅ MVP Adapters    │  Phase 2: ⚠️ Compression     ║
║  Phase 3: ✅ Output Formats  │  Phase 4: ✅ Context Mgmt     ║
║  Phase 5: 📋 VS Code Extension                                 ║
╚══════════════════════════════════════════════════════════════╝
```

---

## IV. Hướng Dẫn Sử Dụng Chi Tiết

### 1. Cài đặt

```bash
# Cách 1: Chạy trực tiếp (không cần install)
python d:/Project/AiMem/aimem_main.py --help

# Cách 2: Install via pip
pip install aimem

# Cách 3: Install từ source
cd d:/Project/AiMem
pip install -e .
aimem --help
```

### 2. Khởi tạo (chỉ cần 1 lần)

```bash
aimem init
```

Tạo file config tại `~/.aimem/config.json`

### 3. Kiểm tra agent nào có sẵn

```bash
aimem list --agents

# Kết quả:
#   Claude Code: [OK] Available (78 sessions)
#   Qwen CLI:    [OK] Available (2 sessions)
#   Gemini CLI:  [OK] Available (6 sessions)
#   Aider:      [X] Not found
#   Continue.dev: [X] Not found
#   Clipboard:  [OK] Available
```

### 4. Save session

```bash
# Save từ Claude (tự động hỏi chọn session nếu có nhiều)
aimem save --from claude

# Save session cụ thể
aimem save --from claude --session-id 62d520bb

# Save từ clipboard
aimem save --from clipboard

# Save từ Qwen
aimem save --from qwen

# Save từ Gemini
aimem save --from gemini

# Save từ OpenCode (MỚI!)
aimem save --from opencode

# Save từ Codex (MỚI!)
aimem save --from codex

# Save từ Aider
aimem save --from aider

# Save từ Continue.dev
aimem save --from continue
```

### 5. Load session

```bash
# Load as Markdown (mặc định, tự động copy clipboard)
aimem load claude-62d520bb

# Load cho Claude Code
aimem load claude-62d520bb --to claude

# Load cho Gemini CLI
aimem load claude-62d520bb --to gemini

# Load cho Qwen CLI
aimem load claude-62d520bb --to qwen

# Load cho OpenCode CLI (MỚI!)
aimem load claude-62d520bb --to opencode

# Load cho Codex CLI (MỚI!)
aimem load claude-62d520bb --to codex

# Load cho Continue.dev
aimem load claude-62d520bb --to continue

# Ghi ra file thay vì stdout
aimem load claude-62d520bb --to gemini -o context.md

# Load với phân tích context
aimem load claude-62d520bb --to gemini --analyze

# Load với tự động chia chunks nếu quá lớn
aimem load claude-62d520bb --to qwen --chunk
```

### 5.1. Auto-Inject (MỚI!)

```bash
# Inject TRỰC TIẾP vào storage của agent đích
# Không cần copy-paste, session tự động xuất hiện trong session list

# Inject vào Gemini
aimem load claude-62d520bb --to gemini --inject
gemini --resume latest

# Inject vào Claude
aimem load claude-62d520bb --to claude --inject
claude --resume

# Inject vào Qwen
aimem load claude-62d520bb --to qwen --inject
qwen --continue

# Inject vào OpenCode
aimem load claude-62d520bb --to opencode --inject
opencode -s ses_xxx

# Inject vào Codex
aimem load claude-62d520bb --to codex --inject
codex --resume
```

### 6. Phân tích context (không load)

```bash
# Xem session có fit vào target không
aimem load claude-62d520bb --to qwen --analyze
```

### 7. Merge sessions

```bash
# Gộp 2 sessions đơn giản
aimem merge claude-62d520bb qwen-38650866

# Smart merge (tự động deduplicate, gộp goals, combine todos)
aimem merge claude-62d520bb qwen-38650866 --smart

# Smart merge + auto-trim cho Gemini
aimem merge claude-62d520bb qwen-38650866 --smart --to gemini
```

### 8. Quản lý sessions

```bash
# Xem tất cả sessions đã save
aimem list

# Xóa session
aimem delete claude-62d520bb

# Xem có bao nhiêu sessions ở mỗi agent
aimem list --agents
```

### 9. Cấu hình

```bash
# Xem config hiện tại
aimem config

# Bật LLM compression
aimem config set compression.enabled true
aimem config set compression.api_key YOUR_GROQ_KEY
aimem config set compression.provider groq

# Đổi sang Gemini compression
aimem config set compression.provider gemini
aimem config set compression.api_key YOUR_GEMINI_KEY

# Bật Redis cache (optional)
aimem config set storage.redis.enabled true
aimem config set storage.redis.host localhost
aimem config set storage.redis.ttl 3600

# Đổi output format mặc định
aimem config set output.format markdown
aimem config set output.clipboard_auto true
```

---

## V. Công Dụng Thực Tế

### Use Case 1: Hết token Claude → Chuyển sang Gemini

```
Bạn: "Claude hết token rồi, tôi cần chuyển sang Gemini"
↓
$ aimem save --from claude
$ aimem load sess-abc --to gemini
↓
Paste vào Gemini → Gemini biết nguyên context, tiếp tục ngay
```

### Use Case 2: Context quá lớn cho Qwen

```
Bạn: "Qwen chỉ có 32K context, session tôi 50K tokens"
↓
$ aimem load sess-abc --to qwen --analyze
# → ⚠️ Session EXCEEDS Qwen limit
↓
$ aimem load sess-abc --to qwen --chunk
# → 📦 CHUNK 1/2 (25K tokens)
# → 📦 CHUNK 2/2 (25K tokens)
# Load từng phần, Qwen vẫn handle được
```

### Use Case 3: Merge sessions từ nhiều tools

```
Bạn: "Tôi code ở Claude + Qwen + Aider, muốn gộp lại"
↓
$ aimem save --from claude
$ aimem save --from qwen
$ aimem save --from aider
$ aimem merge sess1 sess2 sess3 --smart
↓
→ Smart-merged: deduplicate messages, gộp goals, combine todos
→ Load 1 lần vào Claude, có context từ cả 3 tools
```

### Use Case 4: Copy từ web UI (Claude.ai, Gemini web)

```
Bạn: "Tôi đang chat ở claude.ai trên web, muốn chuyển sang CLI"
↓
1. Copy toàn bộ chat text
2. $ aimem save --from clipboard
3. $ aimem load sess-abc --to gemini
↓
Paste vào Gemini CLI → Có nguyên context
```

### Use Case 5: Nén session lớn

```
Bạn: "Session của tôi 100K tokens, Claude limit 200K nhưng muốn nhỏ gọn"
↓
$ aimem save --from claude --compress
# → Compressed: 100,000 tokens → 2,000 tokens
# → LLM call qua Groq (~$0.001)
# → Còn lại: goal, latest code, errors, decisions, todos
```

---

## VI. So Sánh Với Giải Pháp Khác

| Tiêu chí | AiMem | ChatGPT Shared Links | Manual Copy-Paste |
|-----------|-------|---------------------|-------------------|
| Chuyển context giữa agents | ✅ | ❌ | ❌ |
| Không cần server | ✅ | ❌ (OpenAI server) | ✅ |
| Zero config | ✅ | N/A | ✅ |
| LLM Compression | ✅ (opt-in) | ❌ | ❌ |
| Smart chunking | ✅ | ❌ | ❌ |
| Session merge | ✅ | ❌ | ❌ |
| Nhiều agent sources | ✅ (6 adapters) | ❌ | ❌ |
| Open source | ✅ | ❌ | N/A |

---

## VII. Cấu Trúc Project

```
d:\Project\AiMem\
├── aimem/
│   ├── __init__.py
│   ├── cli.py                  # 7 commands: init, save, load, list, merge, config, delete
│   ├── models.py               # UniversalSession, Message, CompressedSession, SessionMetadata
│   ├── storage.py              # FileStorage (default) + RedisCache (opt-in)
│   ├── compression.py           # Groq / Gemini LLM compression engine
│   ├── context_manager.py       # Phase 4: chunking, merge, auto-trim, analysis
│   └── adapters/
│       ├── __init__.py
│       ├── claude.py           # Claude Code (JSONL) - export + inject
│       ├── qwen.py             # Qwen CLI (JSON) - export + inject
│       ├── gemini.py           # Gemini CLI (JSON) - export + inject
│       ├── opencode.py         # OpenCode CLI (JSON) - export + inject (MỚI!)
│       ├── codex.py            # Codex CLI (JSONL) - export + inject (MỚI!)
│       ├── aider.py            # Aider (Markdown) - export only
│       ├── continue_dev.py     # Continue.dev (SQLite + JSON) - export only
│       ├── clipboard.py        # System clipboard
│       └── output/
│           └── __init__.py     # 8 formatters + inject handlers
├── aimem_main.py              # Entry point (chạy trực tiếp không cần install)
├── pyproject.toml              # Python packaging
├── README.md                  # Tài liệu chính
└── REPORT.md                  # Báo cáo này
```

---

## VIII. Tiếp Theo — Phase 5

**VS Code Extension** — biến AiMem thành plugin trong VS Code:

```
VS Code
├─ Side panel: "AiMem Context"
│   ├─ List saved sessions
│   ├─ One-click "Continue in Gemini"
│   └─ Auto-sync current Claude session
├─ Command palette:
│   ├─ AiMem: Save current context
│   ├─ AiMem: Load context to Gemini
│   └─ AiMem: Analyze context fit
└─ Status bar: Token count + fit indicator
```

---

## IX. Quick Reference Card

```
╔════════════════════════════════════════════════════════════╗
║  AIMEM QUICK REFERENCE                                     ║
╠════════════════════════════════════════════════════════════╣
║  aimem init                          Setup                 ║
║  aimem save --from claude            Save session        ║
║  aimem load sess-abc --to gemini     Load + transfer     ║
║  aimem load sess --to qwen --analyze Check fit            ║
║  aimem load sess --to qwen --chunk   Split if needed     ║
║  aimem merge sess1 sess2 --smart     Merge sessions      ║
║  aimem list                           View saved          ║
║  aimem list --agents                  Check agents       ║
║  aimem config set compression.enabled true              ║
║  aimem delete sess-abc               Delete              ║
╚════════════════════════════════════════════════════════════╝
```