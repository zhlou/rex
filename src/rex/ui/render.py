from __future__ import annotations

from collections.abc import Callable

import curses

from rex.models import AppState
from rex.ui.layout import LayoutEngine


class Renderer:
    def __init__(self, state: AppState, layout: LayoutEngine, stdscr_getter: Callable[[], curses.window | None]) -> None:
        self.state = state
        self.layout = layout
        self._stdscr_getter = stdscr_getter

    def draw(self) -> None:
        stdscr = self._stdscr_getter()
        if stdscr is None:
            return

        stdscr.erase()
        h, w = stdscr.getmaxyx()

        browser_focus = "*" if self.state.focus == "browser" else " "
        command_focus = "*" if self.state.focus == "command" else " "

        header = f"{browser_focus} rex  host={self.state.host}  cwd={self.state.cwd}"
        stdscr.addnstr(0, 0, header, w - 1, curses.A_BOLD)

        content_h = max(1, h - 3)
        browser_block_h = content_h
        command_block_h = 0
        if self.state.command.visible:
            command_block_h = min(content_h - 1, self.layout.command_block_height(content_h))
            browser_block_h = max(1, content_h - command_block_h)

        stdscr.addnstr(1, 0, "Files", w - 1, curses.A_UNDERLINE)
        self.draw_entries(2, 0, max(1, browser_block_h - 1), w)

        cursor_pos = None
        if self.state.command.visible:
            panel_title_y = 1 + browser_block_h
            stdscr.hline(panel_title_y - 1, 0, ord("-"), w)
            stdscr.addnstr(
                panel_title_y,
                0,
                f"{command_focus} Run Command (Enter run | PgUp/PgDn scroll | / search | Esc dismiss)",
                w - 1,
                curses.A_UNDERLINE,
            )
            cursor_pos = self.draw_command_panel(panel_title_y + 1, 0, max(1, command_block_h - 1), w)

        footer = (
            "q quit | arrows/hjkl move | enter open/dir | p parent | e edit | o view | "
            "s/: run command | pgup/pgdn scroll | / search"
        )
        stdscr.addnstr(h - 2, 0, footer, w - 1, curses.A_DIM)
        stdscr.addnstr(h - 1, 0, self.state.message, w - 1, curses.A_BOLD)

        if self.state.focus == "command" and cursor_pos is not None:
            cy, cx = cursor_pos
            try:
                curses.curs_set(1)
            except curses.error:
                pass
            stdscr.move(cy, cx)
        else:
            try:
                curses.curs_set(0)
            except curses.error:
                pass

        stdscr.refresh()

    def draw_entries(self, y: int, x: int, height: int, width: int) -> None:
        stdscr = self._stdscr_getter()
        if stdscr is None or height <= 0 or width <= 1:
            return

        rows, column_width, _, page_size = self.layout.browser_layout(height, width)
        visible = self.state.entries[self.state.top_index : self.state.top_index + page_size]
        for i, entry in enumerate(visible):
            idx = self.state.top_index + i
            row = i % rows
            col = i // rows
            draw_x = x + col * column_width
            if draw_x >= x + width - 1:
                continue
            marker = "/" if entry.is_dir else ""
            line = f"{entry.name}{marker}"
            attr = curses.A_REVERSE if idx == self.state.selected and self.state.focus == "browser" else curses.A_NORMAL
            stdscr.addnstr(y + row, draw_x, line, max(1, column_width - 1), attr)

    def draw_command_panel(self, y: int, x: int, height: int, width: int) -> tuple[int, int] | None:
        stdscr = self._stdscr_getter()
        if stdscr is None or height <= 0 or width <= 1:
            return None

        output_rows = max(0, height - 1)
        self.layout.clamp_command_scroll()
        if output_rows > 0:
            end = max(0, len(self.state.command.lines) - self.state.command.scroll)
            start = max(0, end - output_rows)
            lines = self.state.command.lines[start:end]
        else:
            lines = []
        for i, line in enumerate(lines):
            stdscr.addnstr(y + i, x, line, width - 1)

        input_y = y + max(0, height - 1)
        prompt = "/ " if self.state.command.search_mode else "> "
        prompt_w = len(prompt)
        avail = max(0, width - 1 - prompt_w)
        text = self.state.command.search_query if self.state.command.search_mode else self.state.command.input
        cursor = len(text) if self.state.command.search_mode else self.state.command.cursor

        scroll = 0
        if cursor > avail:
            scroll = cursor - avail
        visible_input = text[scroll : scroll + avail]

        stdscr.addnstr(input_y, x, prompt, width - 1, curses.A_BOLD)
        stdscr.addnstr(input_y, x + prompt_w, visible_input, max(0, width - 1 - prompt_w))
        cursor_x = x + prompt_w + min(max(0, cursor - scroll), max(0, avail))
        cursor_x = min(cursor_x, x + width - 2)
        return (input_y, cursor_x)
