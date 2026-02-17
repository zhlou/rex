import subprocess
import unittest

from rex.main import RexApp


class _FakeRemote:
    def __init__(self, result: subprocess.CompletedProcess[str] | None = None, exc: Exception | None = None) -> None:
        self.result = result
        self.exc = exc
        self.calls: list[tuple[str, int]] = []

    def run(self, command: str, timeout: int = 30) -> subprocess.CompletedProcess[str]:
        self.calls.append((command, timeout))
        if self.exc is not None:
            raise self.exc
        assert self.result is not None
        return self.result


class TestRexAppRefactorBehavior(unittest.TestCase):
    def test_show_command_panel_resets_state(self) -> None:
        app = RexApp(stdscr=None, host="example.com")
        app.command.input = "ls"
        app.command.cursor = 2
        app.command.lines = ["old"]
        app.command.search_mode = True

        app._show_command_panel()

        self.assertEqual(app.focus, "command")
        self.assertTrue(app.command.visible)
        self.assertEqual(app.command.input, "")
        self.assertEqual(app.command.cursor, 0)
        self.assertEqual(app.command.lines, [])

    def test_execute_command_input_success_records_output(self) -> None:
        app = RexApp(stdscr=None, host="example.com")
        app.cwd = "/tmp"
        app.command.visible = True
        app.command.input = "echo hi"
        app.remote = _FakeRemote(
            result=subprocess.CompletedProcess(
                args=["ssh"],
                returncode=0,
                stdout="line1\nline2\n",
                stderr="",
            )
        )

        app._execute_command_input()

        self.assertEqual(app.remote.calls, [("cd -- /tmp && echo hi", 60)])
        self.assertEqual(app.command.history, ["echo hi"])
        self.assertEqual(app.command.lines, ["$ echo hi", "line1", "line2"])
        self.assertEqual(app.message, "Command finished")
        self.assertEqual(app.command.input, "")
        self.assertEqual(app.command.cursor, 0)

    def test_execute_command_input_failure_includes_stderr_and_exit(self) -> None:
        app = RexApp(stdscr=None, host="example.com")
        app.cwd = "/tmp"
        app.command.visible = True
        app.command.input = "false"
        app.remote = _FakeRemote(
            result=subprocess.CompletedProcess(
                args=["ssh"],
                returncode=17,
                stdout="",
                stderr="problem\n",
            )
        )

        app._execute_command_input()

        self.assertEqual(app.command.lines, ["$ false", "stderr: problem", "[exit 17]"])
        self.assertEqual(app.message, "Command failed (17)")

    def test_execute_command_input_timeout(self) -> None:
        app = RexApp(stdscr=None, host="example.com")
        app.command.visible = True
        app.command.input = "sleep 999"
        app.remote = _FakeRemote(exc=subprocess.TimeoutExpired(cmd="ssh", timeout=60))

        app._execute_command_input()

        self.assertEqual(app.command.lines, ["$ sleep 999", "[timed out]"])
        self.assertEqual(app.message, "Command timed out")
        self.assertEqual(app.command.input, "")
        self.assertEqual(app.command.cursor, 0)


if __name__ == "__main__":
    unittest.main()
