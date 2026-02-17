from __future__ import annotations

import curses
from collections.abc import Callable
from pathlib import PurePosixPath

from rex.command import CommandController
from rex.models import AppState, RemoteEntry
from rex.ui.layout import LayoutEngine


class InputController:
    def __init__(
        self,
        state: AppState,
        layout: LayoutEngine,
        commands: CommandController,
        move_selection_grid: Callable[[int, int], None],
        move_selection: Callable[[int], None],
        enter_selected: Callable[[], None],
        change_directory: Callable[[str], bool],
        reload_entries: Callable[[], None],
        current_entry: Callable[[], RemoteEntry | None],
        edit_file: Callable[[str], None],
        open_file: Callable[[str], None],
    ) -> None:
        self.state = state
        self.layout = layout
        self.commands = commands
        self._move_selection_grid = move_selection_grid
        self._move_selection = move_selection
        self._enter_selected = enter_selected
        self._change_directory = change_directory
        self._reload_entries = reload_entries
        self._current_entry = current_entry
        self._edit_file = edit_file
        self._open_file = open_file

    def set_command_from_history(self, direction: int) -> None:
        if not self.state.command.history:
            return

        if self.state.command.history_index is None:
            self.state.command.history_stash = self.state.command.input
            self.state.command.history_index = len(self.state.command.history)

        next_idx = self.state.command.history_index + direction
        next_idx = max(0, min(len(self.state.command.history), next_idx))
        self.state.command.history_index = next_idx

        if self.state.command.history_index == len(self.state.command.history):
            self.state.command.input = self.state.command.history_stash
        else:
            self.state.command.input = self.state.command.history[self.state.command.history_index]
        self.state.command.cursor = len(self.state.command.input)

    def handle_search_key(self, key: int) -> bool:
        if key in (27,):  # ESC
            self.state.command.search_mode = False
            self.state.message = "Search cancelled"
            return True
        if key in (curses.KEY_ENTER, 10, 13):
            self.state.command.search_mode = False
            self.commands.refresh_search_matches()
            if not self.state.command.search_matches:
                self.state.message = f"No matches for '{self.state.command.search_query}'"
                return True
            self.state.command.search_pos = -1
            self.commands.jump_search(1)
            return True
        if key in (curses.KEY_BACKSPACE, 127, 8):
            if self.state.command.search_query:
                self.state.command.search_query = self.state.command.search_query[:-1]
            return True
        if key == 21:  # Ctrl-u
            self.state.command.search_query = ""
            return True
        if 32 <= key <= 126:
            self.state.command.search_query += chr(key)
            return True
        return True

    def handle_command_key(self, key: int) -> bool:
        if self.state.command.search_mode:
            return self.handle_search_key(key)

        if key in (27, 29):  # ESC, Ctrl-]
            self.commands.hide_panel()
            return True
        if key in (ord("/"),):
            self.state.command.search_mode = True
            self.state.message = "Search output (/ then Enter, ESC cancel, n/N navigate)"
            return True
        if key in (ord("n"),):
            self.commands.refresh_search_matches()
            self.commands.jump_search(1)
            return True
        if key in (ord("N"),):
            self.commands.refresh_search_matches()
            self.commands.jump_search(-1)
            return True
        if key in (curses.KEY_PPAGE,):
            step = max(1, self.layout.command_output_rows())
            self.state.command.scroll += step
            self.layout.clamp_command_scroll()
            return True
        if key in (curses.KEY_NPAGE,):
            step = max(1, self.layout.command_output_rows())
            self.state.command.scroll -= step
            self.layout.clamp_command_scroll()
            return True
        if key in (curses.KEY_ENTER, 10, 13):
            self.commands.execute_input()
            return True
        if key in (curses.KEY_BACKSPACE, 127, 8):
            if self.state.command.cursor > 0:
                self.state.command.input = (
                    self.state.command.input[: self.state.command.cursor - 1]
                    + self.state.command.input[self.state.command.cursor :]
                )
                self.state.command.cursor -= 1
            return True
        if key in (curses.KEY_DC,):
            if self.state.command.cursor < len(self.state.command.input):
                self.state.command.input = (
                    self.state.command.input[: self.state.command.cursor]
                    + self.state.command.input[self.state.command.cursor + 1 :]
                )
            return True
        if key in (curses.KEY_LEFT,):
            self.state.command.cursor = max(0, self.state.command.cursor - 1)
            return True
        if key in (curses.KEY_RIGHT,):
            self.state.command.cursor = min(len(self.state.command.input), self.state.command.cursor + 1)
            return True
        if key in (curses.KEY_HOME,):
            self.state.command.cursor = 0
            return True
        if key in (curses.KEY_END,):
            self.state.command.cursor = len(self.state.command.input)
            return True
        if key in (curses.KEY_UP,):
            self.set_command_from_history(-1)
            return True
        if key in (curses.KEY_DOWN,):
            self.set_command_from_history(1)
            return True
        if key == 21:  # Ctrl-u
            self.state.command.input = self.state.command.input[self.state.command.cursor :]
            self.state.command.cursor = 0
            return True
        if 32 <= key <= 126:
            ch = chr(key)
            self.state.command.input = (
                self.state.command.input[: self.state.command.cursor]
                + ch
                + self.state.command.input[self.state.command.cursor :]
            )
            self.state.command.cursor += 1
            return True
        return True

    def handle_key(self, key: int) -> bool:
        if key in (ord("q"), ord("Q")):
            return False

        if key in (curses.KEY_RESIZE,):
            return True

        if self.state.focus == "command":
            return self.handle_command_key(key)

        if key in (curses.KEY_UP, ord("k")):
            self._move_selection_grid(-1, 0)
        elif key in (curses.KEY_DOWN, ord("j")):
            self._move_selection_grid(1, 0)
        elif key in (curses.KEY_LEFT, ord("h")):
            self._move_selection_grid(0, -1)
        elif key in (curses.KEY_RIGHT, ord("l")):
            self._move_selection_grid(0, 1)
        elif key in (curses.KEY_NPAGE,):
            self._move_selection(10)
        elif key in (curses.KEY_PPAGE,):
            self._move_selection(-10)
        elif key in (curses.KEY_ENTER, 10, 13):
            self._enter_selected()
        elif key in (ord("p"),):
            if not self._change_directory(str(PurePosixPath(self.state.cwd).parent) or "/"):
                self.state.message = "Error: failed to change to parent directory"
        elif key in (ord("r"),):
            self._reload_entries()
        elif key in (ord("e"),):
            entry = self._current_entry()
            if entry and not entry.is_dir and entry.name != "..":
                self._edit_file(entry.name)
        elif key in (ord("o"),):
            entry = self._current_entry()
            if entry and not entry.is_dir and entry.name != "..":
                self._open_file(entry.name)
        elif key in (ord(":"), ord("s"), ord("S")):
            self.commands.show_panel()

        self.layout.ensure_visible()
        return True
