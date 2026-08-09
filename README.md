# herdr-mobile

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A phone-friendly TUI for triaging and controlling [Herdr](https://herdr.dev)
coding agents from an SSH session. Open [Termius](https://termius.com) (or
any SSH client) on your phone, SSH into the machine running Herdr, run
`herdr-mobile`, and you get a portrait-sized list of every live agent, its
live output, a prompt box, and a tappable key row for answering `blocked`
approval prompts — without opening the full Herdr TUI, and without needing a
physical keyboard.

Why: Herdr's own TUI is built for a wide terminal at a desk. herdr-mobile is
the same control surface reshaped for a narrow touchscreen — everything is
tappable, and the layout, scrolling, and output trimming all assume you're
looking at a phone.

Single-file Python + [Textual](https://textual.textualize.io/) app
(`herdr_mobile.py`) that wraps the `herdr` CLI (JSON in, JSON out). No direct
socket protocol use.

![Agent list screen](docs/demo-list.svg)
![Agent detail screen with remote-control bar](docs/demo-detail.svg)

## Requirements

- A running [Herdr](https://herdr.dev) instance, with the `herdr` CLI on
  `PATH` — version `>=0.7.3` (earlier versions weren't verified against this
  client)
- [`uv`](https://docs.astral.sh/uv/) (`brew install uv`, or see the uv docs
  for other platforms)
- Python `>=3.12` (uv will fetch this for you if it's not already installed)

**Platforms:** tested on macOS; Linux should work identically (nothing
platform-specific — plain Python/Textual over the `herdr` CLI), reports
welcome. Windows is untested and undeclared.

## Install

### Quick install

```bash
curl -fsSL https://raw.githubusercontent.com/bsorescu/herdr-mobile/main/install.sh | sh
```

Installs [`uv`](https://docs.astral.sh/uv/) first if it's missing, then runs
`uv tool install --force` to install (or upgrade) the `herdr-mobile`
command onto your `PATH`. Safe to re-run any time to upgrade. See
`install.sh` in the repo root for exactly what it does before piping it to
`sh`, as always with any curl-pipe-to-shell install.

### Option 1: clone + run

```bash
git clone https://github.com/bsorescu/herdr-mobile.git
cd herdr-mobile
uv run herdr_mobile.py
```

`herdr_mobile.py` declares its own dependencies via PEP 723 inline script
metadata (just `textual`), so `uv run` handles the virtualenv for you — no
separate install step needed.

To put a `herdr-mobile` command on your `PATH`:

```bash
mkdir -p ~/.local/bin
cp bin/herdr-mobile ~/.local/bin/herdr-mobile
```

The wrapper resolves the repo directory from its own location, so it keeps
working if you move the clone or symlink the wrapper elsewhere. Make sure
`~/.local/bin` is on `PATH` in your interactive shell
(`zsh -ic 'command -v herdr-mobile'` should print the path).

### Option 2: `uv tool install`

```bash
uv tool install git+https://github.com/bsorescu/herdr-mobile
```

This installs the packaged `herdr-mobile` entry point (from `pyproject.toml`)
straight onto your `PATH` via `uv`'s tool shims — no clone or manual `PATH`
setup needed.

## Usage

```bash
herdr-mobile
```

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
| `u` / `d` | Scroll output up / down half a page |
| `q` / `esc` | Back to list — but while the remote-control bar is open, neither goes back: `q` closes the bar instead, and `esc` is forwarded to the agent instead (see below) |

The output pane follows the agent's live output automatically; scrolling up
pauses following (so you can read history without it jumping), scrolling
back to the bottom resumes it. `u`/`d` scroll it half a page at a time and
work regardless of which widget has focus (touch clients like Termius can't
send mouse-wheel events, and physical arrow keys only scroll the output
while it's focused) — except while the prompt box is focused, where typing
`u`/`d` inserts the characters instead, same as any other letter.

The remote-control bar (`k`) shows tappable buttons — `↑ ↓ Enter Esc y n 1 2
3` — for answering an agent's own approval prompts (e.g. a `blocked`
Claude Code permission dialog) by key passthrough. It also auto-opens the
first time an agent goes `blocked`. While it's open, physical keyboard keys
are forwarded too for arrows/Enter/Tab/Esc/y/1/2/3 — **but not `n` or
`p`**: those always cycle to the next/previous agent, bar open or closed,
so to answer *No* you have to tap the on-screen `[n]` button (the bar's own
hint line — `tap buttons to answer · n/p = next/prev agent` — says the
same).

## Termius tips

Everything in the UI is tappable (row selection, buttons, prompt input), so
a bare Termius session works with no extra setup — no `Esc` key needed, no
extra-keys row required. An extra-keys row (for `Esc`, `Tab`, arrows) is
optional convenience, not required — the remote-control bar exists
specifically so you don't need one to answer a `blocked` agent's prompt.
The footer entries themselves are tappable too — tapping `Keys` toggles the
remote-control bar, so `k` is never required on touch.

## Troubleshooting

**"herdr CLI not found on PATH"** — herdr-mobile execs `herdr` as a
subprocess; it needs to be resolvable from the same `PATH` the app runs
under. If you installed herdr into a shell-specific location (e.g. via nvm,
pipx, or a login-shell-only PATH addition), check that a non-interactive
shell can still find it, or set `PATH` explicitly before launching
herdr-mobile.

**"Cannot reach herdr"** banner on the agent list — the `herdr` server
itself isn't running, or the `agent list` call errored. Press `r` to retry
once it's back up.

**An agent disappears from the detail screen** — if the pane herdr-mobile
has open closes or gets removed from Herdr's own agent list, herdr-mobile
detects this on its next poll, pops back to the list, and shows a warning
toast (`Agent <pane_id> is gone`).

## Development

Run the test suite:

```bash
./scripts/test.sh
```

This installs its own pinned pytest/pytest-asyncio/textual versions via
`uv run --with ...`, independent of `pyproject.toml`, so it always tests
against the same dependency versions regardless of your local environment.

Regenerate the demo screenshots (`docs/demo-*.svg`) after a UI change:

```bash
uv run scripts/make_demo.py
```

This drives the app headlessly against a fake `HerdrClient` with synthetic
agents — no real Herdr instance required.

## License

MIT — see [LICENSE](LICENSE).
