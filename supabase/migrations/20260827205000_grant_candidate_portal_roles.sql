-- Data API grants are separate from RLS policies. Candidate data remains
-- protected by the ownership policies created in candidate_portal.sql.
grant select, insert, update on table public.candidate_profiles to authenticated;
grant insert, select on table public.public_applications to authenticated;
grant select on table public.jobs to anon, authenticated;

notify pgrst, 'reload schema';
