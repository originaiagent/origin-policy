# Policy Gate Violation Dashboard

Phase 3 Lane 4 — `policy_violations` テーブル / 集計ビューを Streamlit で可視化する。

## 機能
1. 違反件数の日次推移（rule_id 別 stacked bar）
2. actor 別違反内訳（mgmt_claude vs claude_code、円グラフ）
3. tom_interrupt 発生数の日次推移（折れ線）
4. PR 単位の違反 → 遅延分析（`v_policy_violations_pr_impact`）
5. rule_id 別 違反トップ 10 抜粋（`excerpt`）
6. 期間（7d / 30d / 90d / all）・`tool_name`・`rule_id` フィルタ

## 起動手順

### 1. 依存導入（uv 推奨）
```bash
cd ~/dev/origin-policy
uv venv .venv-dashboard
source .venv-dashboard/bin/activate
uv pip install -r dashboard/requirements.txt
```

`uv` が無ければ標準 venv でも可:
```bash
python3 -m venv .venv-dashboard
source .venv-dashboard/bin/activate
pip install -r dashboard/requirements.txt
```

### 2. 環境変数
プロジェクト直下に `.env` を作成（`.gitignore` で除外済）:
```
SUPABASE_URL=https://fqzsxjhhdzrliuuooqic.supabase.co
SUPABASE_SERVICE_KEY=<service_role_key>
```

`SUPABASE_SERVICE_KEY` は **必須**。RLS は `authenticated` SELECT のみ、anon は読めない（excerpt が機微の可能性があるため）。
service_role キーは RLS をバイパスするので、**ローカル運用専用**で扱い、リモートにデプロイする場合は専用 read-only ロールに置き換えること。

### 3. 起動
```bash
streamlit run dashboard/violation_dashboard.py
```
デフォルトで `http://localhost:8501` を開く。

## サンプルデータ
空 DB でも動くが、UI 確認用に 10 件の seed を用意:
```bash
psql "$DATABASE_URL" -f dashboard/seed.sql
```
または Supabase SQL Editor に貼り付けて実行。

## マイグレーション
- `migrations/20260426_policy_violations.sql` — テーブル + 2 ビュー
- `migrations/20260426_policy_violations_rls_tighten.sql` — anon を SELECT のみに絞る

両方適用済（origin-core, project_id: `fqzsxjhhdzrliuuooqic`）。

## DB 失敗時のフォールバック
`SUPABASE_URL` / KEY 未設定・接続失敗時は `st.error` バナーを出して停止する（クラッシュはしない）。

## デプロイ
本タスクの out of scope。Cloud Run / Streamlit Community Cloud は別タスクで起票。
