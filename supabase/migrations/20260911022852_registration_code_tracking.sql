alter policy "public can submit pending company registrations" on public.company_registrations with check (status='pending' and company_id is null and reviewed_at is null and (access_code is null or length(access_code)>=24));
create or replace function public.track_company_registration(p_email text,p_code text)
returns table(company_name text,status text,company_id uuid,reviewed_at timestamptz)
language sql security definer set search_path='' as $$
 select r.company_name,r.status,r.company_id,r.reviewed_at from public.company_registrations r
 where lower(r.business_email)=lower(trim(p_email)) and r.access_code=p_code and length(p_code)>=24
 order by r.created_at desc limit 1;
$$;
revoke all on function public.track_company_registration(text,text) from public;
grant execute on function public.track_company_registration(text,text) to anon,authenticated;
