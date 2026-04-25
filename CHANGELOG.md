# Changelog

All notable changes to AiMem will be documented in this file.

## [0.2.8] - 2026-04-25

### Fixed
- Fixed OpenCode injected sessions so new prompts are not swallowed and LLM calls continue normally.
- Fixed OpenCode imported message timestamps so new user chats are not inserted between older imported messages.
- Restored the TUI post-inject resume prompt and terminal launcher for OpenCode.
- Fixed Codex CLI injection by ensuring base instructions and visible transcript events are written.
- Fixed Codex VS Code launch flow to use the extension deep link instead of opening a raw URI file.
- Fixed CLI success exit behavior while preserving internal TUI result passing.

### Added
- Added `--no-compress` to explicitly disable compression for one run.
- Added regression coverage for OpenCode injection ordering and context/model selection.

### Changed
- Rewrote README with clean UTF-8 documentation for the current release.

## [0.2.2] - 2026-04-20

### Added
- `--compress` flag on `load` command
- `--analyze` documentation (check if session fits target model)
- `--chunk` documentation (split large sessions)
- `--smart` flag for merge command
- Additional output formats: opencode, codex, continue

### Changed
- Updated README with complete documentation
- Added badges (PyPI, Python version, License)

## [0.2.1] - 2026-04-20

### Added
- OpenCode adapter with inject support
- ULID message generation for proper session ordering

### Fixed
- OpenCode inject schema (model, providerID fields)
- Project lookup based on working directory

## [0.2.0] - 2026-04-19

### Added
- PyPI publish (aimem-cli)
- `--inject` flag for direct storage injection
- 8 source adapters
- 8 output formats
- LLM compression (opt-in)

## [0.1.0] - 2026-04-18

### Added
- Initial release
- Claude, Gemini, Qwen, OpenCode, Codex adapters
- Basic save/load commands
- Session storage

---

## Format

```
[VERSION] - DATE

### Added
- New features

### Changed
- Improvements

### Fixed
- Bug fixes
```
