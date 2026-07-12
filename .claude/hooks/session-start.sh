#!/bin/bash
set -euo pipefail

# クラウドモード（iPhone Claude Code等）のみで実行
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

pip install -r "$CLAUDE_PROJECT_DIR/requirements.txt" --quiet
