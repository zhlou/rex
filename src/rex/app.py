from __future__ import annotations

import curses
import os
import shlex
from pathlib import PurePosixPath

from rex.command import CommandController
from rex.input import InputController
from rex.models import AppState, CommandPanelState, RemoteEntry
from rex.remote import RemoteShell
from rex.ui.layout import LayoutEngine
from rex.ui.render import Renderer


class RexApp:
    def __init__(self, stdscr: curses.window | None, host: str, start_path: str = ".") -> None:
        self.stdscr = stdscr
        self._remote = RemoteShell(host)
        self.state = AppState(host=host, cwd=self._normalize_remote_path(start_path))

        self.layout = LayoutEngine(self.state, self._get_stdscr)
        self.commands = CommandController(self.state, self.remote, self.layout)
        self.input = InputController(
            state=self.state,
            layout=self.layout,
            commands=self.commands,
            move_selection_grid=self._move_selection_grid,
            move_selection=self._move_selection,
            enter_selected=self._enter_selected,
            change_directory=self._change_directory,
            reload_entries=self._reload_entries,
            current_entry=self._current_entry,
            edit_file=self._edit_file,
            open_file=self._open_file,
        )
        self.renderer = Renderer(self.state, self.layout, self._get_stdscr)

    def _get_stdscr(self) -> curses.window | None:
        return self.stdscr

    @property
    def remote(self) -> RemoteShell:
        return self._remote

    @remote.setter
    def remote(self, value: RemoteShell) -> None:
        self._remote = value
        if hasattr(self, "commands"):
            self.commands.remote = value

    @property
    def host(self) -> str:
        return self.state.host

    @host.setter
    def host(self, value: str) -> None:
        self.state.host = value

    @property
    def cwd(self) -> str:
        return self.state.cwd

    @cwd.setter
    def cwd(self, value: str) -> None:
        self.state.cwd = value

    @property
    def entries(self) -> list[RemoteEntry]:
        return self.state.entries

    @entries.setter
    def entries(self, value: list[RemoteEntry]) -> None:
        self.state.entries = value

    @property
    def selected(self) -> int:
        return self.state.selected

    @selected.setter
    def selected(self, value: int) -> None:
        self.state.selected = value

    @property
    def top_index(self) -> int:
        return self.state.top_index

    @top_index.setter
    def top_index(self, value: int) -> None:
        self.state.top_index = value

    @property
    def message(self) -> str:
        return self.state.message

    @message.setter
    def message(self, value: str) -> None:
        self.state.message = value

    @property
    def focus(self) -> str:
        return self.state.focus

    @focus.setter
    def focus(self, value: str) -> None:
        self.state.focus = value

    @property
    def command(self) -> CommandPanelState:
        return self.state.command

    def run(self) -> None:
        if self.stdscr is None:
            raise RuntimeError("stdscr is required to run RexApp")

        curses.curs_set(0)
        self.stdscr.nodelay(True)
        self.stdscr.timeout(50)
        self.stdscr.keypad(True)
        self._reload_entries()

        while True:
            self._draw()
            key = self.stdscr.getch()
            if key == -1:
                continue
            if not self._handle_key(key):
                break

    def _reload_entries(self) -> None:
        resolved_cwd, parsed, err = self.remote.list_directory(self.cwd)
        if err is not None or parsed is None or resolved_cwd is None:
            self.message = err or "Error: failed to list directory"
            return

        self.cwd = resolved_cwd
        self.entries = parsed
        self.selected = 0
        self.top_index = 0
        self.message = f"Loaded {len(parsed)-1} entries"

    def _normalize_remote_path(self, path: str) -> str:
        p = PurePosixPath(path)
        if not p.is_absolute():
            p = PurePosixPath(".") / p
        text = str(p)
        return text if text else "."

    def _current_entry(self) -> RemoteEntry | None:
        if not self.entries:
            return None
        return self.entries[self.selected]

    def _move_selection(self, delta: int) -> None:
        if not self.entries:
            return
        self.selected = max(0, min(len(self.entries) - 1, self.selected + delta))

    def _move_selection_grid(self, d_row: int, d_col: int) -> None:
        if not self.entries:
            return

        browser_h, browser_w = self.layout.browser_pane_dimensions()
        rows, _, _, _ = self.layout.browser_layout(browser_h, browser_w)
        if rows <= 0:
            return

        delta = d_row + (d_col * rows)
        if delta == 0:
            return
        target = self.selected + delta
        if target < 0 or target >= len(self.entries):
            return
        self.selected = target

    def _enter_selected(self) -> None:
        entry = self._current_entry()
        if entry is None:
            return

        if entry.name == "..":
            self._change_directory(str(PurePosixPath(self.cwd).parent) or "/")
            return

        target = str(PurePosixPath(self.cwd) / entry.name)
        if self._change_directory(target):
            return

        self.message = f"Not a directory: {entry.name}. Opening file."
        self._open_file(entry.name)

    def _change_directory(self, target_path: str) -> bool:
        old_cwd = self.cwd
        resolved_cwd, parsed, err = self.remote.list_directory(target_path)
        if err is not None or parsed is None or resolved_cwd is None:
            self.message = err or "Failed to change directory"
            return False

        self.cwd = resolved_cwd
        self.entries = parsed
        self.selected = 0
        self.top_index = 0
        if old_cwd != self.cwd:
            self.message = f"Entered {self.cwd} ({len(parsed)-1} entries)"
        else:
            self.message = f"Staying in {self.cwd} ({len(parsed)-1} entries)"
        return True

    def _open_file(self, filename: str) -> None:
        cmd = (
            f"cd -- {shlex.quote(self.cwd)} && "
            f"if command -v less >/dev/null 2>&1; then less -- {shlex.quote(filename)}; "
            f"else cat -- {shlex.quote(filename)}; fi"
        )
        self._run_fullscreen_ssh(cmd)

    def _edit_file(self, filename: str) -> None:
        editor_value = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
        try:
            editor_argv = shlex.split(editor_value)
        except ValueError:
            editor_argv = ["vi"]
        if not editor_argv:
            editor_argv = ["vi"]
        editor_cmd = " ".join(shlex.quote(arg) for arg in editor_argv)
        cmd = f"cd -- {shlex.quote(self.cwd)} && {editor_cmd} -- {shlex.quote(filename)}"
        self._run_fullscreen_ssh(cmd)

    def _run_fullscreen_ssh(self, remote_command: str) -> None:
        if self.stdscr is None:
            self.remote.run_fullscreen(remote_command)
            return

        curses.def_prog_mode()
        curses.endwin()
        try:
            self.remote.run_fullscreen(remote_command)
        finally:
            curses.reset_prog_mode()
            curses.curs_set(0)
            self.stdscr.nodelay(True)
            self.stdscr.timeout(50)
            self.stdscr.keypad(True)
            self._reload_entries()

    # Compatibility delegations for existing tests/callers.
    def _show_command_panel(self) -> None:
        self.commands.show_panel()

    def _hide_command_panel(self) -> None:
        self.commands.hide_panel()

    def _append_command_line(self, line: str) -> None:
        self.commands.append_line(line)

    def _execute_command_input(self) -> None:
        self.commands.execute_input()

    def _refresh_search_matches(self) -> None:
        self.commands.refresh_search_matches()

    def _jump_search(self, direction: int) -> None:
        self.commands.jump_search(direction)

    def _command_block_height(self, total_height: int) -> int:
        return self.layout.command_block_height(total_height)

    def _browser_pane_dimensions(self) -> tuple[int, int]:
        return self.layout.browser_pane_dimensions()

    def _command_output_rows(self) -> int:
        return self.layout.command_output_rows()

    def _command_max_scroll(self) -> int:
        return self.layout.command_max_scroll()

    def _clamp_command_scroll(self) -> None:
        self.layout.clamp_command_scroll()

    def _scroll_to_line(self, line_idx: int) -> None:
        self.layout.scroll_to_line(line_idx)

    def _ensure_visible(self) -> None:
        self.layout.ensure_visible()

    def _browser_layout(self, height: int, width: int) -> tuple[int, int, int, int]:
        return self.layout.browser_layout(height, width)

    def _handle_search_key(self, key: int) -> bool:
        return self.input.handle_search_key(key)

    def _set_command_from_history(self, direction: int) -> None:
        self.input.set_command_from_history(direction)

    def _handle_command_key(self, key: int) -> bool:
        return self.input.handle_command_key(key)

    def _handle_key(self, key: int) -> bool:
        return self.input.handle_key(key)

    def _draw(self) -> None:
        self.renderer.draw()

    def _draw_entries(self, y: int, x: int, height: int, width: int) -> None:
        self.renderer.draw_entries(y, x, height, width)

    def _draw_command_panel(self, y: int, x: int, height: int, width: int) -> tuple[int, int] | None:
        return self.renderer.draw_command_panel(y, x, height, width)
