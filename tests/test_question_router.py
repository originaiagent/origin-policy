"""Pytest suite for scripts/question_router.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ROUTER = PROJECT_ROOT / "scripts" / "question_router.py"

sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import question_router  # noqa: E402

EXIT_HUMAN = question_router.EXIT_HUMAN
EXIT_AI = question_router.EXIT_AI_ROUTE
EXIT_VIOL = question_router.EXIT_SCHEMA_VIOLATION
TOM_MARKER = question_router.TOM_INTERRUPT_MARKER


def _run_cli(payload: str) -> tuple[int, str, str]:
    res = subprocess.run(
        [sys.executable, str(ROUTER)],
        input=payload,
        text=True,
        capture_output=True,
        check=False,
    )
    return res.returncode, res.stdout, res.stderr


# ---- 必須 3 ケース（required_checks） -----------------------------------


def test_human_judgment_exit0() -> None:
    payload = json.dumps(
        {"category": "parent_goal_change", "question": "親ゴールを X に変更しますか"},
        ensure_ascii=False,
    )
    code, out, err = _run_cli(payload)
    assert code == EXIT_HUMAN, (code, out, err)
    assert TOM_MARKER in out
    assert "parent_goal_change" in out


def test_ai_judgment_exit10() -> None:
    payload = json.dumps(
        {"category": "implementation_detail", "question": "yq でパースしてもよいですか"},
        ensure_ascii=False,
    )
    code, out, err = _run_cli(payload)
    assert code == EXIT_AI, (code, out, err)
    assert "implementation_detail" in out
    assert "yq でパースしてもよいですか" in out
    assert "管理クロード" not in err


def test_schema_violation_missing_category() -> None:
    payload = json.dumps({"q": "自由文"}, ensure_ascii=False)
    code, out, err = _run_cli(payload)
    assert code == EXIT_VIOL, (code, out, err)
    assert "category" in err or "blocking_question" in err


# ---- 追加カバレッジ ----------------------------------------------------


def test_blocking_question_wrapper_form() -> None:
    payload = json.dumps(
        {
            "blocking_question": {
                "category": "data_destructive",
                "question": "本番 DB の users テーブルから email カラム削除しますが、進めますか",
                "proposed_default": "進める（バックアップ取得後）",
                "why_blocking": "破壊的変更でロールバック困難",
            }
        },
        ensure_ascii=False,
    )
    code, out, err = _run_cli(payload)
    assert code == EXIT_HUMAN, (code, out, err)
    assert TOM_MARKER in out
    assert "data_destructive" in out


def test_unknown_category_violation() -> None:
    payload = json.dumps(
        {"category": "yolo_mode", "question": "ノリで聞いていいですか"},
        ensure_ascii=False,
    )
    code, _, err = _run_cli(payload)
    assert code == EXIT_VIOL
    assert "yolo_mode" in err


def test_invalid_json_violation() -> None:
    code, _, err = _run_cli("これは JSON ではない")
    assert code == EXIT_VIOL
    assert "invalid JSON" in err or "JSON" in err


def test_empty_input_violation() -> None:
    code, _, err = _run_cli("")
    assert code == EXIT_VIOL
    assert "empty" in err.lower() or "json" in err.lower()


def test_missing_question_violation() -> None:
    payload = json.dumps({"category": "naming"}, ensure_ascii=False)
    code, _, err = _run_cli(payload)
    assert code == EXIT_VIOL
    assert "question" in err


# ---- 関数 API レベルの直接テスト（CLI 呼び出しなし） -----------------


@pytest.mark.parametrize(
    "category",
    [
        "parent_goal_change",
        "business_priority",
        "external_communication",
        "cost_commitment",
        "ux_brand",
        "privacy_security",
        "permission_blocked",
        "data_destructive",
        "security_iam",
        "legal_compliance",
        "public_communication",
        "budget_quota",
        "hr_evaluation",
    ],
)
def test_all_13_human_categories_route_to_human(category: str) -> None:
    code, out, err = question_router.route(
        json.dumps({"category": category, "question": "test"})
    )
    assert code == EXIT_HUMAN, (code, err)
    assert TOM_MARKER in out


@pytest.mark.parametrize("category", question_router.AI_CATEGORIES)
def test_all_8_ai_categories_route_to_ai(category: str) -> None:
    code, out, err = question_router.route(
        json.dumps({"category": category, "question": "test"})
    )
    assert code == EXIT_AI, (code, err)
    assert category in out


def test_envelope_parent_goal_id_is_included_in_prompt() -> None:
    payload = {
        "parent_goal_id": "policy-gate-phase3",
        "related_guides": ["tier0-absolute-rules", "mgmt-bakuso-nonstop-mode"],
        "blocking_question": {
            "category": "library_choice",
            "question": "yaml lib に PyYAML と ruamel.yaml のどちらを使いますか",
        },
    }
    code, out, _ = question_router.route(json.dumps(payload, ensure_ascii=False))
    assert code == EXIT_AI
    assert "policy-gate-phase3" in out
    assert "tier0-absolute-rules" in out
