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
  left join trends t on t.company_id=c.id;
  return result;
end;
$$;
revoke all on function public.owner_platform_analytics() from public, anon;
grant execute on function public.owner_platform_analytics() to authenticated;
