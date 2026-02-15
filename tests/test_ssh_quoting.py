import subprocess
import unittest
from unittest.mock import patch

from rex.main import RexApp, build_remote_sh_command


class TestRemoteCommandQuoting(unittest.TestCase):
    def run_remote(self, command: str) -> subprocess.CompletedProcess[str]:
        remote = build_remote_sh_command(command)
        return subprocess.run(
            ["sh", "-lc", remote],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_shell_operators_are_inside_inner_shell(self) -> None:
        result = self.run_remote("cd / && pwd")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "/")

    def test_paths_with_spaces_work(self) -> None:
        result = self.run_remote("cd -- '/tmp' && printf '%s\n' 'a b'")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "a b")


class TestEditorCommandQuoting(unittest.TestCase):
    def test_editor_value_is_shell_quoted(self) -> None:
        app = RexApp(stdscr=None, host="example.com")
        app.cwd = "/tmp/work dir"
        with patch.dict("os.environ", {"EDITOR": "vim; echo pwned"}, clear=False):
            with patch.object(app, "_run_fullscreen_ssh") as run:
                app._edit_file("notes.txt")
        run.assert_called_once_with("cd -- '/tmp/work dir' && 'vim;' echo pwned -- notes.txt")

    def test_invalid_editor_falls_back_to_vi(self) -> None:
        app = RexApp(stdscr=None, host="example.com")
        app.cwd = "/tmp"
        with patch.dict("os.environ", {"EDITOR": "\""}, clear=False):
            with patch.object(app, "_run_fullscreen_ssh") as run:
                app._edit_file("a.txt")
        run.assert_called_once_with("cd -- /tmp && vi -- a.txt")


if __name__ == "__main__":
    unittest.main()
