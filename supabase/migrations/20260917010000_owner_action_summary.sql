-- Owner operational summary contains no recipient, email body, or candidate details.
create or replace function public.owner_action_summary() returns jsonb
language plpgsql stable security definer set search_path='' as $$
declare result jsonb;
begin
 if coalesce(lower(auth.jwt()->>'email'),'')<>'irfanshafi210608@gmail.com' then
  raise exception 'Owner access required' using errcode='42501';
 end if;
 select jsonb_build_object(
  'pending_approvals',(select count(*) from public.company_registrations where status='pending'),
  'open_privacy_requests',(select count(*) from public.privacy_requests where status in ('received','reviewing')),
  'delivery_issues',(select count(*) from public.interview_delivery_jobs d join public.companies c on c.id=d.company_id where c.verification_status in ('approved','demo_approved') and (d.status='failed' or d.status in ('queued','sending') and d.updated_at<now()-interval '10 minutes')),
  'deliveries',coalesce((select jsonb_agg(x) from (
   select c.name as company_name,d.status,d.updated_at
   from public.interview_delivery_jobs d join public.companies c on c.id=d.company_id
   where c.verification_status in ('approved','demo_approved') and (d.status='failed' or d.status in ('queued','sending') and d.updated_at<now()-interval '10 minutes')
   order by d.updated_at limit 20
  )x),'[]'::jsonb),
  'generated_at',now()
 ) into result;
 return result;
end; $$;
revoke all on function public.owner_action_summary() from public,anon;
grant execute on function public.owner_action_summary() to authenticated;
