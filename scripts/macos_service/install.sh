#!/usr/bin/env bash
# Install the Policy Gate Quick Action into ~/Library/Services so the macOS
# Services menu (right-click → サービス → "Policy Gate で検査") can invoke it.
#
# Usage:
#   ./install.sh                       # auto-detect repo root (parent of scripts/)
#   ORIGIN_POLICY_REPO=~/dev/origin-policy ./install.sh
#
# Bakes the absolute paths to the repo and python interpreter directly into the
# *installed* workflow (the source workflow keeps the placeholders so the repo
# stays portable). No env-var dependence at runtime — survives reboots.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

REPO="${ORIGIN_POLICY_REPO:-$REPO_ROOT}"
PYTHON_BIN="${ORIGIN_POLICY_PYTHON:-/usr/bin/python3}"

WORKFLOW_SRC="$SCRIPT_DIR/PolicyGateCheck.workflow"
SERVICES_DIR="$HOME/Library/Services"
WORKFLOW_DST="$SERVICES_DIR/PolicyGateCheck.workflow"

if [ ! -d "$WORKFLOW_SRC" ]; then
    echo "✗ Workflow source not found: $WORKFLOW_SRC" >&2
    exit 1
fi

if ! "$PYTHON_BIN" -c "import yaml, jsonschema" >/dev/null 2>&1; then
    echo "✗ Python deps missing. Install with: $PYTHON_BIN -m pip install pyyaml jsonschema" >&2
    exit 1
fi

# Escape paths for use as a sed replacement (escape backslash, ampersand, and pipe-delimiter).
sed_escape() {
    printf '%s' "$1" | sed -e 's/[\\&|]/\\&/g'
}
REPO_ESC="$(sed_escape "$REPO")"
PY_ESC="$(sed_escape "$PYTHON_BIN")"

mkdir -p "$SERVICES_DIR"
rm -rf "$WORKFLOW_DST"
cp -R "$WORKFLOW_SRC" "$WORKFLOW_DST"

WFLOW="$WORKFLOW_DST/Contents/document.wflow"
sed -i '' \
    -e "s|__ORIGIN_POLICY_REPO__|$REPO_ESC|g" \
    -e "s|__ORIGIN_POLICY_PYTHON__|$PY_ESC|g" \
    "$WFLOW"

# Verify substitution actually happened — guard against placeholder leftovers.
if grep -q '__ORIGIN_POLICY_REPO__\|__ORIGIN_POLICY_PYTHON__' "$WFLOW"; then
    echo "✗ Placeholder substitution failed in $WFLOW" >&2
    exit 1
fi

echo "✓ Installed: $WORKFLOW_DST"
echo "  REPO=$REPO"
echo "  PYTHON=$PYTHON_BIN"
echo
echo "次の手順:"
echo "  1. システム設定 → キーボード → キーボードショートカット → サービス"
echo "  2. テキスト > 'Policy Gate で検査' を有効化（任意でショートカットキー割当）"
echo "  3. 任意のテキスト選択 → 右クリック → サービス → 'Policy Gate で検査'"
