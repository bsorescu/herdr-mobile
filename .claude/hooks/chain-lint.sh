#!/bin/bash
# Chain lint (AREOS): mechanical checks on the vault's traceability chain.
# Silent when clean; prints FAIL/WARN lines otherwise. Called by both session
# hooks — the methodology must be able to detect its own non-execution
# (kernel audit 2026-07-05, finding: no verification layer).

# Project slug: .claude/areos-project override, else lowercase repo basename.
REPO="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}"
SLUG=$(cat "$REPO/.claude/areos-project" 2>/dev/null || basename "$REPO" | tr 'A-Z' 'a-z')
VAULT="$HOME/Documents/obsidian-claude/$SLUG"
CS="$VAULT/context/$SLUG/current-state.md"
if [ ! -d "$VAULT" ]; then
  # Silent exit here once hid a misconfigured project for weeks (homelab,
  # 2026-08-03): hooks installed = the project claims AREOS tracking, so a
  # missing vault folder is a defect, not a non-AREOS repo.
  echo "WARN vault folder missing for slug '$SLUG' ($VAULT) — repo name != vault folder? Set the slug in .claude/areos-project"
  exit 0
fi

# --- current-state.md ---
# Three states, never collapsed: missing / unreadable / checked. Under macOS TCC
# stat() is allowed while open() is denied, so the old `[ -f ]` branch ran with
# every read failing: the size check fell through silently and grep reported
# "missing header" — a content verdict on a file nobody could read (aqos-platform,
# 2026-08-06..08, two days of a false WARN). Unreadable is NOT clean.
if [ ! -f "$CS" ]; then
  echo "FAIL current-state.md missing at $CS"
else
  # `wc -c FILE`, not `< FILE`: the shell's own redirect error cannot be
  # silenced with 2>/dev/null and would leak to stderr.
  bytes=$(wc -c "$CS" 2>/dev/null | awk '{print $1}')
  if [ -z "$bytes" ]; then
    echo "FAIL current-state.md UNREADABLE at $CS — checks SKIPPED, not passed. Permission denied? (macOS TCC: grant Full Disk Access to the process hosting the agent, then RESTART it — TCC does not apply to running processes)"
  else
    [ "$bytes" -gt 16384 ] && echo "FAIL current-state.md: $bytes bytes (cap 16 KB, tracking rule; if system description dominates, apply the domain split — ADR-011)"
    grep -q "Ultima actualizare" "$CS" 2>/dev/null || echo "WARN current-state.md: missing 'Ultima actualizare' header"
  fi
fi

# --- domain-state files (ADR-011 split): stale >90 days = the risk the ADR
# accepted with a mitigation nothing verified until now ---
find "$VAULT/context/$SLUG" -maxdepth 1 -name '*.md' ! -name 'current-state.md' -mtime +90 2>/dev/null | while read -r d; do
  echo "WARN domain state $(basename "$d"): untouched >90 days — verify it still matches reality (ADR-011 staleness risk)"
done

# --- plans: completed/abandoned must be archived; active must be in current-state ---
for p in "$VAULT"/plans/*.md; do
  [ -f "$p" ] || continue
  st=$(sed -n 's/^status:[[:space:]]*\([a-z]*\).*/\1/p' "$p" | head -1)
  base=$(basename "$p" .md)
  case "$st" in
    completed|abandoned)
      echo "FAIL plan $base: status '$st' but not moved to plans/archive/" ;;
    active)
      grep -q "$base" "$CS" 2>/dev/null || \
        echo "FAIL plan $base: active but not referenced in current-state.md (Active Work)" ;;
  esac
done

# --- ADRs: status transitions must have their dates; superseded needs superseded_by ---
for a in "$VAULT"/decisions/*.md; do
  [ -f "$a" ] || continue
  base=$(basename "$a" .md)
  st=$(sed -n 's/^status:[[:space:]]*\([a-z]*\).*/\1/p' "$a" | head -1)
  case "$st" in
    implemented)
      grep -q "^date_implemented: null" "$a" && \
        echo "FAIL ADR $base: implemented but date_implemented is null" ;;
    accepted)
      grep -q "^date_accepted: null" "$a" && \
        echo "FAIL ADR $base: accepted but date_accepted is null" ;;
    superseded)
      grep -q "^superseded_by: null" "$a" && \
        echo "FAIL ADR $base: superseded but superseded_by is null" ;;
    "")
      echo "WARN ADR $base: no status field" ;;
  esac
done
exit 0
