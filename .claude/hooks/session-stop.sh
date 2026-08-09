#!/bin/bash
# Stop hook (AREOS): (1) checklist reminder — once per session, only when
# uncommitted changes exist; (2) chain-lint violations — every stop, they
# nag until fixed. Silent when clean.

REPO="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
SLUG=$(cat "$REPO/.claude/areos-project" 2>/dev/null || basename "$REPO" | tr 'A-Z' 'a-z')
input=$(cat)

if command -v jq >/dev/null 2>&1; then
  session_id=$(printf '%s' "$input" | jq -r '.session_id // empty' 2>/dev/null)
else
  session_id=$(printf '%s' "$input" | sed -n 's/.*"session_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
fi
session_id=${session_id//[^a-zA-Z0-9-]/_}   # filename-safe
session_id=${session_id:-pid$$}             # empty id must not share a marker

mdir="${TMPDIR:-/tmp}/areos-markers"
mkdir -p -m 700 "$mdir" 2>/dev/null
marker="$mdir/stop-$session_id"

reminder=""
if [ ! -e "$marker" ]; then
  repo_dirty=$(git -C "$REPO" status --porcelain 2>/dev/null | head -1)
  vault_dirty=$(git -C "$HOME/Documents/obsidian-claude" status --porcelain -- "$SLUG/" 2>/dev/null | head -1)
  if [ -n "$repo_dirty" ] || [ -n "$vault_dirty" ]; then
    touch "$marker"
    reminder="AREOS ($SLUG): uncommitted changes exist (repo and/or vault $SLUG/). Run the end-of-session checklist from ~/.claude/rules/obsidian-project-tracking.md before the session ends. (Reminder fires once per session.)"
  fi
fi

lint=$("$REPO/.claude/hooks/chain-lint.sh" 2>/dev/null)

msg="$reminder"
[ -n "$lint" ] && msg="${msg:+$msg
}chain-lint violations (fix before closing):
$lint"

if [ -n "$msg" ]; then
  python3 -c 'import json,sys; print(json.dumps({"hookSpecificOutput":{"hookEventName":"Stop","additionalContext":sys.argv[1]}}))' "$msg" 2>/dev/null
fi
exit 0
