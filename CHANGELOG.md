# Changelog

All notable changes to `rex` are documented in this file.

## [Unreleased]

### Added

- Browser pane now lays out file entries across multiple columns based on content width and terminal width.

### Changed

- Browser navigation now supports full directional movement with `h`/`j`/`k`/`l` and arrow keys.
- Parent directory navigation key changed from `h` to `p`.
- Replaced the interactive shell pane with a local-edit **Run Command** panel.
- Run Command panel opens on demand with `s` or `:`, renders in the bottom quarter, and runs in browser `cwd`.
- Run Command panel supports local line editing, history navigation, and `Esc` to dismiss.
- Added command output paging with `PgUp/PgDn` in Run Command panel.
- Added command output search with `/` + `Enter`, and `n`/`N` navigation between matches.

### Fixed

- Hardened remote edit command construction to avoid raw shell interpolation from `VISUAL`/`EDITOR`.
- Added fallback to `vi` when `VISUAL`/`EDITOR` cannot be parsed safely.
- Added regression tests for editor command quoting behavior.
- Browser selection movement now stays aligned with rendered row/column position and scrolls across pages correctly.

## [0.2] - 2026-02-14

### Added

- Embedded shell pane improvements:
  - ANSI SGR color rendering (for common colored output like `ls --color`).
  - Visible cursor when shell pane has focus.
- Smoke test script: `scripts/smoke.sh`.
- SSH quoting regression tests: `tests/test_ssh_quoting.py`.

### Changed

- Version bumped to `0.2` in package metadata and runtime version.
- README updated to describe v0.2 capabilities and smoke test usage.
- `Enter` behavior in browser pane now tries directory navigation first and falls back to opening file if target is not a directory.

### Fixed

- Critical SSH remote command quoting bug that caused directory navigation to appear successful while listing the wrong directory.
- Directory navigation state synchronization between displayed `cwd` and file list updates.
- Shell pane rendering bleed into footer/hint line.

## [0.1.0] - 2026-02-14

### Added

- Initial release.
- Remote file browsing over system `ssh`.
- Directory navigation (enter/parent/refresh).
- Remote file open (`o`) and remote edit via `$EDITOR` (`e`).
- One-off command execution (`:`) in current remote directory.
- Embedded interactive SSH shell pane.
