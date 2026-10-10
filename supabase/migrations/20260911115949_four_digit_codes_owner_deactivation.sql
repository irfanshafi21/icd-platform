create or replace view public.owner_company_profiles with (security_barrier=true) as select id,name,logo_base64,industry,website,company_size,created_at,verification_status,billing_plan,approved_at,approved_by,access_code from public.companies where lower(auth.jwt()->>'email')='irfanshafi210608@gmail.com';
create or replace function public.owner_deactivate_company(p_id uuid) returns boolean language plpgsql security definer set search_path='' as $$ begin
if auth.uid() is null or lower(auth.jwt()->>'email') is distinct from 'irfanshafi210608@gmail.com' then raise exception 'Owner only'; end if;
update public.companies set verification_status='suspended' where id=p_id; return found; end $$;
revoke all on function public.owner_deactivate_company(uuid) from public,anon;
grant execute on function public.owner_deactivate_company(uuid) to authenticated;
alter policy "public can submit pending company registrations" on public.company_registrations with check (status='pending' and company_id is null and reviewed_at is null and (access_code is null or access_code ~ '^[0-9]{4}$'));
create table public.registration_tracking_attempts (email text primary key, attempts int not null default 0, started timestamptz not null default now());
alter table public.registration_tracking_attempts enable row level security;
revoke all on public.registration_tracking_attempts from public,anon,authenticated;
create or replace function public.track_company_registration(p_email text,p_code text)
returns table(company_name text,status text,company_id uuid,reviewed_at timestamptz)
language plpgsql security definer set search_path='' as $$ declare n int; begin
insert into public.registration_tracking_attempts as a(email,attempts) values(lower(trim(p_email)),1)
on conflict(email) do update set attempts=case when a.started<now()-interval '15 minutes' then 1 else a.attempts+1 end,started=case when a.started<now()-interval '15 minutes' then now() else a.started end returning attempts into n;
if n>5 then return; end if;
return query select r.company_name,r.status,r.company_id,r.reviewed_at from public.company_registrations r where lower(r.business_email)=lower(trim(p_email)) and r.access_code=p_code and p_code ~ '^[0-9]{4}$' order by r.created_at desc limit 1; end $$;
create or replace function public.get_company_login(p_company_id uuid,p_code text) returns table(auth_email text,auth_password text) language sql security definer set search_path='' as $$ select c.internal_auth_email,c.internal_auth_password from public.companies c where c.id=p_company_id and c.access_code=p_code and c.verification_status in ('approved','demo_approved'); $$;
update public.companies set access_code=lpad((floor(random()*10000)::int)::text,4,'0') where access_code is not null and access_code !~ '^[0-9]{4}$';
update public.company_registrations r set access_code=c.access_code from public.companies c where r.company_id=c.id and r.access_code is not null and r.access_code !~ '^[0-9]{4}$';
update public.company_registrations set access_code=lpad((floor(random()*10000)::int)::text,4,'0') where access_code is not null and access_code !~ '^[0-9]{4}$';
