-- policy_violations テーブル定義
-- origin-core DB (project_id: fqzsxjhhdzrliuuooqic) に追加
-- Lane 4 dashboard の集計対象

CREATE TABLE IF NOT EXISTS policy_violations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- 違反イベント
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  source TEXT NOT NULL CHECK (source IN ('chrome_extension', 'stop_hook', 'cli_wrapper', 'question_router', 'report_validator')),
  rule_id TEXT NOT NULL CHECK (rule_id IN ('R1', 'R2', 'R3', 'R4', 'R5', 'bakuso_phrase', 'unknown')),

  -- コンテキスト
  actor TEXT NOT NULL CHECK (actor IN ('mgmt_claude', 'claude_code', 'unknown')),
  tool_name TEXT,                            -- 該当ツール（origin-ai / ec-manager 等）
  parent_goal_id TEXT,                        -- 違反発生時の親ゴール ID
  session_id TEXT,                            -- claude.ai セッション ID（Chrome 拡張用）

  -- 違反内容
  matched_pattern TEXT,                       -- 検出した regex / enum
  excerpt TEXT,                               -- 違反箇所の発言抜粋（先頭 500 文字）
  blocked BOOLEAN NOT NULL DEFAULT false,    -- BLOCK されたか（false なら警告のみ）

  -- 後続アクション追跡
  resolution TEXT CHECK (resolution IN ('auto_fixed', 'tom_interrupt', 'rejected', 'pending', 'ignored')),
  resolved_at TIMESTAMPTZ,
  resolution_note TEXT,

  -- 関連 PR / 差し戻し追跡
  related_pr_url TEXT,
  caused_pr_delay_minutes INTEGER,            -- この違反が PR 完了を遅らせた分

  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_policy_violations_occurred_at ON policy_violations (occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_policy_violations_rule_id ON policy_violations (rule_id);
CREATE INDEX IF NOT EXISTS idx_policy_violations_actor ON policy_violations (actor);
CREATE INDEX IF NOT EXISTS idx_policy_violations_tool_name ON policy_violations (tool_name);
CREATE INDEX IF NOT EXISTS idx_policy_violations_parent_goal_id ON policy_violations (parent_goal_id);
CREATE INDEX IF NOT EXISTS idx_policy_violations_resolution ON policy_violations (resolution) WHERE resolution = 'pending';

-- updated_at 自動更新
CREATE OR REPLACE FUNCTION update_policy_violations_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS policy_violations_updated_at ON policy_violations;
CREATE TRIGGER policy_violations_updated_at
  BEFORE UPDATE ON policy_violations
  FOR EACH ROW EXECUTE FUNCTION update_policy_violations_updated_at();

-- RLS は次の migration (20260426_policy_violations_rls_tighten.sql) で確定する。
-- ここでは RLS のみ有効化。
ALTER TABLE policy_violations ENABLE ROW LEVEL SECURITY;

-- 集計ビュー
CREATE OR REPLACE VIEW v_policy_violations_daily AS
SELECT
  DATE(occurred_at AT TIME ZONE 'Asia/Tokyo') AS day,
  rule_id,
  actor,
  source,
  COUNT(*) AS violation_count,
  SUM(CASE WHEN blocked THEN 1 ELSE 0 END) AS blocked_count,
  SUM(CASE WHEN resolution = 'tom_interrupt' THEN 1 ELSE 0 END) AS interrupt_count,
  AVG(caused_pr_delay_minutes)::numeric(10, 2) AS avg_delay_minutes
FROM policy_violations
GROUP BY DATE(occurred_at AT TIME ZONE 'Asia/Tokyo'), rule_id, actor, source
ORDER BY day DESC;

CREATE OR REPLACE VIEW v_policy_violations_pr_impact AS
SELECT
  related_pr_url,
  tool_name,
  parent_goal_id,
  COUNT(*) AS total_violations,
  SUM(caused_pr_delay_minutes) AS total_delay_minutes,
  ARRAY_AGG(DISTINCT rule_id) AS rules_violated,
  MIN(occurred_at) AS first_violation_at,
  MAX(resolved_at) AS last_resolved_at
FROM policy_violations
WHERE related_pr_url IS NOT NULL
GROUP BY related_pr_url, tool_name, parent_goal_id;
