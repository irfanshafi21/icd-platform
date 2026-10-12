-- Bound login guessing across all clients; fixed windows do not extend on blocked requests.
create schema if not exists icd_private;
revoke all on schema icd_private from public, anon, authenticated;
create table icd_private.company_login_attempts (
 company_id uuid primary key references public.companies(id) on delete cascade,
 attempts integer not null default 0,
 started_at timestamptz not null default now()
);
alter table icd_private.company_login_attempts enable row level security;
revoke all on icd_private.company_login_attempts from public, anon, authenticated;

create or replace function public.get_company_login(p_company_id uuid,p_code text)
returns table(auth_email text,auth_password text)
language plpgsql security definer set search_path='' as $$
declare n integer;
begin
 if p_code is null or p_code !~ '^[0-9]{4}$' then return; end if;
 if not exists(select 1 from public.companies where id=p_company_id and verification_status in ('approved','demo_approved')) then return; end if;
 insert into icd_private.company_login_attempts as a(company_id,attempts,started_at)
 values(p_company_id,1,clock_timestamp())
 on conflict(company_id) do update set
 attempts=case when a.started_at <= clock_timestamp()-interval '15 minutes' then 1 else least(a.attempts+1,11) end,
 started_at=case when a.started_at <= clock_timestamp()-interval '15 minutes' then clock_timestamp() else a.started_at end
 returning attempts into n;
 if n>10 then return; end if;
 return query select c.internal_auth_email,c.internal_auth_password from public.companies c
 where c.id=p_company_id and c.access_code=p_code and c.verification_status in ('approved','demo_approved');
end; $$;
revoke all on function public.get_company_login(uuid,text) from public;
grant execute on function public.get_company_login(uuid,text) to anon,authenticated;
-- Remove the independent unthrottled verification oracle: both paths share the same budget.
create or replace function public.verify_company_access_code(p_company_id uuid,p_code text)
returns boolean language sql security invoker set search_path='' as $$
 select exists(select 1 from public.get_company_login(p_company_id,p_code));
$$;
