-- Sample data for local Streamlit dev.
-- 10 rows covering rule_id / actor / source / blocked / resolution diversity.
-- Run on origin-core (project_id: fqzsxjhhdzrliuuooqic) AFTER 20260426_policy_violations.sql is applied.

INSERT INTO policy_violations (
  occurred_at, source, rule_id, actor, tool_name, parent_goal_id, session_id,
  matched_pattern, excerpt, blocked, resolution, resolved_at, resolution_note,
  related_pr_url, caused_pr_delay_minutes
) VALUES
  (now() - interval '1 day',  'stop_hook',         'R1', 'claude_code',  'origin-ai',     'goal-core-read-write', 'sess-001',
   'forbidden_question',     'どちらにしますか？確認します。', true,  'tom_interrupt', now() - interval '23 hours', 'トムが回答',
   'https://github.com/originaiagent/origin-ai/pull/101', 12),

  (now() - interval '2 days', 'chrome_extension',  'R2', 'mgmt_claude',  'origin-ec',     'goal-core-read-write', 'sess-002',
   'out_of_parent_goal',     'ついでに別タスクも実行します', true,  'rejected',      now() - interval '47 hours', 'BLOCK',
   'https://github.com/originaiagent/origin-ec/pull/55', 30),

  (now() - interval '3 days', 'cli_wrapper',       'R3', 'claude_code',  'origin-ai',     'goal-core-read-write', NULL,
   'uuid_in_text',           'parent_goal_id=22107c50-2e00-4332-bb48-28db98c252f2 を…', false, 'auto_fixed',    now() - interval '71 hours', '自動マスク',
   'https://github.com/originaiagent/origin-ai/pull/102', 5),

  (now() - interval '4 days', 'report_validator',  'R4', 'claude_code',  'ec-manager',    'goal-core-read-write', NULL,
   'no_evidence',            '完了しました（証拠なし）', true, 'rejected',      now() - interval '95 hours', '裏取り不足',
   'https://github.com/originaiagent/ec-manager/pull/30', 45),

  (now() - interval '5 days', 'stop_hook',         'R5', 'mgmt_claude',  NULL,            'goal-core-read-write', 'sess-005',
   'invalid_task_package',   'task_package schema 違反', true,  'rejected',      now() - interval '119 hours', '再起票',
   NULL, NULL),

  (now() - interval '6 days', 'chrome_extension',  'bakuso_phrase', 'mgmt_claude', 'origin-ai', 'goal-core-read-write', 'sess-006',
   'phrase:爆速',            '爆速で進めます！', false, 'ignored',       now() - interval '143 hours', '警告のみ',
   NULL, NULL),

  (now() - interval '7 days', 'question_router',   'R1', 'claude_code',  'origin-policy', 'goal-core-read-write', NULL,
   'forbidden_question',     'どうしますか？',           false, 'pending',       NULL, NULL,
   'https://github.com/originaiagent/origin-policy/pull/3', NULL),

  (now() - interval '10 days','stop_hook',         'R2', 'claude_code',  'origin-ai',     'goal-core-read-write', NULL,
   'out_of_parent_goal',     '関係ないリファクタを始めます', true,  'tom_interrupt', now() - interval '239 hours', '差し戻し',
   'https://github.com/originaiagent/origin-ai/pull/103', 60),

  (now() - interval '15 days','cli_wrapper',       'unknown', 'unknown', NULL,           'goal-core-read-write', NULL,
   NULL,                     'classifier 失敗ケース',     false, 'pending',       NULL, NULL,
   NULL, NULL),

  (now() - interval '40 days','report_validator',  'R4', 'claude_code',  'ec-manager',    'goal-core-read-write', NULL,
   'no_evidence',            '裏取りなし完了報告',        true,  'rejected',      now() - interval '959 hours', '差し戻し',
   'https://github.com/originaiagent/ec-manager/pull/31', 90)
;
