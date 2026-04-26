"""Tests for the management_output CLI wrapper.

Covers the 3 historical 管理クロード violation samples from the lane 3 spec.
すべて BLOCK で、違反箇所が提示されることを確認する。
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout

import pytest

from origin_policy.check_management_output import main as wrapper_main
from origin_policy.policy_gate import check


# Samples copied verbatim from
# instructions/lane3_management_output_validator.md (テスト用入力).
SAMPLE_R3 = "次のターンでトムが指示するのは「Phase2a 前段の指示書を出せ」か「別ゴール」か。"
SAMPLE_R1 = "(A) 昇格する / (B) このまま future 維持 トム判断仰がず即決すべき内容なら言って。"
SAMPLE_COMBINED = "Phase2a前段(366508de)future/low / 念のため確認したいのですが..."


def _run_wrapper(text: str, *, as_json: bool = True) -> tuple[int, str]:
    """Drive the CLI wrapper end-to-end with `text` on stdin and return (exit_code, stdout)."""
    buf = io.StringIO()
    saved_stdin = sys.stdin
    sys.stdin = io.StringIO(text)
    try:
        with redirect_stdout(buf):
            argv = ["--json"] if as_json else []
            code = wrapper_main(argv)
    finally:
        sys.stdin = saved_stdin
    return code, buf.getvalue()


# --- Programmatic API contract (uses policy_gate.check directly) ---


def test_sample_r3_blocks_with_phase_id():
    """Sample 1: 「Phase2a」を含む本文 → R3 BLOCK."""
    result = check(SAMPLE_R3, "management_output")

    assert result["status"] == "BLOCK"
    assert "R3" in result["detected_rules"]
    pattern_ids = {f["pattern_id"] for f in result["findings"]}
    assert "phase_id" in pattern_ids

    phase_id_finding = next(
        f for f in result["findings"] if f.get("pattern_id") == "phase_id"
    )
    assert phase_id_finding["severity"] == "block"
    assert phase_id_finding["match"].startswith("Phase2a")
    # 違反箇所（位置）が提示されていること
    assert "position" in phase_id_finding


def test_sample_r1_blocks_with_choice_and_forbidden_phrase():
    """Sample 2: 選択肢 (A)/(B) + 「トム判断仰がず」/「即決すべきなら」 → R1 BLOCK."""
    result = check(SAMPLE_R1, "management_output")

    assert result["status"] == "BLOCK"
    assert "R1" in result["detected_rules"]

    block_findings = [f for f in result["findings"] if f.get("severity") == "block"]
    assert block_findings, "expected at least one block finding"

    pattern_ids = {f["pattern_id"] for f in block_findings}
    # Either an unclassifiable choice question, or the forbidden_phrase trigger
    # (or both) should fire — both are valid block sources for this sample.
    assert pattern_ids & {"unclassifiable_question", "forbidden_phrase"}, (
        f"expected unclassifiable_question or forbidden_phrase, got {pattern_ids}"
    )


def test_sample_combined_blocks_with_phase_id_and_warns_on_temptation():
    """Sample 3: Phase ID + 短縮 UUID + 「念のため」 → R3 BLOCK + R1 WARN."""
    result = check(SAMPLE_COMBINED, "management_output")

    assert result["status"] == "BLOCK"

    pattern_ids = {f["pattern_id"] for f in result["findings"]}
    severities = {f["pattern_id"]: f["severity"] for f in result["findings"]}

    # R3: Phase ID は block
    assert "phase_id" in pattern_ids
    assert severities["phase_id"] == "block"

    # R3: 短縮 UUID は warn (8桁 hex)
    assert "short_uuid" in pattern_ids
    assert severities["short_uuid"] == "warn"

    # R1: temptation_word 「念のため」は warn
    assert "temptation_word" in pattern_ids
    assert severities["temptation_word"] == "warn"


# --- CLI wrapper exit codes & output contract ---


@pytest.mark.parametrize(
    "sample",
    [SAMPLE_R3, SAMPLE_R1, SAMPLE_COMBINED],
    ids=["sample_r3", "sample_r1", "sample_combined"],
)
def test_wrapper_exits_with_code_1_on_block(sample: str):
    """すべての違反サンプルで exit code 1 が返ること."""
    exit_code, _ = _run_wrapper(sample, as_json=True)
    assert exit_code == 1


@pytest.mark.parametrize(
    "sample",
    [SAMPLE_R3, SAMPLE_R1, SAMPLE_COMBINED],
    ids=["sample_r3", "sample_r1", "sample_combined"],
)
def test_wrapper_json_output_status_is_block(sample: str):
    """--json 出力で status=BLOCK がパースできること."""
    _, out = _run_wrapper(sample, as_json=True)
    parsed = json.loads(out)
    assert parsed["status"] == "BLOCK"
    assert parsed["findings"], "findings should be non-empty"


def test_wrapper_human_output_includes_block_marker_and_position():
    """人間可読モードで `[Policy Gate] BLOCK` と違反箇所/メッセージが出力されること."""
    _, out = _run_wrapper(SAMPLE_R3, as_json=False)
    assert "[Policy Gate] BLOCK" in out
    # 違反箇所のテキスト
    assert "Phase2a" in out
    # メッセージ
    assert "末尾「参照」欄" in out


def test_wrapper_pass_on_clean_input():
    """違反のないテキストは exit 0 / PASS で返ること."""
    clean = "次の作業として実装を進めます。テストも書きます。"
    exit_code, out = _run_wrapper(clean, as_json=True)
    assert exit_code == 0
    parsed = json.loads(out)
    assert parsed["status"] == "PASS"


def test_wrapper_normalizes_crlf():
    """改行コード違い (\\r\\n) でも検出ロジックが動くこと."""
    text_crlf = SAMPLE_R3.replace("。", "\r\n")
    exit_code, out = _run_wrapper(text_crlf, as_json=True)
    assert exit_code == 1
    parsed = json.loads(out)
    assert parsed["status"] == "BLOCK"


def test_wrapper_reads_from_file(tmp_path):
    """--file オプションでファイル入力できること."""
    p = tmp_path / "sample.md"
    p.write_text(SAMPLE_R3, encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = wrapper_main(["--file", str(p), "--json"])
    assert code == 1
    assert json.loads(buf.getvalue())["status"] == "BLOCK"


def test_phase_id_in_reference_section_does_not_trigger_r3():
    """Phase ID が末尾「参照」欄にあれば R3 は発火しないこと（既存契約の確認）."""
    text = "実装方針を決めます。\n\n## 参照\n- Phase2a (366508de)"
    result = check(text, "management_output")
    pattern_ids = {f["pattern_id"] for f in result["findings"]}
    assert "phase_id" not in pattern_ids
