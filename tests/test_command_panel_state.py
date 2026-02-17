import unittest

from rex.main import CommandPanelState


class TestCommandPanelState(unittest.TestCase):
    def test_reset_for_open_clears_transient_state(self) -> None:
        state = CommandPanelState(
            visible=False,
            input="ls",
            cursor=2,
            lines=["old"],
            history=["pwd"],
            history_index=0,
            history_stash="stash",
            scroll=4,
            search_mode=True,
            search_query="err",
            search_matches=[1],
            search_pos=0,
        )

        state.reset_for_open()

        self.assertTrue(state.visible)
        self.assertEqual(state.input, "")
        self.assertEqual(state.cursor, 0)
        self.assertEqual(state.lines, [])
        self.assertIsNone(state.history_index)
        self.assertEqual(state.history_stash, "")
        self.assertEqual(state.scroll, 0)
        self.assertFalse(state.search_mode)
        self.assertEqual(state.search_query, "")
        self.assertEqual(state.search_matches, [])
        self.assertEqual(state.search_pos, -1)

    def test_append_line_truncates_to_max_lines(self) -> None:
        state = CommandPanelState(max_lines=3)
        for item in ["1", "2", "3", "4"]:
            state.append_line(item)

        self.assertEqual(state.lines, ["2", "3", "4"])

    def test_clear_input_resets_input_and_cursor(self) -> None:
        state = CommandPanelState(input="hello", cursor=3)
        state.clear_input()

        self.assertEqual(state.input, "")
        self.assertEqual(state.cursor, 0)


if __name__ == "__main__":
    unittest.main()
