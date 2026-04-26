"""Pytest suite for Policy Gate v1.

Auto-discovers all YAML files in ``eval/violations/`` and asserts each is detected
as the expected rule violation.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

# Allow running pytest from repo root without installing the package.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from origin_policy.policy_gate import check  # noqa: E402

VIOLATIONS_DIR = PROJECT_ROOT / "eval" / "violations"


def _load_violation_cases() -> list[dict]:
    cases: list[dict] = []
    for path in sorted(VIOLATIONS_DIR.glob("*.yaml")):
        case = yaml.safe_load(path.read_text(encoding="utf-8"))
        case["_path"] = str(path)
        cases.append(case)
    return cases


VIOLATION_CASES = _load_violation_cases()


def test_violation_cases_loaded() -> None:
    """Sanity: at least 5 violation cases exist (Done condition #4)."""
    assert len(VIOLATION_CASES) >= 5, (
        f"Expected at least 5 violation cases under {VIOLATIONS_DIR}, "
        f"found {len(VIOLATION_CASES)}"
    )


@pytest.mark.parametrize(
    "case",
    VIOLATION_CASES,
    ids=[c["id"] for c in VIOLATION_CASES],
)
def test_violation_detected(case: dict) -> None:
    """Each violation YAML in eval/violations/ must be detected as expected."""
    result = check(case["input"], case["input_type"])
    expected = case["expected"]

    assert result["status"] == expected["status"], (
        f"{case['id']}: expected status={expected['status']}, "
        f"got status={result['status']}\nfindings={result['findings']}"
    )

    expected_rules = set(expected.get("detected_rules", []))
    actual_rules = set(result["detected_rules"])
    assert expected_rules.issubset(actual_rules), (
        f"{case['id']}: expected rules {expected_rules} not subset of "
        f"actual {actual_rules}\nfindings={result['findings']}"
    )

    if "detected_patterns" in expected:
        expected_patterns = set(expected["detected_patterns"])
        actual_patterns = set(result["detected_patterns"])
        assert expected_patterns.issubset(actual_patterns), (
            f"{case['id']}: expected patterns {expected_patterns} not subset of "
            f"actual {actual_patterns}\nfindings={result['findings']}"
        )


# --- Hand-written sanity tests ---


def test_clean_text_passes() -> None:
    """Plain text with no triggers should PASS."""
    text = "今日は天気が良いですね。実装を進めます。"
    result = check(text, "management_output")
    assert result["status"] == "PASS", result


def test_phase_id_in_reference_section_is_allowed() -> None:
    """Phase ID inside the trailing 「参照」 section must NOT trigger R3."""
    text = (
        "今回の作業内容は、新規 API の追加です。\n"
        "テストも書きます。\n"
        "\n"
        "## 参照\n"
        "- Phase2a 設計メモ\n"
        "- task_id Phase1b の続き\n"
    )
    result = check(text, "management_output")
    # Body has no Phase ID, so R3 should not flag.
    assert "R3" not in result["detected_rules"], result


def test_uuid_in_url_is_allowed() -> None:
    """UUID inside a URL should be exempted from R3."""
    text = (
        "PR を merge しました。\n"
        "https://example.com/items/12345678-1234-5678-9abc-def012345678\n"
    )
    result = check(text, "management_output")
    assert "R3" not in result["detected_rules"], result


def test_classifiable_question_does_not_block() -> None:
    """A question that maps to a human-judgment category should not BLOCK on R1."""
    text = "親ゴールを変更しますか、どっちが優先ですか"
    result = check(text, "management_output")
    # We do not block: the question is classifiable (parent_goal_change / business_priority).
    assert result["status"] != "BLOCK", result


def test_forbidden_phrase_blocks() -> None:
    """R1 forbidden_phrase pattern must BLOCK regardless of classification."""
    text = "即決すべきなら判断ください"
    result = check(text, "management_output")
    assert result["status"] == "BLOCK", result
    assert "R1" in result["detected_rules"], result


def test_valid_report_package_passes() -> None:
    """A well-formed report_package dict should PASS."""
    report = {
        "schema_version": "1.0",
        "task_package_id": "lane1-001",
        "status": "done",
        "summary": "Policy Gate v1 を実装しました",
        "evidence_urls": [
            {
                "type": "pr",
                "url": "https://github.com/originaiagent/origin-policy/pull/1",
                "description": "initial implementation",
            }
        ],
        "tests_run": [{"name": "pytest", "method": "pytest", "result": "pass"}],
        "ci_status": {
            "status": "green",
            "verified_at_source": "https://github.com/originaiagent/origin-policy/actions",
        },
        "self_check": {
            "build": "pass",
            "ui": "n/a",
            "feature": "pass",
            "regression": "pass",
            "errors": "pass",
        },
    }
    result = check(report, "report_package")
    assert result["status"] == "PASS", result


def test_invalid_task_package_blocks() -> None:
    """A task_package missing required fields must BLOCK on R5 schema_violation."""
    bad_task = {"schema_version": "1.0"}  # missing nearly all required fields
    result = check(bad_task, "task_package")
    assert result["status"] == "BLOCK", result
    assert "R5" in result["detected_rules"], result
    assert "schema_violation" in result["detected_patterns"], result
