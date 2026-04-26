# origin-policy

**Policy Gate v1** — Tier 0 absolute rules validator (R1–R5)。

このコミットは管理クロード確定済のスキーマ・ルール定義のみを含む genesis bootstrap。
validator 実装は #1 PR (`claude/policy-gate-v1`) で land 予定。

## 含まれる pre-confirmed assets

- `rules/human_judgment_categories.yaml` — 人間判断 13 カテゴリ enum
- `rules/tier0_detectors.yaml` — R1〜R5 検出器設定
- `schemas/task_package.schema.json` — 管理クロード → Claude Code 指示書 schema
- `schemas/report_package.schema.json` — Claude Code → 管理クロード 完了報告 schema

詳細は [tier0-absolute-rules](.) ガイド（origin-core DB）を参照。
