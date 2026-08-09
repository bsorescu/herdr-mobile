# /// script
# requires-python = ">=3.12"
# dependencies = ["textual==8.2.8"]
# ///
"""herdr-remote: phone-friendly TUI for controlling Herdr agents over SSH."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass


class HerdrError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AgentInfo:
    pane_id: str
    kind: str
    status: str
    cwd: str
    name: str | None = None

    @property
    def project(self) -> str:
        return os.path.basename(self.cwd.rstrip("/"))


STATUS_ORDER = {"blocked": 0, "done": 1, "working": 2, "idle": 3, "unknown": 4}


def effective_status(agent: AgentInfo, seen: set[str]) -> str:
    if agent.status == "done" and agent.pane_id in seen:
        return "idle"
    return agent.status


def sort_agents(agents: list[AgentInfo], seen: set[str]) -> list[AgentInfo]:
    return sorted(agents, key=lambda a: (STATUS_ORDER.get(effective_status(a, seen), 99), a.pane_id))


def _default_run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=10)


class HerdrClient:
    def __init__(self, run_cli=None) -> None:
        self._run = run_cli or _default_run

    def _call(self, *args: str) -> dict:
        try:
            proc = self._run(["herdr", *args])
        except FileNotFoundError:
            raise HerdrError("herdr_missing", "herdr CLI not found on PATH") from None
        except subprocess.TimeoutExpired:
            raise HerdrError("timeout", f"herdr {' '.join(args)} timed out") from None

        # First pass: scan both streams for error JSON (errors take absolute precedence)
        for stream in (proc.stdout, proc.stderr):
            stripped = (stream or "").strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except ValueError:
                continue
            if "error" in payload:
                err = payload["error"]
                raise HerdrError(err.get("code", "cli_error"), err.get("message", stripped))

        # Second pass: look for success JSON on stdout
        success_payload = None
        stripped = (proc.stdout or "").strip()
        if stripped:
            try:
                payload = json.loads(stripped)
                if "error" not in payload:
                    success_payload = payload
            except ValueError:
                pass

        # Check returncode: must be 0 to accept success payload
        if proc.returncode != 0:
            raise HerdrError("cli_error", (proc.stderr or proc.stdout or "herdr failed").strip())

        # Return success payload if found and returncode was 0
        if success_payload:
            return success_payload

        return {}

    def list_agents(self) -> list[AgentInfo]:
        payload = self._call("agent", "list")
        return [
            AgentInfo(pane_id=a["pane_id"], kind=a["agent"], status=a["agent_status"],
                      cwd=a["cwd"], name=a.get("name"))
            for a in payload["result"]["agents"]
        ]

    def read_agent(self, pane_id: str, lines: int = 200) -> str:
        payload = self._call("agent", "read", pane_id, "--source", "recent-unwrapped",
                             "--format", "ansi", "--lines", str(lines))
        return payload["result"]["read"]["text"]

    def prompt_agent(self, pane_id: str, text: str) -> None:
        self._call("pane", "run", pane_id, text)

    def send_key(self, pane_id: str, key: str) -> None:
        if len(key) == 1:
            self._call("pane", "send-text", pane_id, key)
        else:
            self._call("pane", "send-keys", pane_id, key)


from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

STATUS_ICONS = {"blocked": "🔴", "done": "🟢", "working": "🔵", "idle": "⚪", "unknown": "⚫"}
LIST_POLL_SECONDS = 3.0
READ_POLL_SECONDS = 2.0


class AgentListScreen(Screen):
    BINDINGS = [
        Binding("enter", "open_agent", "Open", priority=True),
        Binding("r", "refresh", "Refresh"),
        Binding("q", "quit_app", "Quit"),
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        table = DataTable(cursor_type="row")
        table.add_columns("st", "agent", "project", "pane")
        yield table
        yield Footer()

    def on_mount(self) -> None:
        self.render_agents()

    def render_agents(self) -> None:
        app = self.app
        table = self.query_one(DataTable)
        selected_row = table.cursor_row
        selected_pane_id = self._selected_pane_id()
        table.clear()
        for a in app.agents:
            st = effective_status(a, app.seen)
            table.add_row(STATUS_ICONS.get(st, "?"), f"{a.kind}" + (f" ({a.name})" if a.name else ""),
                          a.project, a.pane_id, key=a.pane_id)
        if not table.row_count:
            return
        new_row = None
        if selected_pane_id is not None:
            try:
                new_row = table.get_row_index(selected_pane_id)
            except Exception:
                new_row = None
        if new_row is None:
            new_row = min(selected_row or 0, table.row_count - 1)
        table.move_cursor(row=new_row)

    def _selected_pane_id(self) -> str | None:
        table = self.query_one(DataTable)
        if not table.row_count:
            return None
        return str(table.get_row_at(table.cursor_row)[3])

    def action_open_agent(self) -> None:
        pane_id = self._selected_pane_id()
        if pane_id:
            self.app.open_agent(pane_id)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.app.open_agent(str(event.row_key.value))

    def action_refresh(self) -> None:
        self.app.refresh_agents()

    def action_quit_app(self) -> None:
        self.app.exit()

    def action_cursor_down(self) -> None:
        self.query_one(DataTable).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one(DataTable).action_cursor_up()


class AgentDetailScreen(Screen):
    BINDINGS = [Binding("q", "back", "Back"), Binding("escape", "back", show=False)]

    def __init__(self, pane_id: str) -> None:
        super().__init__()
        self.pane_id = pane_id

    def compose(self) -> ComposeResult:
        yield Static(self.pane_id, id="detail-header")
        yield Footer()

    def action_back(self) -> None:
        self.app.pop_screen()


class HerdrRemoteApp(App):
    def __init__(self, client) -> None:
        super().__init__()
        self.client = client
        self.agents: list[AgentInfo] = []
        self.seen: set[str] = set()

    def on_mount(self) -> None:
        self.refresh_agents()
        self.push_screen(AgentListScreen())
        self.set_interval(LIST_POLL_SECONDS, self.refresh_agents)

    def refresh_agents(self) -> None:
        try:
            self.agents = sort_agents(self.client.list_agents(), self.seen)
        except HerdrError as err:
            self.notify(err.message, title=err.code, severity="error")
            return
        screen = self.screen_stack[-1] if self.screen_stack else None
        if isinstance(screen, AgentListScreen):
            screen.render_agents()

    def open_agent(self, pane_id: str) -> None:
        self.push_screen(AgentDetailScreen(pane_id))


def main() -> None:
    HerdrRemoteApp(HerdrClient()).run()


if __name__ == "__main__":
    main()
