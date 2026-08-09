#!/bin/sh
# Install herdr-mobile with a single command:
#
#   curl -fsSL https://raw.githubusercontent.com/bsorescu/herdr-mobile/main/install.sh | sh
#
# Installs (or upgrades) herdr-mobile via `uv tool install`. Installs uv
# itself first if it isn't already on PATH. POSIX sh, no bashisms.
set -eu

REPO_URL="git+https://github.com/bsorescu/herdr-mobile"

echo "herdr-mobile installer"
echo

if ! command -v uv >/dev/null 2>&1; then
    echo "uv not found on PATH -- installing it first..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # The official installer puts uv in ~/.local/bin; add it to PATH for the
    # rest of this script (a fresh shell will pick it up on its own via the
    # installer's own shell profile edits).
    PATH="$HOME/.local/bin:$PATH"
    export PATH
    if ! command -v uv >/dev/null 2>&1; then
        echo "uv installation did not put 'uv' on PATH as expected; aborting." >&2
        echo "See https://docs.astral.sh/uv/getting-started/installation/ for manual install." >&2
        exit 1
    fi
    echo
fi

echo "Installing herdr-mobile (uv tool install --force $REPO_URL)..."
uv tool install --force "$REPO_URL"
echo

BIN_PATH="$(uv tool dir --bin 2>/dev/null || true)"
if [ -n "$BIN_PATH" ] && [ -x "$BIN_PATH/herdr-mobile" ]; then
    echo "Installed: $BIN_PATH/herdr-mobile"
else
    BIN_PATH=""
    echo "Installed herdr-mobile (could not determine the exact install path)."
fi

echo

if ! command -v herdr >/dev/null 2>&1; then
    echo "WARNING: the 'herdr' CLI is not on your PATH."
    echo "herdr-mobile needs a running Herdr -- https://herdr.dev"
fi

if ! command -v herdr-mobile >/dev/null 2>&1; then
    if [ -n "$BIN_PATH" ]; then
        echo "NOTE: $BIN_PATH is not on your current PATH."
        echo "Add this to your shell profile (e.g. ~/.zshrc or ~/.bashrc):"
        echo
        echo "    export PATH=\"$BIN_PATH:\$PATH\""
        echo
    else
        echo "NOTE: herdr-mobile was installed but is not on your current PATH."
        echo "Check 'uv tool dir --bin' for its location and add it to your PATH."
        echo
    fi
fi

echo "Done. Run: herdr-mobile"
