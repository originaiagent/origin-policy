#!/usr/bin/env python3
"""CLI wrapper for ad-hoc classifier inspection.

Usage:
    echo "親ゴールを変えますか" | python scripts/classifier.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from origin_policy.classifier import classify, classify_all  # noqa: E402


def main() -> int:
    text = sys.stdin.read()
    primary = classify(text)
    all_matches = classify_all(text)
    print(f"primary: {primary}")
    print(f"all:     {all_matches}")
    return 0 if primary is not None else 1


if __name__ == "__main__":
    sys.exit(main())
