#!/bin/bash
# SessionStart hook (AREOS): inject vault current-state + vault git status.
# Plain stdout is added to Claude's context. With --brief (resume matcher):
# inject only a freshness pointer, not the full file — the conversation
# already contains an earlier injection (context-budget audit 2026-07-05).
# NOTE: vault content is injected verbatim into model context — accepted
# risk, same trust domain (user's own vault); revisit if the vault ever
# syncs third-party content.

REPO="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
SLUG=$(cat "$REPO/.claude/areos-project" 2>/dev/null || basename "$REPO" | tr 'A-Z' 'a-z')
VAULT_ROOT="$HOME/Documents/obsidian-claude"
CURRENT_STATE="$VAULT_ROOT/$SLUG/context/$SLUG/current-state.md"

# housekeeping: drop stale once-per-session markers (>7 days)
find "${TMPDIR:-/tmp}/areos-markers" -name 'stop-*' -mtime +7 -delete 2>/dev/null

echo "## AREOS session context ($SLUG, SessionStart hook)"
echo
if [ "$1" = "--brief" ]; then
  echo "current-state.md already injected earlier in this conversation."
  echo "Freshness check — re-read it ONLY if this line is newer than what you have:"
  grep -m1 "Ultima actualizare" "$CURRENT_STATE" 2>/dev/null || echo "(current-state.md not found)"
else
  echo "### Vault SSOT — current-state.md (already injected: do NOT re-read the file)"
  if [ -f "$CURRENT_STATE" ]; then
    head -c 16384 "$CURRENT_STATE"
    [ "$(wc -c < "$CURRENT_STATE")" -gt 16384 ] && echo "" && echo "[TRUNCATED at 16KB — current-state.md exceeds its own cap; fix it]"
  else
    echo "(current-state.md not found at $CURRENT_STATE)"
  fi
fi
echo
echo "### git status — vault, $SLUG/ paths only (repo status is provided natively)"
git -C "$VAULT_ROOT" status -sb -- "$SLUG/" 2>/dev/null | head -n 40 || echo "(vault not a git repo)"

lint=$("$REPO/.claude/hooks/chain-lint.sh" 2>/dev/null)
if [ -n "$lint" ]; then
  echo
  echo "### chain-lint (fix FAILs before new work)"
  echo "$lint"
fi
exit 0
