alter table public.jobs add column if not exists published_to_portal boolean not null default false;
alter table public.public_applications add column if not exists candidate_user_id uuid references auth.users(id) on delete set null;

create table if not exists public.candidate_profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  full_name text not null, email text not null, phone text,
  created_at timestamptz not null default now(), updated_at timestamptz not null default now()
);
create index if not exists jobs_portal_listing_idx on public.jobs (published_to_portal, status, created_at desc)
  where published_to_portal = true and status = 'active';
create index if not exists public_applications_candidate_idx on public.public_applications (candidate_user_id, applied_at desc)
  where candidate_user_id is not null;

alter table public.candidate_profiles enable row level security;
grant select on table public.jobs to anon, authenticated;
grant select, insert, update on table public.candidate_profiles to authenticated;
grant insert, select on table public.public_applications to authenticated;

drop policy if exists "Allow all access for now" on public.jobs;
drop policy if exists "Public can view published jobs" on public.jobs;
create policy "Public can view published jobs" on public.jobs for select to anon
using (published_to_portal = true and status = 'active' and (deadline is null or deadline >= current_date));
drop policy if exists "Authenticated users can view published jobs" on public.jobs;
create policy "Authenticated users can view published jobs" on public.jobs for select to authenticated
using ((published_to_portal = true and status = 'active' and (deadline is null or deadline >= current_date)) or exists
  (select 1 from public.companies where companies.id = jobs.company_id and companies.owner_user_id = (select auth.uid())));

create policy "Candidates can view their profile" on public.candidate_profiles for select to authenticated using ((select auth.uid()) = user_id);
create policy "Candidates can create their profile" on public.candidate_profiles for insert to authenticated with check ((select auth.uid()) = user_id);
create policy "Candidates can update their profile" on public.candidate_profiles for update to authenticated
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy "Candidates can submit their application" on public.public_applications for insert to authenticated
with check (candidate_user_id = (select auth.uid()) and status = 'Submitted' and exists
  (select 1 from public.jobs where jobs.id = public_applications.job_id and jobs.company_id = public_applications.company_id
   and jobs.published_to_portal = true and jobs.status = 'active' and (jobs.deadline is null or jobs.deadline >= current_date)));
create policy "Candidates can view their applications" on public.public_applications for select to authenticated
using (candidate_user_id = (select auth.uid()));
