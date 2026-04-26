-- Tighten RLS on policy_violations: anon is read-only, writes require service_role / authenticated.
-- Reason: this table is an audit log; allowing anon to INSERT/UPDATE/DELETE would let any
-- holder of the anon key tamper with violation evidence. service_role bypasses RLS by default,
-- so writers (Lane 1/2/3) must use SUPABASE_SERVICE_KEY. The dashboard reads only and stays on anon.

DROP POLICY IF EXISTS "Allow all for anon" ON policy_violations;
CREATE POLICY "anon read-only" ON policy_violations
  FOR SELECT TO anon
  USING (true);
