# Herdr Remote — Mobile TUI Design

**Date:** 2026-08-09
**Status:** approved (brainstorming session herdr-remote-s0)

## Purpose

A mobile-friendly TUI for triaging and controlling Herdr coding agents from a
phone. The user SSHes into the Mac (Termius, typically over Tailscale), runs
`herdr-remote`, and gets a phone-sized interface to: see all live agents at a
glance, read any agent's live output, send it a prompt, and answer approval
dialogs of `blocked` agents — without opening the full Herdr TUI.

Success criteria: the loop "open list → open agent → read → prompt or unblock
→ next agent" is comfortable on a portrait phone screen, using taps and plain
letter keys (no reliance on the physical Esc key).

## Architecture

- Single Python file `herdr_remote.py` with PEP 723 inline metadata; only
  dependency is `textual`. Run via `uv run`.
- Launcher: executable wrapper script `herdr-remote` installed to
  `~/.local/bin` (on PATH in interactive shells) that execs `uv run` on the
  repo's `herdr_remote.py` by absolute path, so it works from any cwd after
  SSH.
- All Herdr interaction goes through the `herdr` CLI (subprocess, JSON
  responses). No direct socket protocol use — protocol changes are absorbed
  by the CLI.
- The tool runs in the SSH session, **outside** any Herdr-managed pane
  (`HERDR_ENV` unset). Therefore every command targets an explicit pane ID
  taken from `herdr agent list` — never the "current" or focused pane, and
  the tool never issues focus-changing commands.

## Components

### HerdrClient

The only module that knows about subprocess. Methods:

- `list_agents()` → `herdr agent list` → list of agent dicts (pane_id,
  agent kind, name, agent_status, cwd, workspace/tab ids).
- `read_agent(pane_id, lines=200)` → `herdr agent read <pane_id> --source
  recent-unwrapped --format ansi --lines 200` → ANSI text.
- `prompt_agent(pane_id, text)` → `herdr agent prompt <pane_id> <text>`
  (no `--wait`; fire-and-forget).
- `send_key(pane_id, key)` → `herdr agent send-keys <pane_id> <key>`.

CLI server errors arrive as JSON on stderr with exit 1; syntax errors exit 2.
The client raises a typed error carrying the parsed message; screens render
it as a toast, never a stacktrace.

### AgentListScreen

- One row per agent: status icon + color (blocked=red, done=green,
  working=blue, idle=gray), agent kind, project (basename of cwd), agent
  name when set, pane_id.
- Sort order for triage: blocked, done, working, idle.
- Polls `list_agents()` every 3 s.
- Keys: arrows or `j`/`k` select, `Enter` open detail, `r` manual refresh,
  `q` quit. Rows are tappable (Textual mouse support; Termius sends taps as
  clicks).

### AgentDetailScreen

Layout, top to bottom:

1. Header: pane_id, kind, project, live status (updates from the list poll).
2. Output area: ANSI-rendered recent output, polled every 2 s while the
   screen is open. Auto-follows the tail; scrolling up pauses follow until
   the user returns to the bottom.
3. Remote-control bar (hidden by default): tappable buttons
   `[↑] [↓] [Enter] [Esc] [y] [n] [1] [2] [3]`, each mapped to
   `send_key`. Toggled with `k`; shown automatically when the agent's
   status becomes `blocked`. While visible, a whitelist of physical keys
   (arrows, Enter, Tab, y, n, digits, Esc) is forwarded to the agent;
   all other keys stay local; `q` closes the bar. Free-text typing is NOT
   forwarded — the whitelist is exactly what agent dialogs need.
4. Prompt bar: single-line Input. `i` or tap focuses it; `Enter` sends via
   `prompt_agent` and clears it only on success; tap outside or the `[✕]`
   button unfocuses without sending.
5. Footer: key hints.

Navigation: `n`/`p` jump to next/previous agent in the current list order
without returning to the list; `q` (or Esc, as an alias) goes back to the
list. The design never requires the physical Esc key.

### Toasts

Non-blocking notifications for: prompt sent, `agent_prompt_stalled` (the
prompt text stays in the input for retry), agent disappeared, CLI errors.

## Data flow

- Two poll cadences: agent list every 3 s (feeds both screens' status),
  output read every 2 s (only for the open agent).
- Prompt is fire-and-forget: the user sees the agent start working in the
  live output; no blocking wait in the UI.
- `done` state caveat: CLI reads do not mark an agent's work as seen in
  Herdr, so `done` persists server-side. The tool keeps a local
  "seen" set (session-scoped): after the user opens a `done` agent's
  detail, the list renders it as idle-equivalent to avoid re-triaging the
  same finished work.

## Error handling

- Herdr server down / socket missing → full-screen error state with a
  retry action; the app does not crash.
- Agent disappears (pane closed) while its detail is open → toast + return
  to the list.
- `agent_prompt_stalled` (no lifecycle change within 5 s of a prompt) →
  toast; input text preserved.
- Any other CLI error → toast with the parsed server message.

## Testing

- `HerdrClient`: unit tests against JSON fixtures captured from the real
  CLI (agent list, errors).
- Screens: Textual `run_test` pilot tests with a scriptable
  `FakeHerdrClient` (scenarios: triage sort, open/cycle agents, prompt
  success and stalled, blocked → remote-control → send-keys → working,
  agent disappearing mid-view).
- Final manual smoke test from Termius against the live session.

## Out of scope (v1)

- Starting new agents, killing/interrupting agents (ctrl+c) — add later if
  needed.
- Multiline prompt editor.
- Plain (non-agent) pane control.
- Auto-launching the TUI on SSH login (backlog P2 in vault).
