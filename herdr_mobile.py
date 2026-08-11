# /// script
# requires-python = ">=3.12"
# dependencies = ["textual==8.2.8"]
# ///
"""herdr-mobile: phone-friendly TUI for controlling Herdr agents over SSH."""
from __future__ import annotations

import json
import os
import re
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


_ALNUM_RE = re.compile(r"[0-9A-Za-z]")
_CHROME_RE = re.compile(
    r"⏵⏵|auto mode on|bypassing permissions|plan mode on|esc to interrupt|"
    r"\? for shortcuts|ctrl\+p to cycle|-- INSERT --",
    re.IGNORECASE,
)
TRIM_WINDOW_LINES = 30

_ANSI_RE = re.compile(
    r"\x1b\[[0-9;:?]*[A-Za-z]"  # CSI: SGR colors, cursor moves, etc.
    r"|\x1b\][^\x07]*\x07"      # OSC, terminated by BEL
    r"|\x1b[()][A-Z0-9]"        # character-set selection
)


def strip_ansi(line: str) -> str:
    """Remove ANSI escape sequences from a line."""
    return _ANSI_RE.sub("", line)


def trim_trailing_chrome(text: str) -> str:
    """Drop agent-TUI chrome from the trailing window of the output.

    Only the last TRIM_WINDOW_LINES lines are ever considered — everything before
    that window is left untouched, even if it looks decorative. Within the
    window, ANY line (not just ones flush against the very end) is dropped
    if — once ANSI escape sequences are stripped for classification purposes
    only — it matches a known Claude Code footer/status pattern (e.g. "auto
    mode on", "-- INSERT --", "esc to interrupt") or has no alphanumeric
    characters (blank lines, box-drawing separators, a bare ❯, colored blank
    bands). Classifying on the ANSI-stripped copy matters because a
    truecolor SGR sequence like "\\x1b[38;2;248;248;242m" is full of digits
    and letters, which would otherwise make a purely decorative line look
    like it has real content. The ORIGINAL (ANSI-laden) line is what
    actually gets dropped or kept. This still keeps real content that
    happens to sit below such chrome — e.g. Claude Code's "⏺ main" / "◯
    general-purpose  ..." agent status lines, which have letters and match
    no chrome pattern. Trailing blank lines left behind by the filtering are
    stripped from the result.
    """
    lines = text.split("\n")
    window_start = max(0, len(lines) - TRIM_WINDOW_LINES)
    kept = lines[:window_start]
    for line in lines[window_start:]:
        classify = strip_ansi(line)
        if _CHROME_RE.search(classify) or not _ALNUM_RE.search(classify):
            continue
        kept.append(line)
    while kept and strip_ansi(kept[-1]).strip() == "":
        kept.pop()
    return "\n".join(kept)


_AGENT_MODE_WINDOW_LINES = 15
_AGENT_MODE_PATTERNS = [
    ("auto", re.compile(r"auto mode on", re.IGNORECASE)),
    ("plan", re.compile(r"plan mode on", re.IGNORECASE)),
    ("bypass", re.compile(r"bypassing permissions", re.IGNORECASE)),
]


def detect_agent_mode(text: str) -> str | None:
    """Scan the trailing _AGENT_MODE_WINDOW_LINES lines of agent output for
    Claude Code's own permission-mode status marker and return a short
    label: "auto" ("auto mode on"), "plan" ("plan mode on"), or "bypass"
    ("bypassing permissions"). Returns None when no marker is visible —
    covers pi and other non-Claude-Code agents, or output where the status
    line isn't in the scanned window. Scans from the end of the window
    backwards so the CLOSEST-to-bottom marker wins if more than one somehow
    appears (the most recent status). Normalizes CRLF and strips ANSI
    itself, so it can be called directly on raw agent output — specifically
    on the PRE-TRIM text, since trim_trailing_chrome removes exactly this
    status line from the displayed output.
    """
    text = text.replace("\r\n", "\n").replace("\r", "")
    lines = text.split("\n")[-_AGENT_MODE_WINDOW_LINES:]
    for line in reversed(lines):
        stripped = strip_ansi(line)
        for label, pattern in _AGENT_MODE_PATTERNS:
            if pattern.search(stripped):
                return label
    return None


_RULE_CHARS = "─━═╌┄┈"
_COLLAPSE_MAX_RUN = 20
_COLLAPSE_FALLBACK_WIDTH = 40
_RULE_CHIP_STYLE = "\x1b[30;46m"  # black on cyan — closest to Claude Code's own chip
_RULE_CHIP_RESET = "\x1b[0m"
_MODE_ANSI = {"auto": "\x1b[33m", "plan": "\x1b[36m", "bypass": "\x1b[31m"}  # yellow/cyan/red
_MODE_LEAD_RULE = 2  # short leading rule before an inlined mode word, e.g. "── auto ..."


def collapse_wide_rules(
    text: str, max_run: int = _COLLAPSE_MAX_RUN, width: int = _COLLAPSE_FALLBACK_WIDTH,
    mode: str | None = None,
) -> str:
    """Collapse over-long horizontal-rule runs (e.g. Claude Code's ~170-char
    input-box border, or full-width message dividers) to fit the actual
    available width, right-aligning any name/label carried on the line.

    At a phone width, RichLog wraps these into several rows that are pure
    rule characters plus one row with a name fragment (e.g. a right-aligned
    session name on the input-box border) — a wall of "stripe" rows with no
    useful information. Detection runs on the ANSI-stripped copy of each
    line, since a run may be interrupted by SGR color-change codes.

    For a line with an over-long run:
      - No other text (a pure divider): collapsed to exactly `width` rule
        characters — one full row, no wrap. `mode` is never applied here.
      - Other text present (e.g. a right-aligned session name): rebuilt as
        `<rule fill><space><chip><space>──`, right-aligned to exactly
        `width` VISIBLE characters (ANSI codes don't count). The text
        fragment is wrapped in a black-on-cyan ANSI chip (`_RULE_CHIP_STYLE`)
        since the original styling was lost when the line was rebuilt from
        its ANSI-stripped copy. If `mode` is given (see detect_agent_mode)
        and there's room for it too, it's inlined as a short colored prefix
        instead: `<lead rule><space><mode><space><rule fill><space><chip>
        ──` — e.g. "── auto ──────────────── herdr-remote-s0 ──" — colored
        per `_MODE_ANSI` (auto=yellow, plan=cyan, bypass=red), still exactly
        `width` visible characters overall. If the text alone is already
        >= width, it's emitted alone (still chip-styled, no mode — no room).

    Lines with no over-long run are returned completely untouched (ANSI and
    all). `width` <= 0 falls back to `_COLLAPSE_FALLBACK_WIDTH`.
    """
    if width <= 0:
        width = _COLLAPSE_FALLBACK_WIDTH
    rule_run_re = re.compile(rf"([{_RULE_CHARS}])\1{{{max_run},}}")
    out_lines = []
    for line in text.split("\n"):
        stripped = strip_ansi(line)
        match = rule_run_re.search(stripped)
        if not match:
            out_lines.append(line)
            continue
        rule_char = match.group(1)
        residue = rule_run_re.sub("", stripped)
        text_fragment = residue.strip(" " + _RULE_CHARS)
        if not text_fragment:
            out_lines.append(rule_char * width)
            continue
        chip = f"{_RULE_CHIP_STYLE}{text_fragment}{_RULE_CHIP_RESET}"
        if len(text_fragment) >= width:
            out_lines.append(chip)
            continue
        suffix = " ──"
        mode_ansi = _MODE_ANSI.get(mode) if mode else None
        # Fixed overhead of the mode-prefixed layout beyond `mode` + `text`:
        # lead rule + space + space + space + suffix.
        mode_overhead = _MODE_LEAD_RULE + 3 + len(suffix)
        if mode_ansi is not None and len(mode) + len(text_fragment) + mode_overhead <= width:
            mode_chip = f"{mode_ansi}{mode}{_RULE_CHIP_RESET}"
            fill = width - len(mode) - len(text_fragment) - mode_overhead
            out_lines.append(
                (rule_char * _MODE_LEAD_RULE) + " " + mode_chip + " "
                + (rule_char * fill) + " " + chip + suffix
            )
            continue
        fill = max(0, width - len(text_fragment) - 1 - len(suffix))
        out_lines.append((rule_char * fill) + " " + chip + suffix)
    return "\n".join(out_lines)


_WIDE_GAP_MIN_SPACES = 9  # collapse runs of MORE than 8 spaces
_WIDE_GAP_RE = re.compile(rf"(?<=\S) {{{_WIDE_GAP_MIN_SPACES},}}(?=\S)")
_WIDE_GAP_REPLACEMENT = " · "


def collapse_wide_gaps(text: str) -> str:
    """Collapse over-long runs of spaces WITHIN a line (same spirit as
    collapse_wide_rules) to a single " · " separator.

    Agent TUIs often right-align stats with huge space gaps, e.g.
    "  ◯ general-purpose  Sleep briefly (footer probe)" followed by ~100
    spaces and then "6s · ↓ 20.8k tokens". At phone width that run wraps
    into a near-empty row plus the stats alone on their own row. Only a run
    with non-space text on BOTH sides is collapsed — pure indentation at
    the start of a line (no text before the run) is left untouched, and
    trailing spaces (no text after) are already harmless and untouched too.
    Detection runs on the ANSI-stripped copy of each line, since a run may
    be interrupted by SGR color-change codes; a line with such a run is
    rebuilt from that stripped copy (losing any intra-line ANSI styling —
    acceptable for a decorative gap), so ordinary lines keep their ANSI
    untouched.
    """
    out_lines = []
    for line in text.split("\n"):
        stripped = strip_ansi(line)
        if _WIDE_GAP_RE.search(stripped):
            out_lines.append(_WIDE_GAP_RE.sub(_WIDE_GAP_REPLACEMENT, stripped))
        else:
            out_lines.append(line)
    return "\n".join(out_lines)


_BULLET_CHARS = "⏺●◯○✻✽✢✶✳⎿"
_GLUED_BULLET_RE = re.compile(
    rf"^((?:\s|{_ANSI_RE.pattern})*[{_BULLET_CHARS}](?:{_ANSI_RE.pattern})*)(?!\s)(?!$)"
)


def normalize_bullet_spacing(text: str) -> str:
    """Insert a space after a leading bullet glyph (⏺ ● ◯ ○ ✻ ✽ ✢ ✶ ✳ ⎿) that
    is glued directly to the text following it (e.g. "⏺main" -> "⏺ main"),
    so output rows don't feel glued to their bullet. Lines that already have
    a space (or nothing at all) after the bullet are left untouched.
    Detection tolerates leading whitespace and interleaved ANSI escape codes
    around the bullet, and never touches anything past the start of the
    line — a bullet glyph appearing mid-line is left alone.
    """
    return "\n".join(
        _GLUED_BULLET_RE.sub(lambda m: m.group(1) + " ", line, count=1)
        for line in text.split("\n")
    )


_DIALOG_OPTION_RE = re.compile(r"^\s*(?:❯\s*)?(\d{1,3})\.\s")
_DIALOG_OPTION_WINDOW_LINES = 15  # a real dialog sits at the bottom, near the input box
_DIALOG_OPTION_MAX = 9


def count_dialog_options(text: str) -> int:
    """Scan the trailing _DIALOG_OPTION_WINDOW_LINES lines of agent output
    for numbered-option dialog lines (e.g. "❯ 1. Yes", "  6. Never ask
    again") and return the highest option number seen, capped at
    _DIALOG_OPTION_MAX. Returns 0 when no numbered option line is found.

    Used to size the remote-control bar's digit row to the actual number of
    options in a blocked prompt, instead of a fixed 1-3. Normalizes CRLF and
    strips ANSI itself, so it can be called directly on raw agent output.
    Only the trailing window is scanned — a numbered-looking line earlier in
    scrollback (e.g. from a past, already-answered prompt) is ignored. A
    normal-prose line that happens to start with "<digit>. " is
    indistinguishable from a real option line and will be counted — an
    accepted imperfection of a purely textual heuristic.
    """
    text = text.replace("\r\n", "\n").replace("\r", "")
    lines = text.split("\n")[-_DIALOG_OPTION_WINDOW_LINES:]
    highest = 0
    for line in lines:
        match = _DIALOG_OPTION_RE.match(strip_ansi(line))
        if match:
            highest = max(highest, int(match.group(1)))
    return min(highest, _DIALOG_OPTION_MAX)


_YN_PROMPT_RE = re.compile(
    r"[(\[]\s*y\s*/\s*n\s*[)\]]"  # "(y/n)", "[y/n]", "[Y/n]", "(y/N)"
    r"|(?<!\w)y\s+or\s+n(?!\w)"  # "y or n"
    r"|(?<!\S)y/n(?!\S)",  # standalone " y/n" token
    re.IGNORECASE,
)


def detect_yn_prompt(text: str) -> bool:
    """Scan the trailing _DIALOG_OPTION_WINDOW_LINES lines of agent output
    for a y/n-style confirmation prompt: "(y/n)", "[y/n]", "[Y/n]", "(y/N)",
    "y or n", or a standalone "y/n" token — case-insensitive. Deliberately
    conservative (each pattern is anchored to the whole y/n token, not just
    the letter "y") so ordinary prose containing the letter "y" (e.g.
    "yarn install") doesn't false-positive. Normalizes CRLF and strips ANSI
    itself, so it can be called directly on raw agent output.
    """
    text = text.replace("\r\n", "\n").replace("\r", "")
    lines = text.split("\n")[-_DIALOG_OPTION_WINDOW_LINES:]
    return any(_YN_PROMPT_RE.search(strip_ansi(line)) for line in lines)


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
        text = payload["result"]["read"]["text"]
        # herdr returns \r\n-terminated lines. Rich's Text.from_ansi treats a
        # trailing \r as carriage-return-overwrite, wiping every line but the
        # last at render time, so normalize line endings here.
        return text.replace("\r\n", "\n").replace("\r", "")

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
STALL_SECONDS = 12.0
PROJECT_CHIP_STYLE = "black on bright_green"


def build_header_text(agent: AgentInfo, status: str) -> Text:
    """Build the detail-screen header, with the project name as a highly
    visible chip (black on bright green) so it's instantly clear which
    session/agent is on screen. bright_green renders well in both truecolor
    and 256-color terminals, unlike a hex color.
    """
    icon = STATUS_ICONS.get(status, "?")
    text = Text()
    text.append(f"{agent.pane_id} · {agent.kind} · ")
    text.append(f" {agent.project} ", style=PROJECT_CHIP_STYLE)
    text.append(f" — {icon} {status}")
    return text


REMOTE_KEYS = {"up": "up", "down": "down", "enter": "enter", "tab": "tab",
               "escape": "esc", "y": "y", "n": "n",
               "1": "1", "2": "2", "3": "3", "4": "4", "5": "5", "6": "6",
               "7": "7", "8": "8", "9": "9"}


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
        # show_command_palette=False: hides the "^p palette" footer entry,
        # which crowds real bindings out at phone width. ctrl+p still opens
        # the command palette (used for screenshots) — this only affects the
        # Footer's own display, not the App-level ctrl+p binding.
        yield Footer(show_command_palette=False)

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
        Binding("k", "toggle_remote", "Key"),
        Binding("n", "next_agent", "Agt", key_display="n/p"),
        Binding("p", "prev_agent", "Agt", show=False),
        Binding("u", "scroll_output('up')", "Scr", key_display="u/d"),
        Binding("d", "scroll_output('down')", "Scr", show=False),
        Binding("m", "cycle_mode", "Mode"),
    ]

    DEFAULT_CSS = """
    AgentDetailScreen #output {
        padding: 0 0 0 1;
    }

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
        self._bar_manual = False  # bar shown via "k" (action_toggle_remote), not auto-shown
        self._last_read = ""  # last fetched content, for sizing the digit row

    def compose(self) -> ComposeResult:
        yield Static(self.pane_id, id="detail-header")
        # min_width=1: RichLog defaults to min_width=78, which at phone
        # widths (e.g. 44 columns) makes it wrap content at 78 and then
        # horizontally CLIP everything past the actual (narrower) viewport
        # width — silently losing chunks of every long line. Force wrapping
        # to always happen at the real viewport width instead.
        yield RichLog(id="output", markup=False, wrap=True, auto_scroll=False, min_width=1)
        with Vertical(id="remote-bar"):
            with Horizontal(id="remote-row1"):
                for key_name, label in [("up", "↑"), ("down", "↓"), ("enter", "Enter"),
                                        ("esc", "Esc"), ("y", "y"), ("n", "n")]:
                    yield Button(label, id=f"rk-{key_name}")
            # Digit row: all 9 pre-created (simpler and less flicker-prone than
            # mounting/removing Buttons), only 1..count visible at a time —
            # see _set_digit_count(). Its own row so it can grow independently
            # of row1 and still fit a 44-col phone screen for the common case.
            with Horizontal(id="remote-row2"):
                for i in range(1, 10):
                    yield Button(str(i), id=f"rk-{i}")
            yield Static("tap buttons to answer · n/p = next/prev agent", id="remote-hint")
        yield Input(placeholder="prompt… (i to focus)", id="prompt")
        # show_command_palette=False: hides the "^p palette" footer entry,
        # which crowds real bindings out at phone width. ctrl+p still opens
        # the command palette (used for screenshots) — this only affects the
        # Footer's own display, not the App-level ctrl+p binding. compact=True
        # trims the per-entry padding, and Key/Agt/Scr are abbreviated (from
        # Keys/Agent/Scroll), so all 6 labels (Back/Prompt/Key/Agt/Scr/Mode)
        # actually fit within a 44-column phone screen instead of getting
        # clipped.
        yield Footer(show_command_palette=False, compact=True)

    def on_mount(self) -> None:
        self.query_one("#remote-bar").display = False
        self._sync_remote_bar_buttons()
        self.refresh_header()
        self.refresh_output()
        self.watch(self.query_one(RichLog), "scroll_y", self.on_scroll_moved, init=False)
        self.set_interval(READ_POLL_SECONDS, self._tick)

    def _set_digit_count(self, count: int) -> None:
        for i in range(1, 10):
            self.query_one(f"#rk-{i}", Button).display = i <= count

    def _sync_remote_bar_buttons(self) -> None:
        """Show only contextually relevant remote-bar buttons: the
        navigation core (up/down/enter/esc) is always available while the
        bar is open; digit buttons 1..count_dialog_options(...) and the y/n
        buttons appear only when the agent's effective status is
        "blocked" AND the corresponding pattern is actually detected in
        the last-read content — no fallback minimum, no dialog means no
        digits. Gating on "blocked" (not just the text heuristics) matters:
        without it, the user's own conversation text mentioning "(y/n)" or
        a numbered list (e.g. discussing this very feature) could
        false-positive and light up answer buttons with no real dialog
        present. Recomputed on every refresh (see
        refresh_output/refresh_header/action_toggle_remote) so the bar
        adapts as content and status change. The hint line shortens when
        there are no answer buttons to tap.
        """
        a = self._agent()
        is_blocked = a is not None and effective_status(a, self.app.seen) == "blocked"
        count = count_dialog_options(self._last_read) if is_blocked else 0
        self._set_digit_count(count)
        yn = detect_yn_prompt(self._last_read) if is_blocked else False
        self.query_one("#rk-y", Button).display = yn
        self.query_one("#rk-n", Button).display = yn
        hint = self.query_one("#remote-hint", Static)
        if count > 0 or yn:
            hint.update("tap buttons to answer · n/p = next/prev agent")
        else:
            hint.update("n/p = next/prev agent")

    def _tick(self) -> None:
        if self.app.screen is not self:
            return
        if self.app.agents and self._agent() is None:
            # The agent list has loaded and this pane isn't in it: it's truly
            # gone, not just a stale/paused view. refresh_output() alone won't
            # catch this while follow is paused (it early-returns without
            # calling read_agent), so recover explicitly here.
            self.app.handle_agent_error(
                self.pane_id, HerdrError("agent_not_found", f"agent target {self.pane_id} not found"))
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
        self.query_one("#detail-header", Static).update(build_header_text(a, st))
        bar = self.query_one("#remote-bar")
        if st == "blocked" and not self._auto_shown:
            bar.display = True
            self._auto_shown = True
            self._bar_manual = False
            self._sync_remote_bar_buttons()
        elif st != "blocked":
            # Auto-hide only a bar that WE auto-showed, not one the user
            # opened manually via "k" — that stays open across the flip.
            if bar.display and not self._bar_manual:
                bar.display = False
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
        self._last_read = content  # for _sync_remote_bar_buttons()
        log = self.query_one(RichLog)
        log.clear()
        # Belt and braces: HerdrClient already normalizes \r\n, but strip any
        # stray \r here too so Text.from_ansi never treats it as a
        # carriage-return-overwrite (which wipes all but the last line).
        content = content.replace("\r\n", "\n").replace("\r", "")
        # Detect the agent's permission mode on the PRE-TRIM text — the
        # status line this reads is exactly what trim_trailing_chrome
        # removes from the displayed output below. Threaded into
        # collapse_wide_rules further down, which inlines it onto the
        # session border row.
        mode = detect_agent_mode(content)
        # Insert a space after a leading bullet glyph glued to its text
        # (e.g. "⏺main" -> "⏺ main") — rows otherwise feel glued together.
        content = normalize_bullet_spacing(content)
        # Trim trailing agent-TUI chrome (separators, empty prompt box, footer
        # status line) — display-only, the client stays a faithful reader.
        content = trim_trailing_chrome(content)
        # Collapse huge mid-line space runs (right-aligned stats separated
        # from the text before them by ~100 spaces) to " · " — otherwise
        # they wrap into a near-empty row plus the stats alone at phone
        # width.
        content = collapse_wide_gaps(content)
        # Collapse full-width rule runs (input-box borders, message dividers)
        # that would otherwise wrap into several useless "stripe" rows at
        # phone width. Use the RichLog's actual usable width so the collapsed
        # rule fills the row without wrapping. The detected permission mode
        # (if any) is inlined onto the session border row (the one rule row
        # that carries text) — see collapse_wide_rules' mode param.
        width = log.scrollable_content_region.width or _COLLAPSE_FALLBACK_WIDTH
        content = collapse_wide_rules(content, width=width, mode=mode)
        log.write(Text.from_ansi(content))
        # immediate=True: apply synchronously so scroll_y/max_scroll_y are consistent
        # right away (a deferred scroll_end leaves scroll_y stale against the freshly
        # rewritten content, which corrupts the next is_vertical_scroll_end check).
        log.scroll_end(animate=False, immediate=True)
        self._sync_remote_bar_buttons()

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
        self._bar_manual = bar.display
        if bar.display:
            self._sync_remote_bar_buttons()

    def action_scroll_output(self, direction: str) -> None:
        # Screen-level binding so it works regardless of which widget has focus
        # (touch clients like Termius can't send wheel events; physical arrows
        # only reach the RichLog while it's focused, which is fragile after
        # tapping other widgets). The Input widget consumes/stops printable
        # keys itself before they'd ever reach this binding, so typing "u"/"d"
        # into the prompt still inserts characters instead of scrolling.
        log = self.query_one(RichLog)
        half_page = max(1, log.size.height // 2)
        delta = -half_page if direction == "up" else half_page
        log.scroll_relative(y=delta, animate=False, immediate=True)
        # scroll_y's reactive watcher isn't guaranteed to fire synchronously
        # within this call (see on_scroll_moved's other callers below); poke
        # it explicitly so follow updates immediately.
        self.on_scroll_moved()

    def action_cycle_mode(self) -> None:
        # ctrl+p is Claude Code's own binding for cycling its permission
        # mode (auto/plan/bypass); verified as an accepted key spelling for
        # `herdr pane send-keys` on a live scratch pane before wiring this
        # up. len("ctrl+p") > 1, so HerdrClient.send_key routes it through
        # send-keys, not send-text. The inlined mode on the session border
        # row (see refresh_output/collapse_wide_rules) only reflects the
        # change on the next READ_POLL_SECONDS refresh.
        try:
            self.app.client.send_key(self.pane_id, "ctrl+p")
        except HerdrError as err:
            self.app.notify(err.message, title=err.code, severity="error")
            return
        self.app.notify("Mode cycle sent", severity="information")

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


class HerdrMobileApp(App):
    TITLE = "herdr-mobile"

    def __init__(self, client) -> None:
        super().__init__()
        self.client = client
        self.agents: list[AgentInfo] = []
        self.seen: set[str] = set()
        self.pending_prompts: dict[str, float] = {}
        # Panes that already had one stale-and-still-idle/blocked observation
        # (see refresh_agents): a second consecutive one is required before
        # warning, since list-poll data can lag up to LIST_POLL_SECONDS
        # behind a read that already saw the prompt land.
        self._stale_strikes: set[str] = set()

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

        live_pane_ids = {a.pane_id for a in self.agents}
        self.pending_prompts = {p: t for p, t in self.pending_prompts.items() if p in live_pane_ids}
        self._stale_strikes &= self.pending_prompts.keys()

        if list_screen is not None:
            list_screen.render_agents()
            list_screen.clear_error()

        now = time.monotonic()
        for pane_id, sent_at in list(self.pending_prompts.items()):
            if now - sent_at < STALL_SECONDS:
                continue
            agent = next((a for a in self.agents if a.pane_id == pane_id), None)
            if agent and agent.status in ("idle", "blocked"):
                if pane_id in self._stale_strikes:
                    # Second consecutive stale-and-still-idle/blocked
                    # observation: warn and stop tracking.
                    self.notify(f"Prompt may not have arrived (agent still {agent.status})",
                                title="prompt stall", severity="warning")
                    del self.pending_prompts[pane_id]
                    self._stale_strikes.discard(pane_id)
                else:
                    # First strike: give it one more refresh before concluding
                    # the prompt actually stalled.
                    self._stale_strikes.add(pane_id)
            else:
                # Any different status (agent progressed, or is gone) drops
                # silently, strike or not.
                del self.pending_prompts[pane_id]
                self._stale_strikes.discard(pane_id)

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
    HerdrMobileApp(HerdrClient()).run()


if __name__ == "__main__":
    main()
