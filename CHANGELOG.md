# Changelog

All notable changes to AiMem will be documented in this file.

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