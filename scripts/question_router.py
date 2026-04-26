#!/usr/bin/env python3
"""Question Router — Claude Code の blocking_question JSON を機械的にルーティング。

Phase 3 Lane 3 — Tier 0 R1 後段の自動分類層。

入力（stdin or --file）: JSON。次のいずれかの形を許容:
  1. blocking_question 単体オブジェクト       {"category": ..., "question": ..., ...}
  2. wrapper 形式                            {"blocking_question": {"category": ..., ...}}

出力 / 終了コード:
  0  — category が 13 enum (human judgment) → stdout に "TOM_INTERRUPT_REQUIRED" マーカー
        + JSON pretty。Tom interrupt を呼び出し側でトリガーする。
  10 — category が 8 enum (AI judgment)     → stdout に管理クロード向けプロンプト。
        実 LLM 呼び出しは Phase 3 では out of scope（プロンプト出力までで完了）。
  2  — schema 違反 (JSON parse 失敗 / category 欠損 / question 欠損 / 両 enum 外)
        → stderr に違反理由。Claude Code に差し戻す。

正本:
  - HUMAN_ENUM (13): rules/human_judgment_categories.yaml（最初の正本、既存 classifier.py と共有）
  - AI_ENUM (8): 本ファイル内 AI_CATEGORIES 定数。将来 yaml 側に ai_categories セクションが
    追加された場合は yaml が優先される（後方互換）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HUMAN_CATEGORIES_YAML = PROJECT_ROOT / "rules" / "human_judgment_categories.yaml"

# AI 判断カテゴリ — Claude Code が自分で決めるべき 8 領域。
# 13 人間判断カテゴリのいずれにも該当しない、かつ AI が即決すべき技術判断。
# 将来 rules/human_judgment_categories.yaml に ai_categories セクションが追加された
# 場合はそちらを優先する（_load_ai_categories 参照）。
AI_CATEGORIES: tuple[str, ...] = (
    "implementation_detail",
    "library_choice",
    "refactor_pattern",
    "test_strategy",
    "naming",
    "error_handling",
    "performance_tuning",
    "code_style",
)

EXIT_HUMAN = 0
EXIT_SCHEMA_VIOLATION = 2
EXIT_AI_ROUTE = 10

TOM_INTERRUPT_MARKER = "TOM_INTERRUPT_REQUIRED"


def _load_human_categories() -> list[str]:
    if not HUMAN_CATEGORIES_YAML.exists():
        return []
    data = yaml.safe_load(HUMAN_CATEGORIES_YAML.read_text(encoding="utf-8")) or {}
    return [c["id"] for c in data.get("categories", []) if "id" in c]


def _load_ai_categories() -> list[str]:
    """yaml 側の ai_categories セクションを優先、なければ AI_CATEGORIES 定数を返す。"""
    if HUMAN_CATEGORIES_YAML.exists():
        data = yaml.safe_load(HUMAN_CATEGORIES_YAML.read_text(encoding="utf-8")) or {}
        yaml_ai = data.get("ai_categories")
        if isinstance(yaml_ai, list) and yaml_ai:
            ids = [c["id"] for c in yaml_ai if isinstance(c, dict) and "id" in c]
            if ids:
                return ids
    return list(AI_CATEGORIES)


def _normalize_input(raw: dict) -> dict | None:
    """blocking_question wrapper 形式と単体オブジェクトの両方を受け付ける。"""
    if not isinstance(raw, dict):
        return None
    if "blocking_question" in raw and isinstance(raw["blocking_question"], dict):
        return raw["blocking_question"]
    return raw


def _build_human_output(payload: dict) -> str:
    return f"{TOM_INTERRUPT_MARKER}\n{json.dumps(payload, ensure_ascii=False, indent=2)}"


def _build_ai_prompt(payload: dict, envelope: dict) -> str:
    """AI 判断時に管理クロードへ渡すプロンプトを組み立てる。

    envelope は wrapper 形式の場合の外側 dict（parent_goal_id / related_guides を含む可能性）。
    """
    category = payload.get("category", "unknown")
    question = payload.get("question", "(質問本文なし)")
    proposed_default = payload.get("proposed_default", "未指定")
    why_blocking = payload.get("why_blocking", "未指定")

    parent_goal_id = (
        envelope.get("parent_goal_id")
        or payload.get("parent_goal_id")
        or "unknown"
    )

    related = (
        envelope.get("related_guides")
        or payload.get("related_guides")
        or []
    )
    if isinstance(related, list):
        related_str = ", ".join(str(s) for s in related) if related else "なし"
    else:
        related_str = str(related)

    return (
        f"[自動ルーティング] AI 判断カテゴリ ({category}) の質問が発生しました。\n"
        f"parent_goal_id: {parent_goal_id}\n"
        f"related_guides: {related_str}\n"
        "\n"
        "質問:\n"
        f"{question}\n"
        "\n"
        f"proposed_default: {proposed_default}\n"
        f"why_blocking: {why_blocking}\n"
        "\n"
        "上記を踏まえ、即決して Claude Code に回答してください。"
    )


def route(input_data: Any) -> tuple[int, str, str]:
    """Return (exit_code, stdout, stderr)."""
    if isinstance(input_data, str):
        text = input_data.strip()
        if not text:
            return EXIT_SCHEMA_VIOLATION, "", "[question_router] empty input"
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as e:
            return (
                EXIT_SCHEMA_VIOLATION,
                "",
                f"[question_router] invalid JSON: {e}",
            )
    else:
        parsed = input_data

    if not isinstance(parsed, dict):
        return (
            EXIT_SCHEMA_VIOLATION,
            "",
            "[question_router] top-level JSON must be an object",
        )

    payload = _normalize_input(parsed)
    if payload is None:
        return (
            EXIT_SCHEMA_VIOLATION,
            "",
            "[question_router] could not extract blocking_question payload",
        )

    category = payload.get("category")
    question = payload.get("question")

    if not category:
        return (
            EXIT_SCHEMA_VIOLATION,
            "",
            "[question_router] missing required field: category",
        )
    if not question:
        return (
            EXIT_SCHEMA_VIOLATION,
            "",
            "[question_router] missing required field: question",
        )

    human = _load_human_categories()
    ai = _load_ai_categories()

    if category in human:
        return EXIT_HUMAN, _build_human_output(payload), ""

    if category in ai:
        envelope = parsed if "blocking_question" in parsed else {}
        return EXIT_AI_ROUTE, _build_ai_prompt(payload, envelope), ""

    return (
        EXIT_SCHEMA_VIOLATION,
        "",
        (
            f"[question_router] category='{category}' is in neither HUMAN_ENUM (13) "
            f"nor AI_ENUM (8). 質問せず自分で即決するか、適切なカテゴリへ修正してください。\n"
            f"  HUMAN_ENUM: {', '.join(human)}\n"
            f"  AI_ENUM:    {', '.join(ai)}"
        ),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="question_router",
        description="Route blocking_question JSON to Tom interrupt or management Claude.",
    )
    parser.add_argument(
        "--file",
        default=None,
        help="Read JSON from file (default: stdin).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    raw = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()

    exit_code, stdout, stderr = route(raw)
    if stdout:
        print(stdout)
    if stderr:
        print(stderr, file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
