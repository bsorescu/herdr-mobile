# Herdr Remote — Project Instructions

Mobile-friendly TUI for controlling Herdr coding agents from a phone over SSH
(Termius → Mac → `herdr` socket API). Lets you triage the agent list, read an
agent's live output, send prompts, and unblock `blocked` agents via key
passthrough — without opening the full Herdr TUI. Stack: Python + Textual,
wrapping the `herdr` CLI (JSON responses).

## Instruction ownership (ADR-006)

One instruction = one mechanism. Never duplicate an instruction across
mechanisms — link to its owner instead.

| Mechanism | Owns | Loaded |
|---|---|---|
| `CLAUDE.md` (this file) | Facts and pointers: what this project is, where things live | Every session, in full |
| Vault `~/Documents/obsidian-claude/herdr-remote/` | State (current-state.md), decisions (ADRs), plans, session notes | Read at session start per global tracking rule |
| `~/.claude/skills/herdr` | How to drive the `herdr` CLI (agent/pane commands, lifecycle states) | On invocation |

## Conventions

- UI text and code identifiers in English; vault content and user
  communication in Romanian.
- The `herdr` CLI is the integration surface — no direct socket protocol use.
  Verify command syntax against `herdr <group>` help, not memory.

## Pointers

- Current state (SSOT): vault `herdr-remote/context/herdr-remote/current-state.md`
- Design spec: `docs/superpowers/specs/2026-08-09-herdr-mobile-tui-design.md` (when written)
