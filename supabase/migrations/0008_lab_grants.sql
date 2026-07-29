-- 0008_lab_grants.sql
-- Close an EXECUTE grant that 0007 believed it had already removed.
--
-- WHAT WAS WRONG
--
-- 0007 ends with `revoke all on function ... from public`, on the assumption
-- that this clears Postgres's implicit EXECUTE-to-PUBLIC default. It does. But
-- Supabase additionally ships
--
--     alter default privileges in schema public
--         grant all on functions to anon, authenticated, service_role;
--
-- so every new function in `public` is *also* granted to `anon` explicitly, and
-- an explicit grant survives a revoke aimed at PUBLIC. `siap lab-check` caught
-- it by signing in as anon and calling the function successfully.
--
-- IMPACT: none observed. Both functions gate on
-- `current_annotator_code() is not null`, which resolves through auth.uid();
-- for anon that is NULL, so both returned zero rows. Measured, not assumed —
-- see docs/changelog.md. This migration removes the grant anyway, because a
-- function reachable by the public dashboard role is one careless `where`
-- clause away from being a leak, and defence that depends on a filter deeper
-- in the query is not defence.

revoke all on function public.current_annotator_code() from anon;
revoke all on function public.lab_queue(integer)       from anon;
revoke all on function public.lab_progress()           from anon;

-- Re-assert the intended posture, so this file states it in full rather than
-- leaving a reader to diff it against 0007.
grant execute on function public.current_annotator_code() to authenticated;
grant execute on function public.lab_queue(integer)       to authenticated;
grant execute on function public.lab_progress()           to authenticated;
