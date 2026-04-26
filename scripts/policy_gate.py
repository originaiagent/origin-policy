#!/usr/bin/env python3
"""CLI wrapper — equivalent to ``python -m origin_policy.policy_gate``.

Allows calling ``python scripts/policy_gate.py ...`` directly without installing
the package.
"""

import sys
from pathlib import Path

# Make the project root importable so ``origin_policy`` resolves.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from origin_policy.policy_gate import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
