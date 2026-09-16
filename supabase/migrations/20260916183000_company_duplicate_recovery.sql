-- Reversible duplicate archival: preserves linked records and original credentials.
alter table public.companies add column if not exists duplicate_of uuid references public.companies(id);
alter table public.companies add column if not exists duplicate_archived_at timestamptz;

-- A contact may have multiple reviewed organizations, but only one pending request.
alter table public.company_registrations drop constraint if exists company_registrations_email_pending;
create unique index if not exists company_registration_pending_email on public.company_registrations(lower(trim(business_email))) where status='pending';

-- Keep the first Zoho workspace; these three identical copies have no hiring data.
update public.companies c set duplicate_of='964f998f-fb6a-4d6f-85db-c0c66430057f',duplicate_archived_at=now(),verification_status='suspended'
where c.id in ('8312edd1-5d7f-43fc-b494-b05a9af011cb','12508009-263f-43ba-b431-4b2d65aeade0','f3cd6bd3-f912-4673-8e4d-248cf51edc90')
  and not exists(select 1 from public.jobs j where j.company_id=c.id)
  and not exists(select 1 from public.screening_history s where s.company_id=c.id)
  and not exists(select 1 from public.public_applications a where a.company_id=c.id)
  and not exists(select 1 from public.interviews i where i.company_id=c.id)
  and exists(select 1 from public.companies original where original.id='964f998f-fb6a-4d6f-85db-c0c66430057f'
    and original.name=c.name and original.website=c.website and original.logo_base64=c.logo_base64
    and original.industry=c.industry and original.company_size=c.company_size);

-- Explicitly requested: hide the already-deactivated Nvidia duplicate, preserving its jobs.
update public.companies set duplicate_of='45ee6600-5fcc-48e4-b015-4abb2af8019c',duplicate_archived_at=now()
where id='94e4f265-9fec-49a7-a67f-b477b13d52db' and verification_status='suspended';

-- Finish the previously attempted approval that provisioned Zoho but failed on the old constraint.
update public.company_registrations r set status='approved',company_id=c.id,reviewed_at=c.approved_at,
 review_notes=concat_ws(E'\n',nullif(r.review_notes,''),'Recovered interrupted approval; duplicate workspaces archived.')
from public.companies c where r.id='ee162c64-a48a-4bf3-a4b6-0479c323bd46' and r.status='pending'
 and c.id='964f998f-fb6a-4d6f-85db-c0c66430057f' and r.access_code=c.access_code
 and c.approved_by='irfanshafi210608@gmail.com';

create unique index if not exists companies_unique_identity on public.companies
 (lower(trim(name)),lower(rtrim(trim(coalesce(website,'')),'/')),md5(coalesce(logo_base64,'')),lower(trim(coalesce(industry,''))),lower(trim(coalesce(company_size,''))))
 where duplicate_of is null and (coalesce(website,'')<>'' or coalesce(logo_base64,'')<>'');

create or replace view public.companies_public as
 select id,name,logo_base64,industry from public.companies
 where duplicate_of is null and verification_status in ('approved','demo_approved');
create or replace view public.owner_company_profiles with(security_barrier=true) as
 select id,name,logo_base64,industry,website,company_size,created_at,verification_status,billing_plan,approved_at,approved_by,access_code
 from public.companies where duplicate_of is null and lower(auth.jwt()->>'email')='irfanshafi210608@gmail.com';

-- Aggregate reporting only. No candidate identity, files, or company credentials.
create or replace function public.owner_platform_analytics()
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare result jsonb;
begin
  if coalesce(lower(auth.jwt()->>'email'), '') <> 'irfanshafi210608@gmail.com' then
    raise exception 'Owner access required' using errcode = '42501';
  end if;
  with screenings as (
    select company_id, count(*) as screened,
      count(*) filter (where decision_status = 'Selected') as selected,
      count(*) filter (where decision_status = 'Rejected') as rejected,
      count(*) filter (where overall_score >= 80) as strong,
      count(*) filter (where overall_score >= 50 and overall_score < 80) as potential,
      count(*) filter (where overall_score < 50) as low,
      count(*) filter (where overall_score is null) as unscored,
      round(avg(overall_score)::numeric, 1) as average_score,
      max(screened_at) as last_screened
    from public.screening_history where status is distinct from 'cleared' group by company_id
  ), roles as (
    select company_id, count(*) as jobs,
      count(*) filter (where status = 'active') as active_jobs
    from public.jobs group by company_id
  ), applications as (
    select company_id, count(*) as applications from public.public_applications group by company_id
  ), meetings as (
    select company_id, count(*) as interviews,
      count(*) filter (where status = 'Scheduled') as scheduled,
      count(*) filter (where status = 'Completed') as completed,
      count(*) filter (where status = 'Cancelled') as cancelled
    from public.interviews group by company_id
  ), daily as (
    select company_id, (screened_at at time zone 'UTC')::date as day, count(*) as count
    from public.screening_history
    where status is distinct from 'cleared'
      and screened_at >= ((now() at time zone 'UTC')::date - 29) at time zone 'UTC'
    group by company_id, (screened_at at time zone 'UTC')::date
  ), trends as (
    select company_id, jsonb_agg(jsonb_build_object('day',day,'count',count) order by day) as trend
    from daily group by company_id
  )
  select jsonb_build_object('generated_at', now(), 'companies', coalesce(jsonb_agg(
    jsonb_build_object('id',c.id,'name',c.name,
      'jobs',coalesce(r.jobs,0),'active_jobs',coalesce(r.active_jobs,0),
      'applications',coalesce(a.applications,0),'screened',coalesce(s.screened,0),
      'selected',coalesce(s.selected,0),'rejected',coalesce(s.rejected,0),
      'strong',coalesce(s.strong,0),'potential',coalesce(s.potential,0),
      'low',coalesce(s.low,0),'unscored',coalesce(s.unscored,0),'average_score',s.average_score,
      'interviews',coalesce(m.interviews,0),'scheduled',coalesce(m.scheduled,0),
      'completed',coalesce(m.completed,0),'cancelled',coalesce(m.cancelled,0),
      'last_screened',s.last_screened,'trend',coalesce(t.trend,'[]'::jsonb)
    ) order by c.name), '[]'::jsonb)) into result
  from public.companies c
  left join screenings s on s.company_id=c.id
  left join roles r on r.company_id=c.id
  left join applications a on a.company_id=c.id
  left join meetings m on m.company_id=c.id
  left join trends t on t.company_id=c.id
  where c.duplicate_of is null and c.verification_status in ('approved','demo_approved');
  return result;
end;
$$;
revoke all on function public.owner_platform_analytics() from public, anon;
grant execute on function public.owner_platform_analytics() to authenticated;
