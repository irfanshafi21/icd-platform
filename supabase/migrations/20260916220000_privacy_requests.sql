-- Optional request tracking. No candidate records are erased by this migration.
create table public.privacy_requests (
 id uuid primary key default gen_random_uuid(),
 user_id uuid not null references auth.users(id),
 email text not null,
 kind text not null check (kind in ('access','correction','deletion')),
 details text not null default '' check (length(details)<=2000),
 status text not null default 'received' check (status in ('received','reviewing','completed','declined')),
 response text not null default '' check (length(response)<=2000),
 created_at timestamptz not null default now(),
 updated_at timestamptz not null default now()
);
create unique index privacy_one_open_request on public.privacy_requests(user_id,kind)
 where status in ('received','reviewing');
alter table public.privacy_requests enable row level security;
revoke all on public.privacy_requests from anon, authenticated;
grant select on public.privacy_requests to authenticated;
grant insert(user_id,email,kind,details) on public.privacy_requests to authenticated;
grant update(status,response,updated_at) on public.privacy_requests to authenticated;
create policy privacy_read on public.privacy_requests for select to authenticated
 using(user_id=auth.uid() or lower(auth.jwt()->>'email')='irfanshafi210608@gmail.com');
create policy privacy_submit on public.privacy_requests for insert to authenticated
 with check(user_id=auth.uid() and lower(email)=lower(auth.jwt()->>'email'));
create policy privacy_owner_update on public.privacy_requests for update to authenticated
 using(lower(auth.jwt()->>'email')='irfanshafi210608@gmail.com')
 with check(lower(auth.jwt()->>'email')='irfanshafi210608@gmail.com');

create table public.privacy_request_events (
 id bigint generated always as identity primary key,
 request_id uuid not null references public.privacy_requests(id),
 actor_id uuid, status text not null, occurred_at timestamptz not null default now()
);
alter table public.privacy_request_events enable row level security;
revoke all on public.privacy_request_events from anon,authenticated;
grant select on public.privacy_request_events to authenticated;
create policy privacy_events_owner on public.privacy_request_events for select to authenticated
 using(lower(auth.jwt()->>'email')='irfanshafi210608@gmail.com');
create function public.record_privacy_request_event() returns trigger language plpgsql security definer set search_path='' as $$
begin
 if TG_OP='UPDATE' and new.status in ('completed','declined') and length(trim(new.response))=0 then
  raise exception 'Explain the outcome before closing a request';
 end if;
 insert into public.privacy_request_events(request_id,actor_id,status) values(new.id,auth.uid(),new.status);
 return new;
end; $$;
-- AFTER ensures the parent request exists before inserting the audit event.
create trigger privacy_request_audit after insert or update on public.privacy_requests
 for each row execute function public.record_privacy_request_event();
revoke all on function public.record_privacy_request_event() from public,anon,authenticated;

-- Persist invitations before attempting delivery, including after a process restart.
create table public.interview_delivery_jobs (
 id uuid primary key default gen_random_uuid(),
 company_id uuid not null references public.companies(id),
 interview_id bigint not null unique references public.interviews(id) on delete cascade,
 recipient text not null, subject text not null, body text not null,
 status text not null default 'queued' check(status in ('queued','sending','sent','failed')),
 updated_at timestamptz not null default now(),
 created_at timestamptz not null default now()
);
alter table public.interview_delivery_jobs enable row level security;
revoke all on public.interview_delivery_jobs from anon,authenticated;
grant select,insert,update on public.interview_delivery_jobs to authenticated;
create policy interview_delivery_company on public.interview_delivery_jobs for all to authenticated
 using(exists(select 1 from public.companies c where c.id=company_id and c.owner_user_id=auth.uid() and c.verification_status in ('approved','demo_approved')))
 with check(exists(select 1 from public.companies c where c.id=company_id and c.owner_user_id=auth.uid() and c.verification_status in ('approved','demo_approved'))
 and exists(select 1 from public.interviews i where i.id=interview_id and i.company_id=interview_delivery_jobs.company_id));
