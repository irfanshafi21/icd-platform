revoke all on table public.public_applications from anon;
revoke all on sequence public.public_applications_id_seq from anon;

alter table public.public_applications
  alter column company_id type uuid
  using company_id::text::uuid;

alter table public.public_applications
  alter column company_id set not null;

alter table public.public_applications
  drop constraint if exists public_applications_company_id_fkey;

alter table public.public_applications
  add constraint public_applications_company_id_fkey
  foreign key (company_id) references public.companies(id) on delete cascade;

grant insert on table public.public_applications to anon;
grant usage on sequence public.public_applications_id_seq to anon;
grant select, update, delete on table public.public_applications to authenticated;

drop policy if exists "anyone can apply" on public.public_applications;

create policy "Public can submit valid job applications"
on public.public_applications for insert
to anon
with check (
  status = 'Submitted'
  and exists (
    select 1 from public.jobs
    where jobs.id = public_applications.job_id
      and jobs.company_id = public_applications.company_id
      and jobs.status = 'active'
      and (jobs.deadline is null or jobs.deadline >= current_date)
  )
);

create policy "Company owners can view public applications"
on public.public_applications for select
to authenticated
using (
  exists (
    select 1 from public.companies
    where companies.id = public_applications.company_id
      and companies.owner_user_id = (select auth.uid())
  )
);

create policy "Company owners can update public applications"
on public.public_applications for update
to authenticated
using (
  exists (
    select 1 from public.companies
    where companies.id = public_applications.company_id
      and companies.owner_user_id = (select auth.uid())
  )
)
with check (
  exists (
    select 1 from public.companies
    where companies.id = public_applications.company_id
      and companies.owner_user_id = (select auth.uid())
  )
);

create policy "Company owners can delete public applications"
on public.public_applications for delete
to authenticated
using (
  exists (
    select 1 from public.companies
    where companies.id = public_applications.company_id
      and companies.owner_user_id = (select auth.uid())
  )
);
