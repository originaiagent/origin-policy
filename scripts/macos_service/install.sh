#!/usr/bin/env bash
# Install the Policy Gate Quick Action into ~/Library/Services so the macOS
# Services menu (right-click → サービス → "Policy Gate で検査") can invoke it.
#
# Usage:
#   ./install.sh                       # auto-detect repo root (parent of scripts/)
#   ORIGIN_POLICY_REPO=~/dev/origin-policy ./install.sh
#
# Sets ORIGIN_POLICY_REPO and ORIGIN_POLICY_PYTHON for the Quick Action via
# launchctl setenv (persists for the current login session). Re-run after a
# reboot or set them in ~/.zprofile / ~/.zshrc and re-login for permanence.
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

mkdir -p "$SERVICES_DIR"
rm -rf "$WORKFLOW_DST"
cp -R "$WORKFLOW_SRC" "$WORKFLOW_DST"

launchctl setenv ORIGIN_POLICY_REPO "$REPO"
launchctl setenv ORIGIN_POLICY_PYTHON "$PYTHON_BIN"

echo "✓ Installed: $WORKFLOW_DST"
echo "  ORIGIN_POLICY_REPO=$REPO"
echo "  ORIGIN_POLICY_PYTHON=$PYTHON_BIN"
echo
echo "次の手順:"
echo "  1. システム設定 → キーボード → キーボードショートカット → サービス"
echo "  2. テキスト > 'Policy Gate で検査' を有効化"
echo "  3. 任意のテキスト選択 → 右クリック → サービス → 'Policy Gate で検査'"
echo
echo "永続化したい場合は ~/.zprofile に追記:"
echo "  export ORIGIN_POLICY_REPO=\"$REPO\""
echo "  export ORIGIN_POLICY_PYTHON=\"$PYTHON_BIN\""
