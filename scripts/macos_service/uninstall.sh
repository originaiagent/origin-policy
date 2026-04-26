#!/usr/bin/env bash
# Remove the Policy Gate Quick Action from ~/Library/Services.
set -euo pipefail

WORKFLOW_DST="$HOME/Library/Services/PolicyGateCheck.workflow"

if [ -d "$WORKFLOW_DST" ]; then
    rm -rf "$WORKFLOW_DST"
    echo "✓ Removed: $WORKFLOW_DST"
else
    echo "(not installed: $WORKFLOW_DST)"
fi

# Clear any legacy launchctl env vars from prior installs (no-op if absent).
launchctl unsetenv ORIGIN_POLICY_REPO 2>/dev/null || true
launchctl unsetenv ORIGIN_POLICY_PYTHON 2>/dev/null || true
