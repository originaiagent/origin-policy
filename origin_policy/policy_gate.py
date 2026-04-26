"""Policy Gate v1 — Tier 0 R1〜R5 validator.

Usage (CLI):

    echo "Phase2a の指示を出せ" | python -m origin_policy.policy_gate check --type=management_output
    cat task_package.json | python -m origin_policy.policy_gate check --type=task_package
    cat report.json       | python -m origin_policy.policy_gate check --type=report_package

Programmatic API:

    from origin_policy.policy_gate import check
    result = check(text_or_dict, input_type)
    # result = {"status": "PASS"|"WARN"|"BLOCK", "findings": [...],
    #          "detected_rules": [...], "detected_patterns": [...]}

Exit codes:
    0 — PASS or WARN
    1 — BLOCK (at least one block-severity finding)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft7Validator

from origin_policy.classifier import classify

# --- Paths ---

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RULES_DIR = PROJECT_ROOT / "rules"
SCHEMAS_DIR = PROJECT_ROOT / "schemas"


# --- Lazy loaders (singletons) ---

_DETECTORS: dict | None = None
_TASK_SCHEMA: dict | None = None
_REPORT_SCHEMA: dict | None = None


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def get_detectors() -> dict:
    global _DETECTORS
    if _DETECTORS is None:
        _DETECTORS = _load_yaml(RULES_DIR / "tier0_detectors.yaml")
    return _DETECTORS


def get_task_schema() -> dict:
    global _TASK_SCHEMA
    if _TASK_SCHEMA is None:
        _TASK_SCHEMA = _load_json(SCHEMAS_DIR / "task_package.schema.json")
    return _TASK_SCHEMA


def get_report_schema() -> dict:
    global _REPORT_SCHEMA
    if _REPORT_SCHEMA is None:
        _REPORT_SCHEMA = _load_json(SCHEMAS_DIR / "report_package.schema.json")
    return _REPORT_SCHEMA


# --- Body / Reference splitting (R3 exception handling) ---

# Lines that mark the start of the 末尾「参照」 section.
_REFERENCE_HEADER_RE = re.compile(r"^\s*#{0,6}\s*参照\b")


def split_body_and_reference(text: str) -> tuple[str, str]:
    """Split text into (body, reference) at the first "参照" header.

    Reference section is anything after a line matching:
      - '参照' (alone)
      - '## 参照', '### 参照' (any heading level)
      - '---' followed by '参照' on the next line

    Reference contents are exempted from R3 ID checks.
    """
    lines = text.split("\n")
    ref_start: int | None = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if _REFERENCE_HEADER_RE.match(line):
            ref_start = i
            break
        if stripped == "---" and i + 1 < len(lines):
            if _REFERENCE_HEADER_RE.match(lines[i + 1]):
                ref_start = i
                break

    if ref_start is None:
        return text, ""

    body = "\n".join(lines[:ref_start])
    reference = "\n".join(lines[ref_start:])
    return body, reference


# --- Excluded ranges (code blocks, URLs, file paths) for R3 ---

_TRIPLE_BACKTICK_RE = re.compile(r"```[\s\S]*?```")
_INLINE_BACKTICK_RE = re.compile(r"`[^`\n]+`")
_URL_RE = re.compile(r"(?:https?|file|ftp)://\S+")
# Heuristic file paths: contain '/' and a .ext, OR start with '/' or './' or '../'
_FILE_PATH_RE = re.compile(
    r"(?:\.{0,2}/[\w\-./]+\.[A-Za-z0-9]{1,8})"
    r"|(?:[\w\-]+/[\w\-./]+\.[A-Za-z0-9]{1,8})"
    r"|(?:/[\w\-./]+/[\w\-]+)"
)


def _excluded_ranges(text: str) -> list[tuple[int, int]]:
    """Compute character ranges that should be exempted from R3 detection."""
    ranges: list[tuple[int, int]] = []

    for m in _TRIPLE_BACKTICK_RE.finditer(text):
        ranges.append((m.start(), m.end()))
    for m in _INLINE_BACKTICK_RE.finditer(text):
        if not _is_inside(m.start(), ranges):
            ranges.append((m.start(), m.end()))
    for m in _URL_RE.finditer(text):
        ranges.append((m.start(), m.end()))
    for m in _FILE_PATH_RE.finditer(text):
        ranges.append((m.start(), m.end()))

    return ranges


def _is_inside(pos: int, ranges: list[tuple[int, int]]) -> bool:
    return any(s <= pos < e for s, e in ranges)


def _is_match_excluded(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
    return any(s <= start and end <= e for s, e in ranges)


# --- Checkers ---


def check_r3(text: str) -> list[dict]:
    """R3 — internal IDs (Phase ID, UUID, task_id labels) must not appear in body.

    Exempt: 末尾「参照」 section, code blocks, URLs, file paths.
    """
    findings: list[dict] = []
    body, _ref = split_body_and_reference(text)
    excluded = _excluded_ranges(body)

    detectors = get_detectors()
    spec = detectors.get("r3_internal_id_in_body", {})
    for pattern in spec.get("patterns", []):
        regex = re.compile(pattern["regex"], re.UNICODE)
        for m in regex.finditer(body):
            if _is_match_excluded(m.start(), m.end(), excluded):
                continue
            findings.append(
                {
                    "rule": "R3",
                    "pattern_id": pattern["id"],
                    "severity": pattern.get("severity", "block"),
                    "message": pattern.get("message", ""),
                    "match": m.group(),
                    "position": m.start(),
                }
            )
    return findings


def _extract_sentence(text: str, pos: int) -> str:
    """Return the sentence (split by 。！？!?\\n) containing position pos."""
    boundary = "。！？!?\n"
    start = pos
    while start > 0 and text[start - 1] not in boundary:
        start -= 1
    end = pos
    while end < len(text) and text[end] not in boundary:
        end += 1
    return text[start:end].strip()


def check_r1(text: str) -> list[dict]:
    """R1 — questions / choice offers / confirmation requests must classify into
    one of the 13 human judgment categories. Otherwise BLOCK (it's AI 即決領域)."""
    findings: list[dict] = []
    detectors = get_detectors()
    spec = detectors.get("r1_question_detection", {})
    classification_msg = (
        spec.get("classification", {})
        .get("on_fail_message", "Question is not classifiable to any human judgment category")
        .strip()
    )

    seen_sentence_positions: set[int] = set()

    for trigger in spec.get("trigger_patterns", []):
        ttype = trigger.get("type", "unknown")
        regex = re.compile(trigger["regex"], re.UNICODE)
        explicit_severity = trigger.get("severity")
        explicit_message = trigger.get("message", "")

        for m in regex.finditer(text):
            if ttype == "forbidden_phrase":
                findings.append(
                    {
                        "rule": "R1",
                        "pattern_id": "forbidden_phrase",
                        "severity": explicit_severity or "block",
                        "message": explicit_message,
                        "match": m.group(),
                        "position": m.start(),
                    }
                )
            elif ttype == "temptation_word":
                findings.append(
                    {
                        "rule": "R1",
                        "pattern_id": "temptation_word",
                        "severity": explicit_severity or "warn",
                        "message": explicit_message,
                        "match": m.group(),
                        "position": m.start(),
                    }
                )
            else:
                # explicit_question / choice_offer / confirmation_request → classify
                sentence = _extract_sentence(text, m.start())
                # Dedupe on the sentence's start position to avoid double-flagging
                # a sentence that triggered multiple patterns.
                sentence_start = m.start()
                while sentence_start > 0 and text[sentence_start - 1] not in "。！？!?\n":
                    sentence_start -= 1
                if sentence_start in seen_sentence_positions:
                    continue
                seen_sentence_positions.add(sentence_start)

                category = classify(sentence)
                if category is None:
                    findings.append(
                        {
                            "rule": "R1",
                            "pattern_id": "unclassifiable_question",
                            "severity": "block",
                            "message": classification_msg,
                            "match": sentence,
                            "trigger_type": ttype,
                            "position": m.start(),
                        }
                    )
                # If classified, we do NOT block — asking a human-judgment
                # question is allowed (and this gate is only Tier 0).
    return findings


def _schema_findings(rule: str, instance: Any, schema: dict) -> list[dict]:
    """Return findings for every jsonschema validation error."""
    out: list[dict] = []
    validator = Draft7Validator(schema)
    for err in validator.iter_errors(instance):
        out.append(
            {
                "rule": rule,
                "pattern_id": "schema_violation",
                "severity": "block",
                "message": f"Schema violation: {err.message}",
                "path": [str(p) for p in err.absolute_path],
            }
        )
    return out


def check_r4(report_data: Any) -> list[dict]:
    """R4 — completion report must conform to report_package schema and contain
    real evidence. Forbidden patterns ('✅ 完了' alone, '画面表示 OK' self-reports)
    block when raw text is given.
    """
    findings: list[dict] = []
    detectors = get_detectors()
    spec = detectors.get("r4_report_package_schema", {})

    if isinstance(report_data, str):
        for fp in spec.get("forbidden_patterns", []):
            regex = re.compile(fp["regex"], re.UNICODE)
            for m in regex.finditer(report_data):
                findings.append(
                    {
                        "rule": "R4",
                        "pattern_id": "forbidden_text",
                        "severity": fp.get("severity", "block"),
                        "message": fp.get("message", ""),
                        "match": m.group(),
                    }
                )
        return findings

    # JSON / dict path
    findings.extend(_schema_findings("R4", report_data, get_report_schema()))

    # Belt-and-braces: explicit evidence_urls check (clearer error message).
    evidence = report_data.get("evidence_urls") if isinstance(report_data, dict) else None
    if not evidence:
        findings.append(
            {
                "rule": "R4",
                "pattern_id": "no_evidence",
                "severity": "block",
                "message": "evidence_urls が空または欠落。最低 1 個の証拠 URL（PR / commit / dashboard / log 等）が必要。",
            }
        )

    return findings


def check_r5(task_data: Any) -> list[dict]:
    """R5 — task_package schema check. For raw text, flag natural-language indicators
    that suggest the instruction was not schema-ized."""
    findings: list[dict] = []
    detectors = get_detectors()
    spec = detectors.get("r5_task_package_schema", {})

    if isinstance(task_data, str):
        severity = spec.get("fail_action", "warn")
        message = spec.get("message", "Task instruction may not conform to task_package schema.")
        for indicator in spec.get("natural_language_indicators", []):
            if indicator in task_data:
                findings.append(
                    {
                        "rule": "R5",
                        "pattern_id": "natural_language_instruction",
                        "severity": severity,
                        "message": message,
                        "match": indicator,
                    }
                )
        return findings

    # JSON / dict path
    findings.extend(_schema_findings("R5", task_data, get_task_schema()))
    return findings


# --- Public API ---

VALID_INPUT_TYPES = {
    "management_output",
    "task_package",
    "report_package",
    "completion_report_text",
}


def check(input_data: Any, input_type: str) -> dict:
    """Apply Tier 0 detectors based on ``input_type``.

    - management_output (text): R3 + R1 + R5 (natural-language indicators)
    - task_package (dict/JSON): R5 schema validation
    - report_package (dict/JSON): R4 schema validation + evidence check
    - completion_report_text (text): R4 forbidden-pattern check

    Returns a dict with status (PASS/WARN/BLOCK), findings list, and aggregated
    detected_rules / detected_patterns sets.
    """
    if input_type not in VALID_INPUT_TYPES:
        raise ValueError(
            f"Unknown input_type: {input_type!r}. Valid: {sorted(VALID_INPUT_TYPES)}"
        )

    findings: list[dict] = []

    if input_type == "management_output":
        findings.extend(check_r3(input_data))
        findings.extend(check_r1(input_data))
        findings.extend(check_r5(input_data))
    elif input_type == "task_package":
        findings.extend(check_r5(input_data))
    elif input_type == "report_package":
        findings.extend(check_r4(input_data))
    elif input_type == "completion_report_text":
        findings.extend(check_r4(input_data))

    has_block = any(f.get("severity") == "block" for f in findings)
    has_warn = any(f.get("severity") == "warn" for f in findings)

    if has_block:
        status = "BLOCK"
    elif has_warn:
        status = "WARN"
    else:
        status = "PASS"

    detected_rules = sorted({f["rule"] for f in findings})
    detected_patterns = sorted({f["pattern_id"] for f in findings})

    return {
        "status": status,
        "findings": findings,
        "detected_rules": detected_rules,
        "detected_patterns": detected_patterns,
    }


# --- CLI ---


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="policy_gate",
        description="Policy Gate v1 — Tier 0 R1〜R5 validator (origin-policy).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    cp = sub.add_parser("check", help="Validate input against Tier 0 detectors")
    cp.add_argument(
        "--type",
        required=True,
        dest="input_type",
        choices=sorted(VALID_INPUT_TYPES),
        help="Input type — selects which detectors to apply.",
    )
    cp.add_argument(
        "--file",
        default=None,
        help="Read input from file (default: stdin).",
    )
    cp.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress JSON output; rely on exit code only.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.file:
        content = Path(args.file).read_text(encoding="utf-8")
    else:
        content = sys.stdin.read()

    if args.input_type in ("task_package", "report_package"):
        try:
            input_data: Any = json.loads(content) if content.strip() else {}
        except json.JSONDecodeError as e:
            print(
                json.dumps(
                    {
                        "status": "BLOCK",
                        "findings": [
                            {
                                "rule": args.input_type.upper(),
                                "pattern_id": "invalid_json",
                                "severity": "block",
                                "message": f"Input is not valid JSON: {e}",
                            }
                        ],
                        "detected_rules": [args.input_type.upper()],
                        "detected_patterns": ["invalid_json"],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                file=sys.stderr,
            )
            return 1
    else:
        input_data = content

    result = check(input_data, args.input_type)

    if not args.quiet:
        print(json.dumps(result, ensure_ascii=False, indent=2))

    return 1 if result["status"] == "BLOCK" else 0


if __name__ == "__main__":
    sys.exit(main())
