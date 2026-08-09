# herdr-remote

A phone-friendly TUI for triaging and controlling [Herdr](https://herdr.dev)
coding agents from an SSH session — open Termius on your phone, SSH into the
Mac, run `herdr-remote`, and you get a portrait-sized list of every live
agent, its live output, a prompt box, and a tappable key row for answering
`blocked` approval prompts — without opening the full Herdr TUI.

Single-file Python + [Textual](https://textual.textualize.io/) app
(`herdr_remote.py`) that wraps the `herdr` CLI (JSON in, JSON out). No direct
socket protocol use.

## Usage

```bash
herdr-remote
```

Requires `uv` on `PATH` (`brew install uv`) and the `herdr` CLI on `PATH`.
`herdr-remote` execs `uv run` on `herdr_remote.py`, which declares its own
dependencies (PEP 723 inline metadata — just `textual`), so no virtualenv
setup is needed.

### Install

```bash
mkdir -p ~/.local/bin
cp bin/herdr-remote ~/.local/bin/herdr-remote
```

Make sure `~/.local/bin` is on `PATH` in your interactive shell
(`zsh -ic 'command -v herdr-remote'` should print the path).

## Key map

### Agent list screen

| Key | Action |
|---|---|
| `j` / `k` | Move selection down / up |
| `enter` | Open selected agent |
| `r` | Refresh list |
| `q` | Quit app |

Agents are shown in triage order: `blocked` → `done` → `working` → `idle` →
`unknown`. If `herdr` can't be reached, an error banner replaces the table;
`r` retries.

### Agent detail screen

| Key | Action |
|---|---|
| `i` | Focus the prompt box (type, then `enter` to send) |
| `k` | Toggle the remote-control key bar |
| `n` / `p` | Cycle to next / previous agent (list order) |
| `q` / `esc` | Back to list — while the remote-control bar is open, `q` closes the bar first |

The output pane follows the agent's live output automatically; scrolling up
pauses following (so you can read history without it jumping), scrolling
back to the bottom resumes it.

The remote-control bar (`k`) shows tappable buttons — `↑ ↓ Enter Esc y n 1 2
3` — for answering an agent's own approval prompts (e.g. a `blocked`
Claude Code permission dialog) by key passthrough. It also auto-opens the
first time an agent goes `blocked`. While it's open, the same physical keys
on a real keyboard are forwarded too.

## Termius note

Everything in the UI is tappable (row selection, buttons, prompt input), so
a bare Termius session works with no extra setup. An extra-keys row (for
`Esc`, `Tab`, arrows) is optional convenience, not required — the
remote-control bar exists specifically so you don't need one to answer a
`blocked` agent's prompt.

## Pointers

- Design spec: `docs/superpowers/specs/2026-08-09-herdr-mobile-tui-design.md`
- Project state / decisions / session notes: vault
  `~/Documents/obsidian-claude/herdr-remote/`
