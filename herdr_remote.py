# /// script
# requires-python = ">=3.12"
# dependencies = ["textual==8.2.8"]
# ///
"""herdr-remote: phone-friendly TUI for controlling Herdr agents over SSH."""
from __future__ import annotations

import json
import os
import subprocess
import time
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


from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, RichLog, Static

STATUS_ICONS = {"blocked": "🔴", "done": "🟢", "working": "🔵", "idle": "⚪", "unknown": "⚫"}
LIST_POLL_SECONDS = 3.0
READ_POLL_SECONDS = 2.0
STALL_SECONDS = 6.0

REMOTE_KEYS = {"up": "up", "down": "down", "enter": "enter", "tab": "tab",
               "escape": "esc", "y": "y", "n": "n",
               "1": "1", "2": "2", "3": "3"}


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
        yield Static("", id="list-error")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#list-error", Static).display = False
        self.app.refresh_agents()

    def show_error(self, err: HerdrError) -> None:
        box = self.query_one("#list-error", Static)
        box.update(f"Cannot reach herdr: {err.message}\nPress r to retry.")
        box.display = True
        self.query_one(DataTable).display = False

    def clear_error(self) -> None:
        box = self.query_one("#list-error", Static)
        if box.display:
            box.display = False
            self.query_one(DataTable).display = True

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
    BINDINGS = [
        Binding("q", "back", "Back"),
        Binding("escape", "back", show=False),
        Binding("i", "focus_prompt", "Prompt"),
        Binding("k", "toggle_remote", "Remote"),
        Binding("n", "next_agent", "Next"),
        Binding("p", "prev_agent", "Prev"),
    ]

    DEFAULT_CSS = """
    AgentDetailScreen #remote-bar {
        height: auto;
    }

    AgentDetailScreen #remote-row1,
    AgentDetailScreen #remote-row2 {
        height: auto;
        align: left top;
    }

    AgentDetailScreen #remote-bar Button {
        width: auto;
        min-width: 5;
        height: 1;
        border: none;
        padding: 0 1;
        margin: 0 1 0 0;
    }

    AgentDetailScreen #remote-hint {
        height: auto;
        color: $text-muted;
    }
    """

    def __init__(self, pane_id: str) -> None:
        super().__init__()
        self.pane_id = pane_id
        self.follow = True
        self._auto_shown = False

    def compose(self) -> ComposeResult:
        yield Static(self.pane_id, id="detail-header")
        yield RichLog(id="output", markup=False, wrap=True, auto_scroll=False)
        with Vertical(id="remote-bar"):
            with Horizontal(id="remote-row1"):
                for key_name, label in [("up", "↑"), ("down", "↓"), ("enter", "Enter"),
                                        ("esc", "Esc"), ("y", "y")]:
                    yield Button(label, id=f"rk-{key_name}")
            with Horizontal(id="remote-row2"):
                for key_name, label in [("n", "n"), ("1", "1"), ("2", "2"), ("3", "3")]:
                    yield Button(label, id=f"rk-{key_name}")
            yield Static("tap buttons to answer · n/p = next/prev agent", id="remote-hint")
        yield Input(placeholder="prompt… (i to focus)", id="prompt")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#remote-bar").display = False
        self.refresh_header()
        self.refresh_output()
        self.watch(self.query_one(RichLog), "scroll_y", self.on_scroll_moved, init=False)
        self.set_interval(READ_POLL_SECONDS, self._tick)

    def _tick(self) -> None:
        if self.app.screen is not self:
            return
        self.refresh_header()
        self.refresh_output()

    def _agent(self) -> AgentInfo | None:
        for a in self.app.agents:
            if a.pane_id == self.pane_id:
                return a
        return None

    def refresh_header(self) -> None:
        a = self._agent()
        if a is None:
            return
        st = effective_status(a, self.app.seen)
        self.query_one("#detail-header", Static).update(
            f"{a.pane_id} · {a.kind} · {a.project} — {STATUS_ICONS.get(st, '?')} {st}")
        if st == "blocked" and not self._auto_shown:
            self.query_one("#remote-bar").display = True
            self._auto_shown = True
        elif st != "blocked":
            self._auto_shown = False

    def refresh_output(self) -> None:
        if not self.follow:
            # User scrolled up to read history: freeze content in place. read_agent
            # returns a sliding window, so fetching now would silently replace the
            # text under the user's eyes even though scroll_y hasn't moved.
            return
        try:
            content = self.app.client.read_agent(self.pane_id)
        except HerdrError as err:
            self.app.handle_agent_error(self.pane_id, err)
            return
        log = self.query_one(RichLog)
        log.clear()
        log.write(Text.from_ansi(content))
        # immediate=True: apply synchronously so scroll_y/max_scroll_y are consistent
        # right away (a deferred scroll_end leaves scroll_y stale against the freshly
        # rewritten content, which corrupts the next is_vertical_scroll_end check).
        log.scroll_end(animate=False, immediate=True)

    def on_scroll_moved(self) -> None:
        log = self.query_one(RichLog)
        was_following = self.follow
        self.follow = bool(log.is_vertical_scroll_end)
        if self.follow and not was_following:
            # Returning to the bottom: don't make the user wait up to
            # READ_POLL_SECONDS for the frozen content to catch up.
            self.refresh_output()

    def action_back(self) -> None:
        self.app.pop_screen()

    def action_focus_prompt(self) -> None:
        self.query_one("#prompt", Input).focus()

    def action_toggle_remote(self) -> None:
        bar = self.query_one("#remote-bar")
        bar.display = not bar.display

    def action_next_agent(self) -> None:
        self.app.cycle_agent(self.pane_id, +1)

    def action_prev_agent(self) -> None:
        self.app.cycle_agent(self.pane_id, -1)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        key = event.button.id.removeprefix("rk-")
        self._send_remote_key(key)

    def _send_remote_key(self, herdr_key: str) -> None:
        try:
            self.app.client.send_key(self.pane_id, herdr_key)
        except HerdrError as err:
            self.app.notify(err.message, title=err.code, severity="error")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        try:
            self.app.client.prompt_agent(self.pane_id, text)
        except HerdrError as err:
            self.app.notify(err.message, title=err.code, severity="error")
            return
        event.input.value = ""
        event.input.blur()
        self.app.notify("Prompt sent", severity="information")
        self.app.pending_prompts[self.pane_id] = time.monotonic()

    def on_key(self, event) -> None:
        if event.key == "escape" and isinstance(self.app.focused, Input):
            self.app.focused.blur()
            event.stop()
            return
        if isinstance(self.app.focused, Input):
            return
        bar = self.query_one("#remote-bar")
        if not bar.display:
            return
        if event.key == "q":
            bar.display = False
            event.stop()
            return
        if event.key in ("n", "p"):
            # Reserved for agent cycling (see BINDINGS) even while the remote
            # bar is visible; answering y/n prompts remotely still works via
            # the on-screen buttons.
            return
        if event.key in REMOTE_KEYS:
            self._send_remote_key(REMOTE_KEYS[event.key])
            event.stop()


class HerdrRemoteApp(App):
    def __init__(self, client) -> None:
        super().__init__()
        self.client = client
        self.agents: list[AgentInfo] = []
        self.seen: set[str] = set()
        self.pending_prompts: dict[str, float] = {}

    def on_mount(self) -> None:
        self.push_screen(AgentListScreen())
        self.set_interval(LIST_POLL_SECONDS, self.refresh_agents)

    def refresh_agents(self) -> None:
        screen = self.screen_stack[-1] if self.screen_stack else None
        list_screen = screen if isinstance(screen, AgentListScreen) else None
        try:
            self.agents = sort_agents(self.client.list_agents(), self.seen)
        except HerdrError as err:
            if not self.agents:
                if list_screen is not None:
                    list_screen.show_error(err)
            else:
                self.notify(err.message, title=err.code, severity="error")
            return

        self.pending_prompts = {p: t for p, t in self.pending_prompts.items()
                                 if p in {a.pane_id for a in self.agents}}

        if list_screen is not None:
            list_screen.render_agents()
            list_screen.clear_error()

        now = time.monotonic()
        for pane_id, sent_at in list(self.pending_prompts.items()):
            if now - sent_at < STALL_SECONDS:
                continue
            agent = next((a for a in self.agents if a.pane_id == pane_id), None)
            if agent and agent.status in ("idle", "blocked"):
                self.notify(f"Prompt may not have arrived (agent still {agent.status})",
                            title="prompt stall", severity="warning")
            del self.pending_prompts[pane_id]

    def cycle_agent(self, current: str, delta: int) -> None:
        if not self.agents:
            return
        ids = [a.pane_id for a in self.agents]
        idx = ids.index(current) if current in ids else 0
        target = ids[(idx + delta) % len(ids)]
        self.pop_screen()
        self.open_agent(target)

    def open_agent(self, pane_id: str) -> None:
        agent = next((a for a in self.agents if a.pane_id == pane_id), None)
        if agent and agent.status == "done":
            self.seen.add(pane_id)
        self.push_screen(AgentDetailScreen(pane_id))

    def handle_agent_error(self, pane_id: str, err: HerdrError) -> None:
        top = self.screen_stack[-1] if self.screen_stack else None
        if err.code == "agent_not_found" and isinstance(top, AgentDetailScreen) and top.pane_id == pane_id:
            self.pop_screen()
            self.notify(f"Agent {pane_id} is gone", severity="warning")
            return
        self.notify(err.message, title=err.code, severity="error")


def main() -> None:
    HerdrRemoteApp(HerdrClient()).run()


if __name__ == "__main__":
    main()
