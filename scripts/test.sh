#!/bin/sh
cd "$(dirname "$0")/.." || exit 1
exec uv run --with 'pytest>=8' --with 'pytest-asyncio>=0.24' \
  --with 'textual==8.2.8' \
  -m pytest tests/ --asyncio-mode=auto -q "$@"
