# rex

`rex` is a terminal UI remote explorer over SSH.

## Features (v0.1)

- Browse remote files/directories.
- Enter/leave directories.
- View files remotely (`o`).
- Edit files remotely with `$EDITOR` (`e`).
- Embedded SSH shell pane (focus with `TAB` or `s`).
- Run one-off command in current remote directory (`:`).

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

- `j`/`k` or arrow keys: move selection
- `Enter`/`l`: enter directory or open file
- `h`: go to parent directory
- `e`: edit selected file remotely via `$EDITOR`
- `o`: open selected file in remote pager (`less`/`cat`)
- `:`: run one command in current remote directory
- `s`: focus shell pane
- `TAB`: toggle focus between browser and shell
- In shell focus: type directly into remote shell, `b` to return to browser
- `q`: quit

## Notes

- SSH auth is delegated to system `ssh` (keys, agent, passwords, and `~/.ssh/config`).
- Target platforms: macOS and Linux.
