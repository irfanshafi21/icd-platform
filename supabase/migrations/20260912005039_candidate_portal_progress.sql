alter table public.screening_history add column if not exists application_id bigint references public.public_applications(id) on delete set null;
alter table public.interviews add column if not exists screening_id bigint references public.screening_history(id) on delete set null;
create index if not exists screening_application_idx on public.screening_history(application_id);
create index if not exists interviews_screening_idx on public.interviews(screening_id);
create table public.candidate_application_updates (
 application_id bigint primary key references public.public_applications(id) on delete cascade,
 status text,
 interview jsonb,
 updated_at timestamptz not null default now(),
 offer_sent_at timestamptz,
 offer_pdf_base64 text
);
alter table public.candidate_application_updates enable row level security;
revoke all on public.candidate_application_updates from anon, authenticated;
grant select, insert, update on public.candidate_application_updates to authenticated;
create policy "Candidates read only their own progress" on public.candidate_application_updates
 for select to authenticated using (exists(select 1 from public.public_applications a where a.id=application_id and a.candidate_user_id=(select auth.uid())));
create policy "Recruiters read their application progress" on public.candidate_application_updates
 for select to authenticated using (exists(select 1 from public.public_applications a join public.companies c on c.id=a.company_id where a.id=application_id and c.owner_user_id=(select auth.uid())));
create policy "Recruiters create their application progress" on public.candidate_application_updates
 for insert to authenticated with check (exists(select 1 from public.public_applications a join public.companies c on c.id=a.company_id where a.id=application_id and c.owner_user_id=(select auth.uid())));
create policy "Recruiters update their application progress" on public.candidate_application_updates
 for update to authenticated using (exists(select 1 from public.public_applications a join public.companies c on c.id=a.company_id where a.id=application_id and c.owner_user_id=(select auth.uid())))
 with check (exists(select 1 from public.public_applications a join public.companies c on c.id=a.company_id where a.id=application_id and c.owner_user_id=(select auth.uid())));
notify pgrst, 'reload schema';
-- Enforce company isolation even in installations with old permissive policies.
alter table public.screening_history enable row level security;
alter table public.interviews enable row level security;
create policy "Enforce screening company boundary" on public.screening_history as restrictive for all to public
 using (exists(select 1 from public.companies c where c.id=company_id and c.owner_user_id=(select auth.uid())))
 with check (exists(select 1 from public.companies c where c.id=company_id and c.owner_user_id=(select auth.uid())));
create policy "Enforce interview company boundary" on public.interviews as restrictive for all to public
 using (exists(select 1 from public.companies c where c.id=company_id and c.owner_user_id=(select auth.uid())))
 with check (exists(select 1 from public.companies c where c.id=company_id and c.owner_user_id=(select auth.uid())));
create policy "Bind portal submissions to verified identity" on public.public_applications as restrictive for insert to public
 with check (candidate_user_id is null or (candidate_user_id=(select auth.uid()) and lower(applicant_email)=lower(auth.jwt()->>'email')));
