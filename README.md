# origin-policy

**Policy Gate v1** — Tier 0 absolute rules validator (R1–R5) for AI 出力の機械検査基盤。

自然文ルールを「読ませる」運用から、出力を「機械検査する」運用へ移行するための土台。

## 設計思想

- **Tier 0** = 5 個固定の絶対ルール（このリポでブロック）
- **Tier 1** = 運用ルール（違反時警告、別系統）
- **Tier 2** = 参考情報（知識ベース、別系統）

詳細は origin-core DB の guides テーブル `slug = tier0-absolute-rules` を参照。

## Tier 0 ルール

| ID | 概要 | 実装場所 |
|----|------|----------|
| **R1** | 質問・選択肢・確認依頼は人間判断 13 カテゴリのいずれかに分類できなければ BLOCK | `check_r1` |
| **R2** | 親ゴール外作業の検出（warn） | 別レーンで実装予定 |
| **R3** | 内部 ID（Phase ID / UUID / task_id ラベル）を本文に出さない | `check_r3` |
| **R4** | 完了報告は schema 準拠かつ証拠 URL 必須 | `check_r4` |
| **R5** | Claude Code への指示は task_package schema に準拠 | `check_r5` |

## ディレクトリ構成

```
origin-policy/
├── README.md
├── pyproject.toml
├── origin_policy/                    # importable package
│   ├── __init__.py
│   ├── policy_gate.py                # CLI + check() API
│   ├── check_management_output.py    # 管理クロード出力の手動 wrapper（CLI）
│   └── classifier.py                 # 13 カテゴリ分類器
├── rules/
│   ├── human_judgment_categories.yaml   # 13 カテゴリ定義（管理クロード確定済）
│   └── tier0_detectors.yaml             # R1-R5 検出器設定（管理クロード確定済）
├── schemas/
│   ├── task_package.schema.json         # 管理クロード → Claude Code 指示書 schema
│   └── report_package.schema.json       # Claude Code → 管理クロード 完了報告 schema
├── scripts/                          # CLI ラッパー
│   ├── policy_gate.py
│   ├── classifier.py
│   ├── check_management_output.py    # 管理クロード出力 wrapper の thin shim
│   └── macos_service/                # Quick Action（右クリック→検査→通知）
│       ├── PolicyGateCheck.workflow/
│       ├── install.sh
│       ├── uninstall.sh
│       └── linux_fallback.sh         # xclip + notify-send 版
├── eval/
│   └── violations/                   # 違反テストケース（YAML）
│       ├── r1_question_no_category.yaml
│       ├── r3_phase_id_in_body.yaml
│       ├── r3_uuid_in_body.yaml
│       ├── r4_no_evidence.yaml
│       ├── r4_emoji_only_completion.yaml
│       └── r5_freeform_instruction.yaml
├── tests/
│   └── test_policy_gate.py
└── .github/workflows/test.yml        # CI
```

## インストール

```bash
pip install -e ".[dev]"
```

依存: `pyyaml >= 6.0`, `jsonschema >= 4.0`（dev: `pytest >= 7.0`）。

## 使い方

### CLI

```bash
# テキスト（管理クロードの出力等）の検査
echo "Phase2a 前段の指示書を出せ" | python -m origin_policy.policy_gate check --type=management_output
# → exit 1, R3 violation: phase_id

# task_package JSON の schema 検査
cat task_package.json | python -m origin_policy.policy_gate check --type=task_package
# → exit 0 if schema valid, exit 1 if violation

# 完了報告 JSON の検査（証拠なしなら BLOCK）
cat report.json | python -m origin_policy.policy_gate check --type=report_package
# → exit 1 if evidence_urls is empty

# 完了報告のテキスト形式（"✅ 完了" 系を検出）
echo "PR merged. ✅ 完了" | python -m origin_policy.policy_gate check --type=completion_report_text
# → exit 1, R4 violation: forbidden_text
```

### 管理クロード出力の手動検査（推奨フロー）

`Claude.ai` web UI の出力は自動フックできないため、コピペで検査する CLI を別途用意:

```bash
pbpaste | python -m origin_policy.check_management_output
echo "テキスト" | python -m origin_policy.check_management_output
python -m origin_policy.check_management_output --file path/to/text.md
python -m origin_policy.check_management_output --json < text.md   # raw JSON
```

`policy_gate check --type=management_output` の薄い wrapper で、出力は人間可読の
`[Policy Gate] BLOCK — N violation(s)` 形式（exit 1 が BLOCK）。
macOS では `scripts/macos_service/install.sh` で右クリックメニューに
"Policy Gate で検査" を登録できる（通知センターで結果表示）。

入力タイプ:

| `--type` 値 | 入力 | 適用ルール |
|-------------|------|------------|
| `management_output` | テキスト | R3, R1, R5 (natural language indicators) |
| `task_package` | JSON | R5 schema 検査 |
| `report_package` | JSON | R4 schema 検査 + evidence_urls チェック |
| `completion_report_text` | テキスト | R4 forbidden patterns |

終了コード: BLOCK のとき `1`、PASS / WARN のとき `0`。

### プログラマティック API

```python
from origin_policy.policy_gate import check

result = check("Phase2a の指示", "management_output")
# result = {
#   "status": "BLOCK",
#   "findings": [{"rule": "R3", "pattern_id": "phase_id", ...}],
#   "detected_rules": ["R3"],
#   "detected_patterns": ["phase_id"]
# }
```

`status` の値:
- `PASS` — 検出なし
- `WARN` — warn-severity の検出のみ（exit 0）
- `BLOCK` — block-severity の検出が 1 件以上（exit 1）

## スキーマ

### `schemas/task_package.schema.json`

管理クロード → Claude Code への指示書フォーマット（JSON Schema Draft-07）。
必須フィールド: `schema_version`, `parent_goal_id`, `tool_name`, `title`,
`done_conditions`, `allowed_scope`, `judgment_authority`, `report_schema_ref`,
`start_trigger`。詳細は schema ファイル参照。

### `schemas/report_package.schema.json`

Claude Code → 管理クロード への完了報告フォーマット。
必須: `schema_version`, `task_package_id`, `status`, `evidence_urls` (minItems: 1),
`tests_run`, `ci_status`, `self_check`。

### `rules/human_judgment_categories.yaml`

R1 検査で使う **13 個の人間判断カテゴリ** enum:
`parent_goal_change`, `business_priority`, `external_communication`,
`cost_commitment`, `ux_brand`, `privacy_security`, `permission_blocked`,
`data_destructive`, `security_iam`, `legal_compliance`, `public_communication`,
`budget_quota`, `hr_evaluation`。

質問がこのいずれにも分類できなければ AI 即決すべき領域 → BLOCK。

### `rules/tier0_detectors.yaml`

R1〜R5 の regex / classifier 設定本体。

## テスト

```bash
pytest -v
```

`eval/violations/*.yaml` は自動的に discover されパラメトライズドテストとして実行される。

新しい違反パターンを追加するには、以下フォーマットで YAML を 1 ファイル追加するだけ:

```yaml
id: rN_short_descriptor_001
rule: R3
input_type: management_output      # or task_package / report_package / completion_report_text
description: |
  人間が読む説明
input: |
  検査対象テキスト（または YAML map で JSON 相当を埋め込む）
expected:
  status: BLOCK                    # PASS / WARN / BLOCK
  detected_rules: [R3]
  detected_patterns: [phase_id]    # 任意。指定すると検証がより厳密に
```

## 拡張ポイント

- **classifier の精度向上**: 現状 v1 は keyword/regex ベース。後段で LLM 分類器に差し替え予定（インターフェース `classify(text) -> category | None` は維持）。
- **R2 (親ゴール外作業検出)**: 本リポ単体では実装せず、dev_backlog DB との突き合わせが要るため別レーンで実装予定。
- **schema バージョニング**: schema 変更時は `schema_version` を bump し、旧版との互換性レイヤーを別 module で持たせる方針（現状 v1.0 のみ）。

## ライセンス

社内利用（origin プロジェクト）。
