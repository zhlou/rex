# rex

`rex` is a terminal UI remote explorer over SSH.

## Features (v0.2)

- Browse remote files/directories.
- Browser view automatically uses multiple columns when terminal width allows.
- Enter/leave directories.
- View files remotely (`o`).
- Edit files remotely with `$EDITOR` (`e`).
- On-demand **Run Command** panel (press `s` or `:` to open).
- Run commands in the current remote directory and view output inline.

## Install

```bash
pip install -e .
```

## Usage

```bash
rex user@host
rex user@host /var/log
```

## Controls

- `h`/`j`/`k`/`l` or arrow keys: move selection (left/down/up/right)
- `Enter`: enter directory or open file
- `p`: go to parent directory
- `e`: edit selected file remotely via `$EDITOR`
- `o`: open selected file in remote pager (`less`/`cat`)
- `s` or `:`: open **Run Command** panel (bottom quarter) in current browser `cwd`
- In command panel:
- Type/edit command locally (`Left/Right/Home/End`, `Backspace`, `Delete`, `Ctrl-U`)
- `Up/Down` for command history
- `Enter` to run command remotely
- `PgUp/PgDn` to page output
- `/` then `Enter` to search output, `n`/`N` for next/previous match
- `Esc` to dismiss pane (or cancel search input while searching)
- `q`: quit

## Notes

- SSH auth is delegated to system `ssh` (keys, agent, passwords, and `~/.ssh/config`).
- Remote edit command (`e`) uses `VISUAL` first, then `EDITOR`, and safely shell-quotes editor arguments before execution.
- If `VISUAL`/`EDITOR` is invalid shell syntax, rex falls back to `vi`.
- Target platforms: macOS and Linux.

## Smoke Test

```bash
./scripts/smoke.sh
```

## Release Notes

See `CHANGELOG.md` for release history.
