# Question Router

Claude Code が出した `blocking_question` JSON をカテゴリで自動分類し、
人間判断（13 カテゴリ）はトム interrupt、AI 判断（8 カテゴリ）は管理クロード
向けプロンプトとして stdout に出すルーター。

Phase 3 Lane 3 で導入。実装本体は `scripts/question_router.py`。

---

## 前提条件（Pre-requisite）

`tool-template/.claude/hooks/question_classifier.sh` (Phase 2) は現在
**13 カテゴリ enum 外を exit 2 で BLOCK** する。本ルーターを Stop hook 連鎖の
後段に置いても、AI 判断カテゴリの質問は classifier 段階で止まり router まで
届かない。

恒久対応は **Lane 2 (detector-yaml-refactor)** で classifier の enum 取得元を
yaml 正本へ切り替える際に、AI 判断カテゴリも pass-through するよう拡張する。
それまでの暫定運用は次の通り:

```bash
# 例: クリップボードに blocking_question JSON が入っているとき
pbpaste | python3 ~/dev/origin-policy/scripts/question_router.py
echo $?  # 0 / 10 / 2
```

または手元 JSON ファイルを直接渡す:

```bash
python3 ~/dev/origin-policy/scripts/question_router.py --file my_question.json
```

---

## 入力フォーマット

stdin もしくは `--file` から JSON を受け取る。次の 2 形式に対応:

### 単体オブジェクト

```json
{
  "category": "data_destructive",
  "question": "本番 DB の users テーブルから email カラム削除しますが、進めますか",
  "proposed_default": "進める（バックアップ取得後）",
  "why_blocking": "破壊的変更でロールバック困難"
}
```

### wrapper 形式（report_package.schema.json#blocking_question 互換）

```json
{
  "parent_goal_id": "policy-gate-phase3",
  "related_guides": ["tier0-absolute-rules"],
  "blocking_question": {
    "category": "library_choice",
    "question": "yaml lib に PyYAML と ruamel.yaml のどちらを使いますか",
    "proposed_default": "PyYAML（既存依存）",
    "why_blocking": "依存追加判断"
  }
}
```

`parent_goal_id` / `related_guides` は AI 判断時の管理クロード向けプロンプトに
埋め込まれる（指定なしなら "unknown" / "なし"）。

---

## 終了コード

| exit | 意味 | stdout | stderr |
|------|------|--------|--------|
| **0** | category が **HUMAN_ENUM (13)**。トム interrupt が必要。 | `TOM_INTERRUPT_REQUIRED` マーカー（独立行）+ JSON pretty | — |
| **10** | category が **AI_ENUM (8)**。管理クロードへ自動ルーティング対象。 | 管理クロード向けプロンプト（テンプレートは `_build_ai_prompt`） | — |
| **2** | schema 違反。Claude Code に差し戻し。 | — | 違反理由（人間可読） |

非ゼロかつ 10 でも 2 でもない exit code が返ることはない。

---

## カテゴリ enum

### HUMAN_ENUM (13) — トム判断必須

正本: `rules/human_judgment_categories.yaml`

`parent_goal_change` / `business_priority` / `external_communication` /
`cost_commitment` / `ux_brand` / `privacy_security` / `permission_blocked` /
`data_destructive` / `security_iam` / `legal_compliance` /
`public_communication` / `budget_quota` / `hr_evaluation`

### AI_ENUM (8) — Claude Code が自分で決めるべき

正本: `scripts/question_router.py` 内の `AI_CATEGORIES` 定数。
将来 yaml 側に `ai_categories` セクションが追加された場合は yaml が優先される。

| id | 用途 |
|----|------|
| `implementation_detail` | 実装手段の選択（API 呼び出し方、データ構造の細部 など） |
| `library_choice` | 既存依存範囲内のライブラリ選定 |
| `refactor_pattern` | リファクタリング手法（既存挙動を変えない範囲） |
| `test_strategy` | テスト粒度・配置・ケース選定 |
| `naming` | 命名（変数 / 関数 / ファイル名） |
| `error_handling` | エラー処理方針（リトライ / フォールバック / log level） |
| `performance_tuning` | パフォーマンス調整（cache / index / algorithm） |
| `code_style` | コードスタイル / formatter / linter 設定 |

これら以外で 13 enum にも該当しない質問は exit 2（自分で即決すべき領域）。

---

## CLI 例

```bash
# 人間判断 → exit 0
echo '{"category":"parent_goal_change","question":"親ゴールを X に変更しますか"}' \
  | python3 scripts/question_router.py

# AI 判断 → exit 10
echo '{"category":"implementation_detail","question":"yq でパースしてもよいですか"}' \
  | python3 scripts/question_router.py

# schema 違反 → exit 2
echo '{"q":"自由文"}' | python3 scripts/question_router.py
```

---

## tool-template hook 配線（推奨）

`~/dev/tool-template/.claude/hooks/question_router_invoke.sh` に invoke
script が追加される。settings.json 自体の編集は本タスクの allowed_scope 外
のため、**Lane 2 で classifier を AI enum 対応に改修するタイミングで** 次の
ような Stop hook 連鎖を作ることを推奨:

```jsonc
"Stop": [
  { "hooks": [{ "type": "command", "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/stop-test-gate.sh" }] },
  { "hooks": [{ "type": "command", "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/policy_gate_stop.sh" }] },
  { "hooks": [{ "type": "command", "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/report_package_validator.sh" }] },
  { "hooks": [{ "type": "command", "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/question_classifier.sh" }] },
  { "hooks": [{ "type": "command", "command": "$CLAUDE_PROJECT_DIR/.claude/hooks/question_router_invoke.sh" }] }
]
```

invoke 側で exit 10 → exit 0 に変換しつつ stdout にプロンプトを出すので、
Stop hook chain は止まらず、Claude Code は管理クロード向けプロンプトを
そのまま読める。

---

## Phase 3 では out of scope

- 実 LLM API 呼び出しによる「管理クロードからの自動回答」は本タスクでは
  実装しない。プロンプト出力までで完了。後続タスクとして dev_backlog に起票
  予定。
- `question_classifier.sh` 自身の AI enum pass-through 改修は **Lane 2**
  で行う（detector-yaml-refactor の一環）。

---

## 関連

- `rules/human_judgment_categories.yaml` — 13 enum の正本
- `schemas/report_package.schema.json#blocking_question` — JSON 形状の正本
- `tool-template/.claude/hooks/question_classifier.sh` — Phase 2 の前段検出器
- `scripts/question_router.py` — 本ルーター実装
- `tests/test_question_router.py` — pytest 30 ケース
