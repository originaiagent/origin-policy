-- Tighten RLS on policy_violations: SELECT for authenticated only (no anon).
-- Reason: this is an audit log; the `excerpt` column may contain sensitive content
-- (PII, internal identifiers, AI output). Anon (public Supabase API key) must not see it.
-- Writers (Lane 1/2/3) use SUPABASE_SERVICE_KEY which bypasses RLS.
-- The dashboard uses SUPABASE_SERVICE_KEY (admin-internal tool, never exposed).

DROP POLICY IF EXISTS "Allow all for anon" ON policy_violations;
DROP POLICY IF EXISTS "anon read-only" ON policy_violations;
CREATE POLICY "authenticated read-only" ON policy_violations
  FOR SELECT TO authenticated
  USING (true);
