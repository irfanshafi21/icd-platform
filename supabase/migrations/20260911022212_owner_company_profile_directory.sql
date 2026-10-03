-- Matches the applied hosted migration. Intentionally owner-filtered view:
-- only non-secret profile fields, no anonymous grants, no write privileges.
create view public.owner_company_profiles with (security_barrier=true) as
select id,name,logo_base64,industry,website,company_size,created_at,
       verification_status,billing_plan,approved_at,approved_by
from public.companies
where lower(auth.jwt()->>'email') = 'irfanshafi210608@gmail.com';
revoke all on public.owner_company_profiles from public,anon;
grant select on public.owner_company_profiles to authenticated;
