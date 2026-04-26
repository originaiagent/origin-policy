"""管理クロード（Claude.ai web UI）出力の Policy Gate 検査 — 手動運用版。

レーン 1 で実装済みの :func:`origin_policy.policy_gate.check` を
``input_type="management_output"`` で呼ぶ薄い CLI wrapper。
出力は人間可読をデフォルトとし、``--json`` で生レポート JSON を出力できる。

Usage::

    pbpaste | python -m origin_policy.check_management_output
    echo "テキスト" | python -m origin_policy.check_management_output
    python -m origin_policy.check_management_output --file path/to/text.md
    python -m origin_policy.check_management_output --json < text.md

Exit codes::

    0 — PASS or WARN
    1 — BLOCK
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from origin_policy.policy_gate import check


def _format_finding_human(finding: dict) -> str:
    rule = finding.get("rule", "?")
    pattern_id = finding.get("pattern_id", "?")
    match = finding.get("match", "")
    position = finding.get("position")
    message = finding.get("message", "").strip()
    pos_str = f" @ pos {position}" if position is not None else ""
    snippet = match if len(match) <= 80 else match[:77] + "..."
    return (
        f"  - [{rule}/{pattern_id}] {snippet!r}{pos_str}\n"
        f"    → {message}"
    )


def _print_human(result: dict, out=None) -> None:
    if out is None:
        out = sys.stdout
    status = result["status"]
    findings = result["findings"]
    blocks = [f for f in findings if f.get("severity") == "block"]
    warns = [f for f in findings if f.get("severity") == "warn"]

    if status == "BLOCK":
        print(f"[Policy Gate] BLOCK — {len(blocks)} violation(s)", file=out)
        for f in blocks:
            print(_format_finding_human(f), file=out)
        if warns:
            print(f"\n  (additionally {len(warns)} warning(s))", file=out)
            for f in warns:
                print(_format_finding_human(f), file=out)
        print(
            "\n書き換え推奨: 内部 ID（Phase ID / UUID）は本文末尾の「参照」欄に分離し、"
            "保留質問・選択肢提示・「即決すべきなら言って」等の自己申告は削除して即決してください。",
            file=out,
        )
    elif status == "WARN":
        print(f"[Policy Gate] WARN — {len(warns)} suggestion(s)", file=out)
        for f in warns:
            print(_format_finding_human(f), file=out)
    else:
        print("[Policy Gate] PASS", file=out)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_management_output",
        description=(
            "管理クロード（Claude.ai web UI）出力の Policy Gate 検査。"
            " 標準入力からテキストを読み、R1/R3/R5 検査を実施する。"
        ),
    )
    parser.add_argument(
        "--file",
        default=None,
        help="入力ファイルパス（省略時は stdin）。",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="policy_gate の生レポート JSON を出力（人間可読出力を抑止）。",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="出力を抑止し終了コードのみ返す。",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    else:
        if hasattr(sys.stdin, "reconfigure"):
            try:
                sys.stdin.reconfigure(encoding="utf-8")
            except Exception:
                pass
        # Avoid silently hanging when invoked interactively without a pipe.
        if sys.stdin.isatty():
            print(
                "stdin から検査対象テキストを読みます。終了は Ctrl-D。"
                "（パイプ・リダイレクトなしで起動した場合のみ表示）",
                file=sys.stderr,
            )
        text = sys.stdin.read()

    text = text.replace("\r\n", "\n")

    result = check(text, "management_output")

    if not args.quiet:
        if args.as_json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            _print_human(result)

    return 1 if result["status"] == "BLOCK" else 0


if __name__ == "__main__":
    sys.exit(main())
