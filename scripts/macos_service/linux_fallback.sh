#!/usr/bin/env bash
# Linux 代替: クリップボードのテキストを Policy Gate で検査し、
# notify-send で結果を通知。
#
# 依存: xclip (or xsel), libnotify-bin (notify-send), python3 + pyyaml + jsonschema
#
# Usage:
#   linux_fallback.sh           # クリップボードを検査
#   linux_fallback.sh --stdin   # stdin を検査
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
REPO="${ORIGIN_POLICY_REPO:-$REPO_ROOT}"
PYTHON_BIN="${ORIGIN_POLICY_PYTHON:-python3}"

if [ "${1:-}" = "--stdin" ]; then
    INPUT=$(cat)
elif command -v xclip >/dev/null 2>&1; then
    INPUT=$(xclip -selection clipboard -o)
elif command -v xsel >/dev/null 2>&1; then
    INPUT=$(xsel --clipboard --output)
else
    echo "✗ xclip / xsel not found. Install one, or pass --stdin." >&2
    exit 2
fi

OUTPUT=$(printf '%s' "$INPUT" | PYTHONPATH="$REPO" "$PYTHON_BIN" -m origin_policy.check_management_output 2>&1)
EXIT=$?

if [ "$EXIT" -eq 1 ]; then
    LEVEL="critical"
    TITLE="Policy Gate: BLOCK"
elif printf '%s' "$OUTPUT" | grep -q WARN; then
    LEVEL="normal"
    TITLE="Policy Gate: WARN"
else
    LEVEL="low"
    TITLE="Policy Gate: PASS"
fi

if command -v notify-send >/dev/null 2>&1; then
    notify-send -u "$LEVEL" "$TITLE" "$(printf '%s' "$OUTPUT" | head -c 240)"
fi

printf '%s\n' "$OUTPUT"
exit "$EXIT"
