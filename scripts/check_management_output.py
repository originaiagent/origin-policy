#!/usr/bin/env python3
"""CLI wrapper — equivalent to ``python -m origin_policy.check_management_output``.

Allows calling ``python scripts/check_management_output.py ...`` directly
without installing the package (e.g. from Automator service or Linux notify-send).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from origin_policy.check_management_output import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
