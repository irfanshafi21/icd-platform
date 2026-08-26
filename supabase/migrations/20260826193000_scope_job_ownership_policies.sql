-- Keep recruiter-owned job policies away from anonymous public job viewers.
-- Public visitors continue to read only active portal jobs through the
-- separate "Public can view published jobs" policy.

alter policy "Company can view its own jobs" on public.jobs
to authenticated
using (
  company_id = (
    select companies.id
    from public.companies
    where companies.owner_user_id = (select auth.uid())
  )
);

alter policy "Company can insert its own jobs" on public.jobs
to authenticated
with check (
  company_id = (
    select companies.id
    from public.companies
    where companies.owner_user_id = (select auth.uid())
  )
);

alter policy "Company can update its own jobs" on public.jobs
to authenticated
using (
  company_id = (
    select companies.id
    from public.companies
    where companies.owner_user_id = (select auth.uid())
  )
)
with check (
  company_id = (
    select companies.id
    from public.companies
    where companies.owner_user_id = (select auth.uid())
  )
);

alter policy "Company can delete its own jobs" on public.jobs
to authenticated
using (
  company_id = (
    select companies.id
    from public.companies
    where companies.owner_user_id = (select auth.uid())
  )
);
